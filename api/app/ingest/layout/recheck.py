"""④ 재확인. 행 문제는 띠 재전사, 칸 문제는 구조화 출력 턴 루프(확대 요청 또는 답)."""
import logging
from pathlib import Path

from app.config import get_settings
from app.ingest.layout import prompts
from app.ingest.layout.schemas import (BandRow, Box, Caps, CropRequest, PageImage, RecheckTurn,
                                       TableResult)
from app.ingest.layout.transcribe import (check_table, crop_zoom, fill_down, merge_bands,
                                          merge_window, transcribe_table)
from app.ingest.providers import measured_generate, parse_model_spec

logger = logging.getLogger(__name__)
_CAP = "cap"


def crop_box(region_box: Box, req: CropRequest) -> Box | None:
    """구역 안 0~1 좌표를 원본 px 로 바꾼다. 구역 밖으로 나가지 않게 자른다.

    뒤집힌 좌표는 정렬하고, 짧은 목록은 전체 범위로 채운다. 넓이가 0 이면 None(요청 무시)."""
    x0, y0, x1, y1 = region_box
    w, h = x1 - x0, y1 - y0
    vals = list(req.bbox)[:4]
    vals += [0.0, 0.0, 1.0, 1.0][len(vals):]
    clamp = lambda v: min(max(float(v), 0.0), 1.0)  # noqa: E731
    ax, bx = sorted((clamp(vals[0]), clamp(vals[2])))
    ay, by = sorted((clamp(vals[1]), clamp(vals[3])))
    box = (x0 + round(ax * w), y0 + round(ay * h), x0 + round(bx * w), y0 + round(by * h))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def crop_scale(box: Box, requested: float, max_px: int) -> float:
    """요청 배율(1~4)을 쓰되, 결과 긴 변이 max_px 를 넘으면 배율을 낮춘다(1 아래로도)."""
    scale = min(max(requested, 1.0), 4.0)
    long_edge = max(box[2] - box[0], box[3] - box[1])
    return min(scale, max_px / long_edge) if long_edge else scale


async def recheck_rows(table: TableResult, page: PageImage, workdir: Path, *, caps: Caps, ctx,
                       usage_sink, raw_sink) -> TableResult:
    """행 단위 플래그가 걸린 띠를 재확인 모델로 다시 전사하고, 원래 결과와 다시 합친다."""
    s = get_settings()
    bands = sorted({f.band_index for f in table.flags if f.col is None})
    if not bands or caps.recheck_calls_left <= 0:
        return table
    bands = bands[:caps.recheck_calls_left]
    caps.recheck_calls_left -= len(bands)
    caps.bands_left += len(bands)            # 재전사는 띠 상한이 아니라 재확인 상한으로 센다
    redo = await transcribe_table(table.region, page, workdir, caps=caps,
                                  ctx=lambda l: ctx(f"{l}.re"), usage_sink=usage_sink,
                                  raw_sink=raw_sink, spec_text=s.layout_recheck_model,
                                  band_indexes=bands)
    # 다시 읽은 띠는 새 원본 행(잘림 표시 포함)으로, 나머지 띠는 기존 행으로 띠별 목록을 만들어 합친다
    per_band: list[list[BandRow]] = []
    for bi in range(len(table.band_boxes)):
        redone = bi in bands
        source = redo.rows if redone else table.rows
        per_band.append([BandRow(row_label=r.label, cells=list(r.cells),
                                 cut_top=r.cut_top if redone else False,
                                 cut_bottom=r.cut_bottom if redone else False)
                         for r in source if r.band_index == bi])
    merged, flags = merge_bands(per_band, table.header,
                                window=merge_window(table.band_boxes,
                                                    overlap_rows=s.layout_band_overlap_rows,
                                                    min_row_px=s.layout_min_row_px))
    fill_down(merged)
    info = table.region.table
    flags += check_table(merged, table.header, info.expected_rows if info else None,
                         info.row_label_column if info else None)
    for f in flags:
        f.cell_id = f"{table.region.region_id}{f.cell_id}"
    return TableResult(table.region, table.header, merged, flags, table.band_boxes,
                       rerouted=table.rerouted, unreadable=table.unreadable)


def _cell_line(table: TableResult, cid: str, f) -> str:
    head = table.header[f.col] if f.col < len(table.header) else str(f.col)
    cells = table.rows[f.row_index].cells if f.row_index < len(table.rows) else []
    cur = cells[f.col] if f.col < len(cells) else ""
    return f"- {cid}: {f.row_index + 1}번째 행 '{head}' 칸, 지금 읽은 값 '{cur}'"


async def resolve_cells(table: TableResult, page: PageImage, workdir: Path, *, caps: Caps, ctx,
                        usage_sink, raw_sink) -> None:
    """칸 플래그를 모델 답으로 채운다. 못 읽거나 상한이면 table.unreadable 에 사유를 남긴다."""
    s = get_settings()
    pending = {f.cell_id: f for f in table.flags if f.col is not None}
    if not pending:
        return
    region = table.region
    images = [crop_zoom(page.path, region.box, 1.0, workdir / f"{region.region_id}-rc.png")]
    for turn in range(s.layout_recheck_max_turns):
        if not pending or caps.recheck_calls_left <= 0:
            break
        caps.recheck_calls_left -= 1
        cells = "\n".join(_cell_line(table, cid, f) for cid, f in pending.items())
        got: RecheckTurn = await measured_generate(
            parse_model_spec(s.layout_recheck_model),
            prompts.render("recheck", cells=cells), list(images), RecheckTurn,
            usage_sink=usage_sink, usage_context=ctx(f"{region.region_id}.rc{turn}"),
            raw_sink=raw_sink, what="재확인",
            mock_build=lambda: RecheckTurn(crops=[], answers=[]))
        for a in got.answers:
            f = pending.pop(a.cell_id, None)
            if f is None:
                continue
            if a.value is not None:
                cells_row = table.rows[f.row_index].cells
                while len(cells_row) <= f.col:
                    cells_row.append("")
                cells_row[f.col] = a.value
            else:
                table.unreadable[(f.row_index, f.col)] = a.unreadable_reason or "판독 불가"
        # 한 턴의 확대 요청은 상한까지만 받는다. 넓이 0 인 요청은 무시한다
        for k, req in enumerate(got.crops[:s.layout_recheck_max_crops_per_turn]):
            box = crop_box(region.box, req)
            if box is None:
                continue
            images.append(crop_zoom(page.path, box, crop_scale(box, req.scale, s.layout_crop_max_px),
                                    workdir / f"{region.region_id}-rc{turn}-{k}.png"))
    for f in pending.values():
        table.unreadable[(f.row_index, f.col)] = _CAP
