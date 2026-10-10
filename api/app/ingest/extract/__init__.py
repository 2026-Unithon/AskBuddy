"""준혁 — 추출기 선택. INGEST_MODE 로 목/실제를 가른다.

mock : LLM 미호출. M1 경계 뚫기용이자 기본값
real : Gemini Flash 호출. M1 통과 후에만 켠다
"""
import logging
from pathlib import Path

from app.config import get_settings
from app.ingest.schemas import FactExtractionResult

logger = logging.getLogger(__name__)


async def extract_facts(
    *, source_id: int, source_type: str, text: str,
    glossary: list[dict[str, str]], media: list[Path] | None = None,
    usage_sink=None, usage_context=None, raw_sink=None,
) -> FactExtractionResult:
    """map — 자료에서 사실만 뽑는다 (W1). 카드를 만들지 않는다."""
    mode = get_settings().ingest_mode
    logger.info("extract_facts mode=%s source=%s type=%s media=%d",
                mode, source_id, source_type, len(media or []))
    if mode == "real":
        from app.ingest.extract import gemini as impl
        return await impl.extract_facts(
            source_id=source_id, source_type=source_type, text=text,
            glossary=glossary, media=media or [],
            usage_sink=usage_sink, usage_context=usage_context, raw_sink=raw_sink,
        )

    # mock 도 원래 응답 기록을 남긴다 (W1-1). 원가 원장에는 쓰지 않는다 — 과금이 없다
    from app.ingest.extract import mock as impl
    return await impl.extract_facts(
        source_id=source_id, source_type=source_type, text=text,
        glossary=glossary, media=media or [],
        usage_context=usage_context, raw_sink=raw_sink,
    )


async def assemble_cards(
    *, source_id: int, facts: list[dict],
    category_names: list[str], glossary: list[dict],
    usage_sink=None, usage_context=None, raw_sink=None,
):
    """reduce — real/mock 모두 사실 추출 뒤 카드로 조립한다."""
    mode = get_settings().ingest_mode
    if mode == "real":
        from app.ingest.extract import gemini as impl
    else:
        from app.ingest.extract import mock as impl

    logger.info("assemble source=%s facts=%d", source_id, len(facts))
    return await impl.assemble(
        source_id=source_id, facts=facts,
        category_names=category_names, glossary=glossary,
        usage_context=usage_context, raw_sink=raw_sink,
        **({"usage_sink": usage_sink} if mode == "real" else {}),
    )


async def assemble_card_plan(
    *, source_id: int, entities: list[dict], category_names: list[str],
    glossary: list[dict], usage_sink=None, usage_context=None, raw_sink=None,
):
    """사실 조립(W3a) — 이름표 배치만 받는다. real/mock 은 ingest_mode 로 고른다."""
    mode = get_settings().ingest_mode
    if mode == "real":
        from app.ingest.extract import gemini as impl
    else:
        from app.ingest.extract import mock as impl

    logger.info("assemble_card_plan source=%s entities=%d", source_id, len(entities))
    return await impl.assemble_plan(
        source_id=source_id, entities=entities,
        category_names=category_names, glossary=glossary,
        usage_context=usage_context, raw_sink=raw_sink,
        **({"usage_sink": usage_sink} if mode == "real" else {}),
    )


async def parse_owner_facts(
    *, payload: dict, usage_sink=None, usage_context=None, raw_sink=None,
) -> FactExtractionResult:
    """W3b — 점주가 카드에 쓴 문장을 사실 후보로 나눈다. 저장하지 않는다. real/mock 은 ingest_mode 로 고른다."""
    mode = get_settings().ingest_mode
    logger.info("parse_owner_facts mode=%s", mode)
    if mode == "real":
        from app.ingest.extract import gemini as impl
        return await impl.parse_owner_facts(
            payload=payload, usage_sink=usage_sink, usage_context=usage_context,
            raw_sink=raw_sink)
    # mock 도 원래 응답 기록은 남긴다. 원가 원장에는 쓰지 않는다 — 과금이 없다
    from app.ingest.extract import mock as impl
    return await impl.parse_owner_facts(
        payload=payload, usage_context=usage_context, raw_sink=raw_sink)
