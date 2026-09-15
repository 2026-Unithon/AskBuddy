"""준혁 — 추출기 선택. INGEST_MODE 로 목/실제를 가른다.

mock : LLM 미호출. M1 경계 뚫기용이자 기본값
real : Gemini Flash 호출. M1 통과 후에만 켠다
"""
import logging
from pathlib import Path

from app.config import get_settings
from app.ingest.schemas import ExtractionResult, FactExtractionResult

logger = logging.getLogger(__name__)


async def extract_cards(
    *, source_id: int, source_type: str, text: str,
    category_names: list[str], glossary: list[dict[str, str]],
    media: list[Path] | None = None, usage_sink=None, usage_context=None,
) -> ExtractionResult:
    mode = get_settings().ingest_mode
    if mode == "real":
        from app.ingest.extract import gemini as impl
    else:
        from app.ingest.extract import mock as impl

    logger.info("extract mode=%s source=%s type=%s media=%d",
                mode, source_id, source_type, len(media or []))
    kwargs = {}
    if mode == "real":
        # mock 구현은 계측 인자를 받지 않는다. mock 실행은 원가가 아니다 (D10)
        kwargs = {"usage_sink": usage_sink, "usage_context": usage_context}
    return await impl.extract(
        source_id=source_id, source_type=source_type, text=text,
        category_names=category_names, glossary=glossary, media=media or [],
        **kwargs,
    )


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

    # mock 에는 사실 추출기가 없다. 카드 목을 사실로 펴서 계약만 맞춘다.
    # mock 실행을 모델 성능으로 집계하지 않는다 (D10)
    from app.ingest.extract import mock as impl
    from app.ingest.schemas import ExtractedAssertion

    carded = await impl.extract(
        source_id=source_id, source_type=source_type, text=text,
        category_names=[], glossary=glossary, media=media or [],
    )
    assertions = [
        ExtractedAssertion(
            local_ref=f"m{i}", original_assertion=f"{f.object_name} {f.attribute} {f.value}",
            subject=f.object_name, attribute=f.attribute, value=f.value,
            category_name=card.category_name, evidence=card.evidence,
            confidence=f.confidence,
        )
        for i, (card, f) in enumerate(
            ((c, f) for c in carded.cards for f in c.facts), start=1)
    ]
    return FactExtractionResult(assertions=assertions,
                                unresolved=list(carded.unresolved))


async def assemble_cards(
    *, source_id: int, facts: list[dict],
    category_names: list[str], glossary: list[dict],
    usage_sink=None, usage_context=None,
):
    """reduce — 뽑아둔 사실을 카드로 조립한다. mock 모드에서는 쓰지 않는다."""
    if get_settings().ingest_mode != "real":
        raise RuntimeError("assemble 은 INGEST_MODE=real 에서만 쓴다")
    from app.ingest.extract import gemini as impl

    logger.info("assemble source=%s facts=%d", source_id, len(facts))
    return await impl.assemble(
        source_id=source_id, facts=facts,
        category_names=category_names, glossary=glossary,
        usage_sink=usage_sink, usage_context=usage_context,
    )
