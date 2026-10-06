"""SCAN 구역 기반 다단계 추출 (설계 W_SCAN_LAYOUT_EXTRACTION_DESIGN).

구역 하나 = 구간(segment) 하나. 구역을 끝내는 즉시 checkpoint 로 원장에 적는다.
금액 상한에 닿으면 남은 구역·쪽은 부르지 않고 실패로 남긴다(작업은 PARTIAL).
판독 불가·전개 미반영은 구역 실패가 아니라 미해결로만 남긴다(계획 편차 7).
"""
import logging
from pathlib import Path

from app.config import get_settings
from app.ingest.layout import expand, recheck, transcribe
from app.ingest.layout.pages import blank_page, page_images
from app.ingest.layout.regions import map_page
from app.ingest.layout.schemas import Caps
from app.ingest.providers import budget

logger = logging.getLogger(__name__)

# 평가 하네스가 읽는 단계별 손실 기록. 프로세스 안에서만 산다(제품 응답에 싣지 않는다)
STATS: dict[int, dict] = {}


def _new_stats() -> dict:
    return dict(pages=0, regions=0, coverage_regions=0, fallback_regions=0, rows=0, expected_rows=0,
                rechecked_cells=0, unreadable_cells=0, unexpanded_tokens=0, failed_regions=0, rerouted=0,
                row_flags_left=0)


def _map_segment(page_number: int) -> str:
    """구역 지도를 얻지 못한 쪽의 실패 구간 이름. 구역 ID 를 모르므로 쪽 단위로 남긴다."""
    return f"p{page_number}-map"


def _row_flag_notes(table) -> list[str]:
    """재전사 뒤에도 남은(또는 상한으로 다시 못 본) 행 단위 문제를 미해결로 드러낸다. 조용히 사라지지 않게."""
    region = table.region
    notes: list[str] = []
    for f in table.flags:
        if f.col is not None:
            continue
        if f.reason == "COLUMN_COUNT":
            row = table.rows[f.row_index] if f.row_index < len(table.rows) else None
            label = (row.label if row and row.label else f"행{f.row_index + 1}")
            notes.append(f"[열 수 불일치] {region.page}쪽 {region.region_id} 띠{f.band_index} 행 {label}")
        else:
            notes.append(f"[행 누락 의심] {region.page}쪽 {region.region_id} {f.reason} 띠{f.band_index}")
    return notes


async def _process_region(region, page, workdir, ctx, caps, glossary, source_id, usage_sink,
                          raw_sink, stats):
    """구역 하나 → (사실, 미해결, 서버 검사용 글)."""
    if region.kind == "TABLE":
        table = await transcribe.transcribe_table(region, page, workdir, caps=caps, ctx=ctx,
                                                  usage_sink=usage_sink, raw_sink=raw_sink)
        if not table.rerouted:
            # 행 단위 문제(띠 재전사)를 먼저 고치고, 남은 칸 단위 문제만 칸 질의로 푼다
            table = await recheck.recheck_rows(table, page, workdir, caps=caps, ctx=ctx,
                                               usage_sink=usage_sink, raw_sink=raw_sink)
            before = sum(1 for f in table.flags if f.col is not None)
            await recheck.resolve_cells(table, page, workdir, caps=caps, ctx=ctx,
                                        usage_sink=usage_sink, raw_sink=raw_sink)
            stats["rechecked_cells"] += before
            stats["unreadable_cells"] += len(table.unreadable)
            stats["rows"] += len(table.rows)
            stats["expected_rows"] += (region.table.expected_rows or 0) if region.table else 0
            row_notes = _row_flag_notes(table)
            stats["row_flags_left"] += len(row_notes)
            facts, unresolved = await expand.expand_table(table, ctx=ctx, usage_sink=usage_sink,
                                                          raw_sink=raw_sink)
            unresolved = row_notes + list(unresolved)
            stats["unexpanded_tokens"] += sum(1 for u in unresolved if u.startswith("[전개 미반영]"))
            text = "\n".join(expand.row_text(table, i) for i in range(len(table.rows)))
            return facts, unresolved, text
        # 표로 읽히지 않는 구역은 글로 다시 읽는다
        stats["rerouted"] += 1
    kind_prompt = "photo" if region.kind == "PHOTO" else "prose"
    prose = await transcribe.transcribe_text(region, page, workdir, kind_prompt=kind_prompt, caps=caps,
                                             ctx=ctx, usage_sink=usage_sink, raw_sink=raw_sink)
    facts, unresolved = await expand.expand_text(prose, source_id=source_id, glossary=glossary, ctx=ctx,
                                                 usage_sink=usage_sink, raw_sink=raw_sink)
    return facts, unresolved, "\n".join(prose.lines)


async def run_layout_extraction(*, source_id: int, path: Path | None, workdir: Path, glossary,
                                usage_sink, usage_base, raw_sink, checkpoint,
                                only_segments: set[str] | None):
    """쪽 → 구역 지도 → 구역마다 전사·재확인·전개 → 원장(checkpoint).

    `only_segments` 를 주면 PARTIAL 재시도다. 구역 지도는 모든 쪽에서 다시 얻어(재사용 전제)
    구간 수를 그대로 세고, 목록에 든 구역만 처리한다. `p{n}-map` 이 들어 있으면 그 쪽의
    구역 전부가 대상이다. 대상이 전부 다시 실패해도 예외를 올리지 않는다.
    """
    from app.ingest import occurrences
    from app.ingest.pipeline import ExtractionOutcome, _ctx_for

    s = get_settings()
    stats = STATS[source_id] = _new_stats()
    workdir.mkdir(parents=True, exist_ok=True)
    pages = ([blank_page(workdir)] if path is None else
             page_images(path, workdir, render_dpi=s.layout_render_dpi, max_pages=s.ingest_scan_max_pages))
    stats["pages"] = len(pages)
    caps = Caps(bands_left=s.layout_max_bands_per_source,
                recheck_calls_left=s.layout_recheck_max_calls_per_source)

    def ctx(label: str):
        return _ctx_for(usage_base, source_id, "EXTRACT", segment_id=label)

    def wanted(rid: str, page_number: int) -> bool:
        return (only_segments is None or rid in only_segments
                or _map_segment(page_number) in only_segments)

    merged, unresolved, failed, total = [], [], [], 0
    stop = False
    for page in pages:
        if stop:
            # 상한 뒤 쪽은 구역 지도도 부르지 않는다. 잃은 쪽으로 세어 PARTIAL 로 드러낸다
            total += 1
            failed.append(_map_segment(page.number))
            continue
        try:
            placed, notes = await map_page(page, workdir, ctx=ctx, usage_sink=usage_sink,
                                           raw_sink=raw_sink)
        except budget.BudgetExceeded as exc:
            logger.warning("금액 상한 — %d쪽 구역 지도부터 부르지 않는다: %s", page.number, exc)
            total += 1
            failed.append(_map_segment(page.number))
            stop = True
            continue
        except Exception as exc:
            # map_page 는 모델 실패를 스스로 흡수한다. 여기 오는 것은 이미지 처리 등 코드 오류다
            logger.warning("구역 지도 실패 source=%s %d쪽: %s", source_id, page.number, exc)
            total += 1
            failed.append(_map_segment(page.number))
            continue
        unresolved += notes
        for region in placed:
            total += 1
            stats["regions"] += 1
            stats["coverage_regions"] += region.added_by == "COVERAGE"
            stats["fallback_regions"] += region.added_by == "FALLBACK"
            rid = region.region_id
            if not wanted(rid, page.number):
                continue
            if stop:
                failed.append(rid)
                continue
            try:
                facts, notes, text = await _process_region(region, page, workdir, ctx, caps, glossary,
                                                           source_id, usage_sink, raw_sink, stats)
                for a in facts:
                    a.segment_id = rid
                notes = list(notes) + occurrences.validate_assertions(
                    facts, source_type="SCAN", text=text, media=[],
                    locator_hints=False,
                    clear_ungrounded=bool(getattr(s, "extract_clear_ungrounded_values", False)))
                if checkpoint is not None:
                    # 끝낸 즉시 적는다. 적지 못하면 그 구역은 잃은 것으로 센다
                    await checkpoint(facts, rid)
                merged += facts
                unresolved += notes
            except budget.BudgetExceeded as exc:
                logger.warning("금액 상한 — %s 부터 남은 구역을 부르지 않는다: %s", rid, exc)
                failed.append(rid)
                stop = True
            except Exception as exc:
                logger.warning("구역 실패 source=%s %s: %s", source_id, rid, exc)
                failed.append(rid)
    stats["failed_regions"] = len(failed)
    if total and len(failed) == total and only_segments is None:
        raise RuntimeError(f"모든 구역({total}개) 추출이 실패했다")
    if failed:
        logger.warning("구역 %d/%d 실패 source=%s — 나머지로 진행한다", len(failed), total, source_id)
    return ExtractionOutcome(merged, unresolved, total, len(failed), failed, None)
