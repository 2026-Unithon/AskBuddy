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
    usage_sink=None, usage_context=None,
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
            usage_sink=usage_sink, usage_context=usage_context,
        )

    from app.ingest.extract import mock as impl
    return await impl.extract_facts(
        source_id=source_id, source_type=source_type, text=text,
        glossary=glossary, media=media or [],
    )


async def assemble_cards(
    *, source_id: int, facts: list[dict],
    category_names: list[str], glossary: list[dict],
    usage_sink=None, usage_context=None,
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
        **({"usage_sink": usage_sink, "usage_context": usage_context} if mode == "real" else {}),
    )
