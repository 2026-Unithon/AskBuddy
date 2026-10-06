"""② 구역 지도. 판단 모델이 구역을 나누고, 코드가 좌표를 정리하고 빠진 글자 영역을 잡는다."""
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from app.config import get_settings
from app.ingest.layout import prompts
from app.ingest.layout.schemas import Box, PageImage, PlacedRegion, Region, RegionMap
from app.ingest.providers import measured_generate, parse_model_spec
from app.ingest.providers.budget import BudgetExceeded

logger = logging.getLogger(__name__)

_SCAN_MAX_PX = 800


def _pad4(bbox: list[float]) -> list[float]:
    """짧은 좌표 목록은 빠진 자리를 전체 범위(0,0,1,1)로 채운다."""
    vals = list(bbox)[:4]
    return vals + [0.0, 0.0, 1.0, 1.0][len(vals):]


def _to_box(bbox: list[float], w: int, h: int) -> Box:
    x0, y0, x1, y1 = _pad4(bbox)
    clamp = lambda v: min(max(float(v), 0.0), 1.0)  # noqa: E731
    x0, x1 = sorted((clamp(x0), clamp(x1)))
    y0, y1 = sorted((clamp(y0), clamp(y1)))
    return (round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))


def place_regions(page: PageImage, region_map: RegionMap, *, min_px: int = 8) -> list[PlacedRegion]:
    out: list[PlacedRegion] = []
    for r in sorted(region_map.regions, key=lambda r: r.reading_order):
        box = _to_box(r.bbox, page.width, page.height)
        if box[2] - box[0] < min_px or box[3] - box[1] < min_px:
            continue
        out.append(PlacedRegion(page.number, f"p{page.number}-r{len(out) + 1}", r.kind, box,
                                len(out) + 1, r.table if r.kind == "TABLE" else None, "MODEL"))
    return out


def cover_margin_px(width: int, height: int, ratio: float) -> int:
    """구역 상자 여유 = max(4px, 쪽 짧은 변 × 비율). 모델 상자가 표 테두리 안쪽에 그어져도 테두리를 덮는다."""
    return max(4, round(min(width, height) * ratio))


def uncovered_boxes(image_path: Path, covered: list[Box], *, ink_threshold: int,
                    min_area_px: int, cover_margin_ratio: float, max_overlap: float,
                    grid_px: int = 8) -> list[Box]:
    """어느 구역에도 안 든 글자 덩어리. 격자 칸 단위로 이웃을 묶는다(numpy 없이).

    - 구역 상자는 여유만큼 넓혀 지운다(테두리 띠가 덩어리로 남지 않게).
    - 후보 상자의 `max_overlap` 넘게가 구역(여유 포함) 안이면 버린다 — 구역 밖 테두리 고리가
      쪽 전체 크기 덩어리가 되어 표를 글로 다시 읽는 일을 막는다.
    - 먼지 방어: 상자 넓이가 아니라 글자 화소 수가 `min_area_px`(원본 px 기준) 미만이면 버린다.
    """
    img = Image.open(image_path).convert("L")
    full_w, full_h = img.size
    m = cover_margin_px(full_w, full_h, cover_margin_ratio)
    padded = [(max(0, b[0] - m), max(0, b[1] - m), min(full_w, b[2] + m), min(full_h, b[3] + m))
              for b in covered]
    # 구역 안은 화소 단위로 흰색 처리한다 — 격자 칸이 구역 가장자리에 걸쳐도 안쪽 글자가 새지 않는다
    draw = ImageDraw.Draw(img)
    mask = Image.new("L", (full_w, full_h), 0)      # 구역(여유 포함) 합집합. 255 가 덮인 곳
    mdraw = ImageDraw.Draw(mask)
    for b in padded:
        if b[2] > b[0] and b[3] > b[1]:
            draw.rectangle((b[0], b[1], b[2] - 1, b[3] - 1), fill=255)
            mdraw.rectangle((b[0], b[1], b[2] - 1, b[3] - 1), fill=255)
    # 큰 쪽은 긴 변 800px 이하로 줄인다. 평균이 아니라 최솟값 필터라 가는 선이 지워지지 않는다
    f = max(1, -(-max(full_w, full_h) // _SCAN_MAX_PX))
    min_ink = min_area_px
    if f > 1:
        img = img.filter(ImageFilter.MinFilter(f if f % 2 else f + 1))
        img = img.resize((max(1, full_w // f), max(1, full_h // f)), Image.NEAREST)
        mask = mask.resize(img.size, Image.NEAREST)
        min_ink = max(1, min_area_px // (f * f))   # 줄인 화소 하나 = 원본 f×f
    w, h = img.size
    cols, rows = (w + grid_px - 1) // grid_px, (h + grid_px - 1) // grid_px
    px = img.load()
    ink: dict[tuple[int, int], int] = {}            # 격자 칸 → 글자 화소 수
    for gy in range(rows):
        for gx in range(cols):
            x0, y0 = gx * grid_px, gy * grid_px
            n = sum(1 for y in range(y0, min(y0 + grid_px, h))
                    for x in range(x0, min(x0 + grid_px, w)) if px[x, y] <= ink_threshold)
            if n:
                ink[(gx, gy)] = n
    out: list[Box] = []
    seen: set = set()
    for start in ink:
        if start in seen:
            continue
        stack, cells = [start], []
        seen.add(start)
        while stack:
            gx, gy = stack.pop()
            cells.append((gx, gy))
            for nx, ny in ((gx + 1, gy), (gx - 1, gy), (gx, gy + 1), (gx, gy - 1)):
                if (nx, ny) in ink and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        if sum(ink[c] for c in cells) < min_ink:
            continue                                # 먼지
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        box = (min(xs) * grid_px, min(ys) * grid_px,
               min((max(xs) + 1) * grid_px, w), min((max(ys) + 1) * grid_px, h))
        area = (box[2] - box[0]) * (box[3] - box[1])
        inside = mask.crop(box).histogram()[255]
        if area and inside / area > max_overlap:
            continue                                # 구역 테두리 고리 — 이미 구역이 읽는다
        out.append((box[0] * f, box[1] * f, min(box[2] * f, full_w), min(box[3] * f, full_h)))
    return sorted(out, key=lambda b: (b[1], b[0]))


def _thumbnail(page: PageImage, workdir: Path, max_px: int) -> Path:
    img = Image.open(page.path)
    img.thumbnail((max_px, max_px))
    out = workdir / f"page-{page.number}-map.png"
    img.save(out)
    return out


def _whole_page(page: PageImage) -> RegionMap:
    return RegionMap(regions=[Region(kind="PROSE", bbox=[0, 0, 1, 1], reading_order=1, table=None)])


async def map_page(page: PageImage, workdir: Path, *, ctx, usage_sink,
                   raw_sink) -> tuple[list[PlacedRegion], list[str]]:
    s = get_settings()
    unresolved: list[str] = []
    try:
        region_map = await measured_generate(
            parse_model_spec(s.layout_region_model), prompts.render("region"),
            [_thumbnail(page, workdir, s.layout_region_image_max_px)], RegionMap,
            usage_sink=usage_sink, usage_context=ctx(f"p{page.number}.map"), raw_sink=raw_sink,
            what="구역 지도", mock_build=lambda: _whole_page(page))
        placed = place_regions(page, region_map)
    except BudgetExceeded:
        raise  # 상한 도달은 삼키지 않는다 — 호출자가 이후 구역 호출을 멈춘다
    except Exception as exc:
        logger.warning("구역 지도 실패 page=%s: %s — 쪽 전체를 한 구역으로 둔다", page.number, exc)
        unresolved.append(f"[구역 지도 실패] {page.number}쪽: {type(exc).__name__} — 쪽 전체를 한 구역으로 읽었다")
        placed = []
    if not placed:
        return [PlacedRegion(page.number, f"p{page.number}-r1", "UNCLASSIFIED",
                             (0, 0, page.width, page.height), 1, None, "FALLBACK")], unresolved
    for box in uncovered_boxes(page.path, [r.box for r in placed],
                               ink_threshold=s.layout_ink_threshold,
                               min_area_px=s.layout_uncovered_min_area_px,
                               cover_margin_ratio=s.layout_cover_margin_ratio,
                               max_overlap=s.layout_coverage_max_overlap):
        placed.append(PlacedRegion(page.number, f"p{page.number}-r{len(placed) + 1}",
                                   "UNCLASSIFIED", box, len(placed) + 1, None, "COVERAGE"))
    return placed, unresolved
