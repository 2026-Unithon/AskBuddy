"""추출과 분리된 기존 카드 의미 분류기."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from app.categories.schemas import ClassificationBatch
from app.config import get_settings

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "classify_cards.ko.txt"


async def classify_cards(cards: list[dict], category_names: list[str]) -> dict[int, str]:
    settings = get_settings()
    other = "기타"
    allowed = set(category_names)

    if settings.ingest_mode == "mock":
        # 목 모드에서는 새 의미를 지어내지 않는다. 삭제된 분류만 기타로 보낸다.
        return {
            int(card["card_id"]): (
                card["category_name"] if card.get("category_name") in allowed else other
            )
            for card in cards
        }

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY가 없어 재분류를 실행할 수 없습니다.")

    from google import genai
    from google.genai import types

    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        template.replace("{categories}", "\n".join(f"- {name}" for name in category_names))
        .replace(
            "{cards}",
            "\n\n".join(
                f"card_id: {card['card_id']}\n제목: {card['title']}\n본문: {card['content']}"
                for card in cards
            ),
        )
    )
    started = time.perf_counter()
    client = genai.Client(api_key=settings.gemini_api_key)
    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ClassificationBatch,
            temperature=0.0,
        ),
    )
    raw = response.text or ""
    usage = response.usage_metadata
    logger.info(
        "gemini reclass model=%s elapsed=%.1fs cards=%d tokens_in=%s tokens_out=%s out=%dchars",
        settings.gemini_model,
        time.perf_counter() - started,
        len(cards),
        getattr(usage, "prompt_token_count", None),
        getattr(usage, "candidates_token_count", None),
        len(raw),
    )
    parsed = ClassificationBatch.model_validate_json(raw)
    choices = {item.card_id: item.category_name for item in parsed.items}
    return {
        int(card["card_id"]): (
            choices.get(int(card["card_id"]))
            if choices.get(int(card["card_id"])) in allowed
            else other
        )
        for card in cards
    }
