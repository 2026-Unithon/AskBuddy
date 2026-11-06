"""사장 지시 문장 다듬기. 사장이 미리보기로 확인한 뒤 보내므로 실패해도 원문으로 보낼 수 있다."""
from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings
from app.contracts.usage import UsageContext
from app.errors import ApiError
from app.today_tasks.schemas import MAX_TEXT
from app.usage.gemini import checked_context, recorded_generate

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "polish_today_task.ko.txt"


class PolishResult(BaseModel):
    body: str


def unavailable() -> ApiError:
    return ApiError(503, "POLISH_UNAVAILABLE", "문장을 다듬지 못했어요. 적은 그대로 보낼 수 있어요.")


async def polish_text(text: str, *, store_id: int, call_id: str, usage_sink=None) -> str:
    settings = get_settings()
    if settings.ingest_mode == "mock":
        # 목 모드는 문장을 지어내지 않는다. 원문 그대로 돌려준다
        return text
    if not settings.gemini_api_key:
        raise unavailable()
    context = checked_context(
        UsageContext(store_id=str(store_id), cost_phase="OPERATING", cost_purpose="PRODUCT",
                     stage="POLISH", logical_call_id=f"today-task-polish:{call_id}"),
        usage_sink, "POLISH", store_id=store_id,
    )
    prompt = PROMPT_PATH.read_text(encoding="utf-8").replace("{text}", text)
    try:
        parsed = await recorded_generate(prompt, PolishResult, settings, context=context, sink=usage_sink)
    except Exception as exc:
        logger.warning("today task polish failed type=%s", type(exc).__name__)
        raise unavailable() from exc
    body = "\n".join(" ".join(line.split()) for line in parsed.body.strip().splitlines() if line.strip())
    if not body or len(body) > MAX_TEXT:
        raise unavailable()
    return body
