"""③ 구역별 전사. 표는 띠로 잘라 칸 원문만 받고, 병합·검사는 코드가 한다."""
import asyncio
import logging
import math
import re
from pathlib import Path
from typing import Literal

from PIL import Image

from app.config import get_settings
from app.ingest.layout import prompts
from app.ingest.layout.schemas import (BandRow, BandRows, Box, Caps, CellFlag, PageImage,
                                       PlacedRegion, ProseLines, ProseResult, TableResult,
                                       TranscribedRow)
from app.ingest.providers import measured_generate, parse_model_spec

logger = logging.getLogger(__name__)
_FILL = "↑"


def plan_bands(box: Box, expected_rows: int | None, *, rows_per_band: int, overlap_rows: int,
               default_row_px: int, min_row_px: int, max_row_px: int) -> list[Box]:
    """예상 행 수로 행 높이를 잡되 [min_row_px, max_row_px] 로 묶는다(모델 행 수를 그대로 믿지 않는다)."""
    x0, y0, x1, y1 = box
    height = y1 - y0
    rows = expected_rows or max(1, height // default_row_px)
    if height / rows < min_row_px:
        rows = max(1, math.floor(height / min_row_px))     # 행이 너무 낮다 — 행 수를 줄인다
    elif height / rows > max_row_px:
        rows = max(1, math.ceil(height / max_row_px))      # 행이 너무 높다 — 행 수를 늘린다
    row_h = height / rows
    band_h = row_h * rows_per_band
    step = row_h * max(1, rows_per_band - overlap_rows)
    if band_h >= height:
        return [box]
    bands, top = [], 0.0
    while True:
        bottom = min(top + band_h, height)
        bands.append((x0, y0 + round(top), x1, y0 + round(bottom)))
        if bottom >= height:
            return bands
        top += step


def merge_window(band_boxes: list[Box], *, overlap_rows: int, min_row_px: int) -> int:
    """겹침 제거 창 = max(겹침 행 + 1, 실제 띠 겹침 px ÷ 최소 행 높이). 띠 기하에서 끌어낸다."""
    overlap_px = max((max(0, a[3] - b[1]) for a, b in zip(band_boxes, band_boxes[1:])), default=0)
    return max(overlap_rows + 1, math.ceil(overlap_px / min_row_px))


def crop_zoom(image_path: Path, box: Box, scale: float, out_path: Path) -> Path:
    img = Image.open(image_path).crop(box)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                     Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def _same(a: list[str], b: list[str]) -> bool:
    return [c.strip() for c in a] == [c.strip() for c in b]


def _align(prev: list, cand: list, match, window: int) -> int:
    """이전 띠 끝 k개와 새 띠 앞 k개가 위치별로 맞는 가장 큰 k(1~window). 없으면 0."""
    for k in range(min(window, len(prev), len(cand)), 0, -1):
        if all(match(prev[len(prev) - k + j], cand[j]) for j in range(k)):
            return k
    return 0


def _rows_match(a: TranscribedRow, b: BandRow) -> bool:
    la, lb = (a.label or "").strip(), (b.row_label or "").strip()
    if la and lb:
        return la == lb
    return _same(a.cells, b.cells)


def merge_bands(bands: list[list[BandRow]], header: list[str], *,
                window: int = 2) -> tuple[list[TranscribedRow], list[CellFlag]]:
    """cell_id 는 region_id 없는 접미사(`:행:열`)다. 호출부가 region_id 를 앞에 붙인다.

    겹침 제거는 앞 띠 끝 k행과 새 띠 앞 k행이 위치별로 맞는 가장 큰 k(≤window)만 한다.
    그 밖의 행은 라벨·내용이 반복돼도 별개 행이다."""
    rows: list[TranscribedRow] = []
    flags: list[CellFlag] = []
    last = len(bands) - 1
    prev_dropped_bottom = False
    for bi, band in enumerate(bands):
        kept: list[tuple[BandRow, bool]] = []      # (행, 잘린 반쪽 강제 유지 여부)
        dropped_bottom = False
        for ri, r in enumerate(band):
            force_keep = False
            # 잘림 표시는 띠 가장자리 행에만 뜻이 있다. 띠 가운데 행의 잘림 표시는 무시하고 둔다
            if r.cut_top and bi > 0 and ri == 0:
                if prev_dropped_bottom:
                    force_keep = True           # 잘린 두 반쪽 — 사이에 행이 빠졌을 수 있다
                else:
                    continue                    # 이웃 띠에 온전히 있다
            if r.cut_bottom and bi < last and ri == len(band) - 1:
                dropped_bottom = True
                continue
            kept.append((r, force_keep))
        prev_idx = [i for i, r in enumerate(rows) if r.band_index == bi - 1]
        k = 0
        if kept and not kept[0][1]:
            k = _align([rows[i] for i in prev_idx], [r for r, _ in kept], _rows_match, window)
        for j in range(k):
            prev_row, new_row = rows[prev_idx[len(prev_idx) - k + j]], kept[j][0]
            if (prev_row.label or "").strip() and (new_row.row_label or "").strip():
                idx = prev_idx[len(prev_idx) - k + j]
                for col, (x, y) in enumerate(zip(prev_row.cells, new_row.cells)):
                    if x.strip() != y.strip():
                        flags.append(CellFlag(f":{idx}:{col}", idx, col, "OVERLAP_MISMATCH", bi))
        for r, force_keep in kept[k:]:
            rows.append(TranscribedRow((r.row_label or "").strip() or None, list(r.cells), bi,
                                       r.cut_top, r.cut_bottom))
            if force_keep:
                n = len(rows) - 1
                flags.append(CellFlag(f":{n}:row", n, None, "ROW_MISSING", bi))
        prev_dropped_bottom = dropped_bottom
    return rows, flags


def fill_down(rows: list[TranscribedRow]) -> None:
    for i, row in enumerate(rows):
        for col, cell in enumerate(row.cells):
            if cell.strip() == _FILL and i > 0 and col < len(rows[i - 1].cells):
                row.cells[col] = rows[i - 1].cells[col]


def check_table(rows: list[TranscribedRow], header: list[str], expected_rows: int | None,
                row_label_column: int | None) -> list[CellFlag]:
    flags: list[CellFlag] = []
    for i, r in enumerate(rows):
        if len(r.cells) != len(header):
            flags.append(CellFlag(f":{i}:row", i, None, "COLUMN_COUNT", r.band_index))
    numbers: dict[int, int] = {}
    for i, r in enumerate(rows):
        if r.label and re.fullmatch(r"\d+", r.label.strip()):
            n = int(r.label)
            if n in numbers:
                # 같은 번호가 두 행에 있다 — 겹침 오독이나 행 밀림. 뒤 행의 띠를 다시 보게 한다
                flags.append(CellFlag(f":{i}:row", i, None, "ROW_COUNT", r.band_index))
                continue
            numbers[n] = i
    if numbers:
        lo, hi = min(numbers), max(numbers)
        missing = [n for n in range(lo, hi + 1) if n not in numbers]
        # 연속 빠진 번호는 한 덩이로 묶고, 덩이 바로 뒤 행의 띠를 가리킨다
        gaps: list[list[int]] = []
        for n in missing:
            if gaps and gaps[-1][-1] == n - 1:
                gaps[-1].append(n)
            else:
                gaps.append([n])
        limit = expected_rows or 50
        if len(missing) > limit:
            gaps = gaps[:1]                     # 라벨 오독 방어 — 하나만 낸다
        for gap in gaps:
            i = numbers[min(k for k in numbers if k > gap[-1])]
            flags.append(CellFlag(f":{i}:row", i, None, "ROW_MISSING", rows[i].band_index))
    if expected_rows and len(rows) < expected_rows:
        if rows:
            i = len(rows) - 1
            flags.append(CellFlag(f":{i}:row", i, None, "ROW_COUNT", rows[i].band_index))
        else:
            flags.append(CellFlag(":0:row", 0, None, "ROW_COUNT", 0))   # 행이 하나도 없다
    return flags


def needs_reroute(rows: list[TranscribedRow], header: list[str]) -> bool:
    if not rows:
        return True
    bad = sum(1 for r in rows if len(r.cells) != len(header))
    return bad * 2 > len(rows)


async def _band_call(spec_text, region, page, workdir, bi, box, header, caps, ctx, usage_sink, raw_sink):
    s = get_settings()
    if caps.bands_left <= 0:
        raise RuntimeError("띠 호출 상한 도달")
    caps.bands_left -= 1
    img = crop_zoom(page.path, box, s.layout_zoom, workdir / f"{region.region_id}-b{bi}.png")
    result = await measured_generate(
        parse_model_spec(spec_text), prompts.render("table_band", header=" | ".join(header)),
        [img], BandRows, usage_sink=usage_sink, usage_context=ctx(f"{region.region_id}.b{bi}"),
        raw_sink=raw_sink, what="띠 전사",
        mock_build=lambda: BandRows(rows=[BandRow(row_label=str(k + 1),
                                                  cells=[f"{h}{k + 1}" for h in header],
                                                  cut_top=False, cut_bottom=False)
                                          for k in range(2)]))
    return result.rows


async def transcribe_table(region: PlacedRegion, page: PageImage, workdir: Path, *, caps: Caps,
                           ctx, usage_sink, raw_sink, spec_text: str | None = None,
                           band_indexes: list[int] | None = None) -> TableResult:
    """band_indexes 를 주면 그 띠만 다시 부른다(재전사). 결과 TableResult 는 그 띠의 행만 담는다."""
    s = get_settings()
    info = region.table
    header = list(info.header_columns) if info else []
    boxes = plan_bands(region.box, info.expected_rows if info else None,
                       rows_per_band=s.layout_band_rows, overlap_rows=s.layout_band_overlap_rows,
                       default_row_px=s.layout_default_row_px, min_row_px=s.layout_min_row_px,
                       max_row_px=s.layout_max_row_px)
    targets = band_indexes if band_indexes is not None else list(range(len(boxes)))
    if len(targets) > caps.bands_left:
        # 미리 센다 — 일부 띠만 부르고 상한에 걸려 쓴 돈만 잃는 구역을 만들지 않는다
        raise RuntimeError(f"띠 호출 상한 부족: 필요 {len(targets)}, 남음 {caps.bands_left}")
    gate = asyncio.Semaphore(s.layout_concurrency)

    async def one(bi):
        async with gate:
            return await _band_call(spec_text or s.layout_transcribe_model, region, page, workdir,
                                    bi, boxes[bi], header, caps, ctx, usage_sink, raw_sink)
    # 하나가 실패해도 형제 호출의 기록/종료를 기다린 뒤 구역 실패로 넘긴다.
    results = await asyncio.gather(*(one(bi) for bi in targets), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    if band_indexes is not None:
        # 재전사: 대상 띠의 원본 행만 돌려준다. 병합·검사는 호출부(재확인)가 기존 행과 함께 한다
        raw = [TranscribedRow((br.row_label or "").strip() or None, list(br.cells), bi,
                              br.cut_top, br.cut_bottom)
               for bi, band_rows in zip(targets, results) for br in band_rows]
        return TableResult(region, header, raw, [], boxes, rerouted=False)
    by_band: list[list[BandRow]] = [[] for _ in boxes]
    for bi, band_rows in zip(targets, results):
        by_band[bi] = band_rows
    rows, flags = merge_bands([by_band[bi] for bi in range(len(boxes))], header,
                              window=merge_window(boxes, overlap_rows=s.layout_band_overlap_rows,
                                                  min_row_px=s.layout_min_row_px))
    fill_down(rows)
    flags += check_table(rows, header, info.expected_rows if info else None,
                         info.row_label_column if info else None)
    for f in flags:
        f.cell_id = f"{region.region_id}{f.cell_id}"
    return TableResult(region, header, rows, flags, boxes, rerouted=needs_reroute(rows, header))


async def transcribe_text(region: PlacedRegion, page: PageImage, workdir: Path, *,
                          kind_prompt: Literal["prose", "photo"],
                          caps: Caps, ctx, usage_sink, raw_sink) -> ProseResult:
    s = get_settings()
    boxes = plan_bands(region.box, None, rows_per_band=s.layout_band_rows * 3,
                       overlap_rows=s.layout_band_overlap_rows, default_row_px=s.layout_default_row_px,
                       min_row_px=s.layout_min_row_px, max_row_px=s.layout_max_row_px)
    lines: list[str] = []
    prev: list[str] = []
    for bi, box in enumerate(boxes):
        if caps.bands_left <= 0:
            raise RuntimeError("띠 호출 상한 도달")
        caps.bands_left -= 1
        img = crop_zoom(page.path, box, s.layout_zoom, workdir / f"{region.region_id}-t{bi}.png")
        got = await measured_generate(
            parse_model_spec(s.layout_transcribe_model), prompts.render(kind_prompt), [img], ProseLines,
            usage_sink=usage_sink, usage_context=ctx(f"{region.region_id}.t{bi}"), raw_sink=raw_sink,
            what="글 전사", mock_build=lambda: ProseLines(lines=[f"{region.region_id} 합성 줄"]))
        new = [ln.strip() for ln in got.lines if ln.strip()]
        k = _align(prev, new, lambda x, y: x == y, s.layout_band_overlap_rows + 1)
        lines.extend(new[k:])                   # 앞 띠 끝줄과 위치별로 맞는 앞쪽 줄만 버린다
        prev = new
    return ProseResult(region, lines)
