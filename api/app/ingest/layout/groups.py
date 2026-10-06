"""⑥ 세로 병합 칸(구분 열) 처리. 띠마다 조각만 보이는 칸을 한 번 더 판단해 범위 행에 채운다."""
import logging
import re
from pathlib import Path

from app.config import get_settings
from app.ingest.layout import prompts
from app.ingest.layout.recheck import crop_scale
from app.ingest.layout.schemas import GroupSpan, GroupSpans, PageImage, TableResult
from app.ingest.layout.transcribe import crop_zoom
from app.ingest.providers import budget, measured_generate, parse_model_spec

logger = logging.getLogger(__name__)
_INT = re.compile(r"\s*(\d+)\s*[.)]?\s*$")
_HOT_ICE = re.compile(r"(?<![A-Za-z])(HOT|ICE)(?![A-Za-z])", re.IGNORECASE)


def _num(text: str | None) -> int | None:
    m = _INT.match(text or "")
    return int(m.group(1)) if m else None


def apply_spans(table: TableResult, spans: list[GroupSpan]) -> int:
    """범위 안(숫자 라벨) 행의 칸을 병합 라벨로 덮는다. 덮은 행 수를 돌려준다."""
    covered: set[int] = set()
    for sp in spans:
        lo, hi = _num(sp.first_row), _num(sp.last_row)
        if lo is None or hi is None or not (0 <= sp.column_index < len(table.header)):
            continue
        for i, row in enumerate(table.rows):
            n = _num(row.label)
            if n is None or not (lo <= n <= hi):
                continue
            while len(row.cells) <= sp.column_index:
                row.cells.append("")
            row.cells[sp.column_index] = sp.label
            table.group_columns.add(sp.column_index)
            table.group_cells.add((i, sp.column_index))
            covered.add(i)
    return len(covered)


def variant_of(text: str) -> str:
    """글에서 단어 경계의 HOT/ICE 를 찾는다. 정확히 한 종류면 그 값(대문자), 아니면 ""."""
    found = {m.upper() for m in _HOT_ICE.findall(text or "")}
    return found.pop() if len(found) == 1 else ""


def row_variant(table: TableResult, i: int) -> str:
    """병합 라벨이 덮은 칸에서만 규격을 읽는다. 일반 칸(메뉴명 등)의 ICE 는 보지 않는다."""
    if table.group_cells:
        cols = {c for (r, c) in table.group_cells if r == i}
    else:
        cols = set(table.group_columns)
    if not cols or i >= len(table.rows):
        return ""
    cells = table.rows[i].cells
    found = {variant_of(cells[c]) for c in cols if c < len(cells)} - {""}
    return found.pop() if len(found) == 1 else ""


async def resolve_groups(table: TableResult, page: PageImage, workdir: Path, *, ctx, usage_sink,
                         raw_sink) -> list[str]:
    """표 구역을 한 번 더 보고 세로 병합 칸을 채운다. 덮은 행 수는 table.group_rows 에 둔다."""
    s = get_settings()
    region = table.region
    if not any(_num(r.label) is not None for r in table.rows):
        return []
    try:
        box = region.box
        img = crop_zoom(page.path, box, crop_scale(box, 1.0, s.layout_crop_max_px),
                        workdir / f"{region.region_id}-g.png")
        got: GroupSpans = await measured_generate(
            parse_model_spec(s.layout_group_model),
            prompts.render("groups", header=" | ".join(f"{i}:{h}" for i, h in enumerate(table.header))),
            [img], GroupSpans, usage_sink=usage_sink, usage_context=ctx(f"{region.region_id}.g"),
            raw_sink=raw_sink, what="병합 칸", mock_build=lambda: GroupSpans(spans=[]))
        table.group_rows = apply_spans(table, got.spans)
    except budget.BudgetExceeded:
        raise
    except Exception as exc:
        logger.warning("병합 칸 실패 %s: %s", region.region_id, exc)
        return [f"[병합 칸 실패] {region.page}쪽 {region.region_id}: {type(exc).__name__}"]
    return []
