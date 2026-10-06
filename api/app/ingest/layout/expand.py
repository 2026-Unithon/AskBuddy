"""⑤ 사실 전개. 몇 행씩 싼 모델에 텍스트로 주고, 빠진 숫자·x 칸은 코드가 짚어 다시 묻는다."""
import logging
import re

from app.config import get_settings
from app.ingest.layout import prompts
from app.ingest.layout.schemas import ExpandResult, LayoutFact, ProseResult, TableResult
from app.ingest.providers import measured_generate, parse_model_spec
from app.ingest.schemas import Evidence, ExtractedAssertion

logger = logging.getLogger(__name__)
_NUM = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d])")
_UNREADABLE = "[판독 불가]"
# 천 단위 쉼표만 지운다 (숫자 사이 쉼표). 소수점은 건드리지 않는다
_THOUSANDS = re.compile(r"(?<=\d),(?=\d)")


def _label(table: TableResult, i: int) -> str:
    return table.rows[i].label or f"행{i + 1}"


def _label_col(table: TableResult) -> int | None:
    return table.region.table.row_label_column if table.region.table else None


def row_text(table: TableResult, i: int, key: str | None = None) -> str:
    """key 는 배치 안에서 우리가 붙인 행 키(R1…). 모델은 row_ref 에 이 키를 적는다."""
    key = key or f"R{i + 1}"
    cells = []
    for col, cell in enumerate(table.rows[i].cells):
        name = table.header[col] if col < len(table.header) else f"열{col + 1}"
        value = _UNREADABLE if (i, col) in table.unreadable else cell
        cells.append(f"{name}={value}")
    label = table.rows[i].label or "-"
    return f"[{key} | 라벨 {label}] " + " ; ".join(cells)


def row_tokens(table: TableResult, i: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for col, cell in enumerate(table.rows[i].cells):
        if col == _label_col(table) or (i, col) in table.unreadable:
            continue
        text = _THOUSANDS.sub("", cell)
        if text.strip().lower() == "x":
            out.append(("NEG", table.header[col] if col < len(table.header) else f"열{col + 1}"))
            continue
        out += [("NUM", n) for n in _NUM.findall(text)]
    return out


def _fact_text(f: LayoutFact) -> str:
    return _THOUSANDS.sub("", " ".join([f.value, f.unit, f.original_assertion, *f.conditions, *f.exceptions]))


def missing_tokens(tokens: list[tuple[str, str]], facts: list[LayoutFact]) -> list[tuple[str, str]]:
    missing = []
    for kind, tok in tokens:
        if kind == "NUM":
            pat = re.compile(rf"(?<![\d.]){re.escape(tok)}(?![\d])")
            ok = any(pat.search(_fact_text(f)) for f in facts)
        else:
            name = tok.replace(" ", "")

            def _neg(f: LayoutFact) -> bool:
                attr = f.attribute.replace(" ", "")
                return f.polarity == "NEGATE" and (
                    name in attr or (attr != "" and attr in name) or tok in f.original_assertion)
            ok = any(_neg(f) for f in facts)
        if not ok:
            missing.append((kind, tok))
    return missing


def _norm_ref(raw: str) -> str:
    """모델이 행 키 뒤에 라벨까지 되풀이해도(`R1|라벨3`, `R12 라벨 1`) 앞의 R 키만 쓴다."""
    norm = re.sub(r"[\s\[\]()]", "", raw).upper()
    m = re.match(r"R\d+", norm)
    return m.group(0) if m else norm


def _dedup(facts: list[LayoutFact]) -> list[LayoutFact]:
    seen, out = set(), []
    for f in facts:
        k = (f.attribute, f.variant, f.value, f.unit, f.polarity, f.order)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def _to_assertion(f: LayoutFact, table_or_prose, index: int, row: str | None, row_index: int | None = None) -> ExtractedAssertion:
    s = get_settings()
    region = table_or_prose.region
    a = ExtractedAssertion(
        local_ref=f"{region.region_id}.{'t' if row_index is None else row_index}.{index}", original_assertion=f.original_assertion,
        subject=f.subject, attribute=f.attribute, value=f.value, variant=f.variant, unit=f.unit,
        polarity=f.polarity, conditions=list(f.conditions), exceptions=list(f.exceptions),
        order=f.order, evidence=Evidence(), confidence=s.layout_fact_confidence)
    loc = {"page": region.page, "region": region.region_id, "bbox": list(region.box)}
    if row is not None:
        loc["row"] = row
    a._layout_locator = loc
    return a


async def _call(table, rows_text, missing, label, ctx, usage_sink, raw_sink) -> ExpandResult:
    s = get_settings()
    return await measured_generate(
        parse_model_spec(s.layout_expand_model),
        prompts.render("expand", header=" | ".join(table.header), rows=rows_text, missing=missing),
        [], ExpandResult, usage_sink=usage_sink, usage_context=ctx(label), raw_sink=raw_sink,
        what="사실 전개", mock_build=lambda: ExpandResult(facts=[]))


async def expand_table(table: TableResult, *, ctx, usage_sink, raw_sink) -> tuple[list[ExtractedAssertion], list[str]]:
    s = get_settings()
    region = table.region
    assertions: list[ExtractedAssertion] = []
    unresolved = [f"[판독 불가] {region.page}쪽 {region.region_id} 행 {_label(table, r)} "
                  f"'{table.header[c] if c < len(table.header) else c}' 칸: {why}"
                  for (r, c), why in sorted(table.unreadable.items())]
    n = s.layout_expand_batch_rows
    for start in range(0, len(table.rows), n):
        idx = list(range(start, min(start + n, len(table.rows))))
        keys = {f"R{j + 1}": i for j, i in enumerate(idx)}      # 배치 안에서 유일한 행 키
        key_of = {i: k for k, i in keys.items()}
        tag = f"{region.region_id}.x{start // n}"
        got = await _call(table, "\n".join(row_text(table, i, key_of[i]) for i in idx), "",
                          tag, ctx, usage_sink, raw_sink)
        per_row: dict[int, list[LayoutFact]] = {i: [] for i in idx}

        def _place(facts):
            for f in facts:
                target = keys.get(_norm_ref(f.row_ref))
                if target is None:
                    unresolved.append(f"[행 연결 실패] {region.page}쪽 {region.region_id}: "
                                      f"row_ref={f.row_ref} — {f.original_assertion}")
                else:
                    per_row[target].append(f)
        _place(got.facts)
        gaps = {i: missing_tokens(row_tokens(table, i), per_row[i]) for i in idx}
        gap_rows = [i for i in idx if gaps[i]]
        if gap_rows:
            hint = "\n이전 응답에서 빠진 값: " + " ; ".join(
                f"[{key_of[i]}] " + ", ".join(t for _, t in gaps[i]) for i in gap_rows)
            retry = await _call(table, "\n".join(row_text(table, i, key_of[i]) for i in gap_rows),
                                hint, tag + "r", ctx, usage_sink, raw_sink)
            # 재시도 응답에서는 틈이 있던 행의 사실만 받는다
            _place([f for f in retry.facts if keys.get(_norm_ref(f.row_ref)) in gap_rows])
        for i in idx:
            label = _label(table, i)
            mine = _dedup(per_row[i])
            for k, f in enumerate(mine):
                assertions.append(_to_assertion(f, table, k, label, i))
            for kind, tok in missing_tokens(row_tokens(table, i), mine):
                shown = f"{tok}(x)" if kind == "NEG" else tok
                unresolved.append(f"[전개 미반영] {region.page}쪽 {region.region_id} 행 {label}: {shown}")
    return assertions, unresolved


async def expand_text(prose: ProseResult, *, source_id: int, glossary, ctx, usage_sink,
                      raw_sink) -> tuple[list[ExtractedAssertion], list[str]]:
    """문단·각주·사진 글은 기존 사실 추출(텍스트 입력)로 넘긴다."""
    from app.ingest.extract import extract_facts

    if not prose.lines:
        return [], []
    result = await extract_facts(source_id=source_id, source_type="SCAN", text="\n".join(prose.lines),
                                 glossary=glossary, media=[], usage_sink=usage_sink,
                                 usage_context=ctx(f"{prose.region.region_id}.x"), raw_sink=raw_sink)
    region = prose.region
    for a in result.assertions:
        a.local_ref = f"{region.region_id}.t.{a.local_ref}"
        a.requires = [f"{region.region_id}.t.{r}" for r in a.requires]
        a._layout_locator = {"page": region.page, "region": region.region_id, "bbox": list(region.box)}
    return list(result.assertions), list(result.unresolved)
