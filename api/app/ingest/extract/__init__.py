"""준혁 — 추출기 선택. INGEST_MODE 로 목/실제를 가른다.

mock : LLM 미호출. M1 경계 뚫기용이자 기본값
real : Gemini Flash 호출. M1 통과 후에만 켠다
"""
import logging

from app.config import get_settings
from app.ingest.schemas import ExtractionResult

logger = logging.getLogger(__name__)


async def extract_cards(
    *, source_id: int, source_type: str, text: str,
    category_names: list[str], glossary: list[dict[str, str]],
) -> ExtractionResult:
    mode = get_settings().ingest_mode
    if mode == "real":
        from app.ingest.extract import gemini as impl
    else:
        from app.ingest.extract import mock as impl

    logger.info("extract mode=%s source=%s type=%s", mode, source_id, source_type)
    return await impl.extract(
        source_id=source_id, source_type=source_type, text=text,
        category_names=category_names, glossary=glossary,
    )
