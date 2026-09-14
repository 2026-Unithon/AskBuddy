"""준혁 — 추출기 선택. INGEST_MODE 로 목/실제를 가른다.

mock : LLM 미호출. M1 경계 뚫기용이자 기본값
real : Gemini Flash 호출. M1 통과 후에만 켠다
"""
import logging
from pathlib import Path

from app.config import get_settings
from app.ingest.schemas import ExtractionResult

logger = logging.getLogger(__name__)


async def extract_cards(
    *, source_id: int, source_type: str, text: str,
    category_names: list[str], glossary: list[dict[str, str]],
    media: list[Path] | None = None,
) -> ExtractionResult:
    mode = get_settings().ingest_mode
    if mode == "real":
        from app.ingest.extract import gemini as impl
    else:
        from app.ingest.extract import mock as impl

    logger.info("extract mode=%s source=%s type=%s media=%d",
                mode, source_id, source_type, len(media or []))
    return await impl.extract(
        source_id=source_id, source_type=source_type, text=text,
        category_names=category_names, glossary=glossary, media=media or [],
    )


async def assemble_cards(
    *, source_id: int, facts: list[dict],
    category_names: list[str], glossary: list[dict],
):
    """reduce — 뽑아둔 사실을 카드로 조립한다. mock 모드에서는 쓰지 않는다."""
    if get_settings().ingest_mode != "real":
        raise RuntimeError("assemble 은 INGEST_MODE=real 에서만 쓴다")
    from app.ingest.extract import gemini as impl

    logger.info("assemble source=%s facts=%d", source_id, len(facts))
    return await impl.assemble(
        source_id=source_id, facts=facts,
        category_names=category_names, glossary=glossary,
    )
