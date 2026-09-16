"""추출과 분리된 기존 카드 의미 분류기."""
from __future__ import annotations

import logging
from pathlib import Path

from app.categories.schemas import ClassificationBatch
from app.config import get_settings
from app.usage.gemini import checked_context, recorded_generate

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "classify_cards.ko.txt"


async def classify_cards(cards: list[dict], category_names: list[str], *,
                         usage_context=None, usage_sink=None) -> dict[int, str]:
    settings = get_settings()
    other = "기타"
    allowed = set(category_names)
    if not cards:
        return {}

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

    context = checked_context(usage_context, usage_sink, "CLASSIFY")

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
    parsed = await recorded_generate(prompt, ClassificationBatch, settings,
                                     context=context, sink=usage_sink)
    choices = {item.card_id: item.category_name for item in parsed.items}
    return {
        int(card["card_id"]): (
            choices.get(int(card["card_id"]))
            if choices.get(int(card["card_id"])) in allowed
            else other
        )
        for card in cards
    }
