"""승인 카드에만 근거한 직원 답변 생성과 결정적 서버 검증."""
from __future__ import annotations

import json
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.contracts.usage import UsageContext
from app.usage.recorder import UsageSink
from app.learn.answer_usage import (
    AnswerUsageStartError, answer_attempt, checked_context, observe_answer,
)

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "grounded_answer.ko.txt"


class GroundedAnswerPayload(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
    card_ids: list[int] = Field(min_length=1, max_length=3)


@dataclass(frozen=True)
class AnswerComposition:
    content: str
    candidates: list[dict]
    source: Literal["CARD_ORIGINAL", "GROUNDED_LLM"]
    grounding_status: Literal["VERIFIED", "FALLBACK"]
    fallback_reason: str | None = None
    # 미호출과 응답 관측 누락을 구분한다. 원문 폴백도 모델 호출 후일 수 있다.
    usage: dict[str, int | None] | None = None
    model_call_status: Literal["NOT_CALLED", "OBSERVED", "UNKNOWN"] = "UNKNOWN"


_WORD = re.compile(r"[0-9A-Za-z가-힣]+")
_NUMBER = re.compile(
    r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?:\s*(?:원|개|명|번|분|초|시간|시|일|주|개월|년|층|도|%|퍼센트|ml|mL|L|g|kg))?"
)
_TAILS = (
    "이라던데요", "라던데요", "인가요", "이에요", "예요", "에요", "해주세요",
    "하세요", "됩니다", "입니다", "습니다", "해요", "어요", "아요", "나요", "가요",
    "까요", "에서", "으로", "한테", "에게", "까지", "부터", "이랑", "보다", "처럼",
    "에게는", "에서는", "으로는", "은", "는", "이", "가", "을", "를", "에", "의",
    "도", "만", "로", "과", "와", "랑",
)
_NON_FACT_TERMS = {
    "안내", "따라", "관련", "경우", "내용", "확인", "참고", "해주세요", "하세요",
    "됩니다", "입니다", "그리고", "또는", "다만", "먼저", "이후", "해당", "직원",
    "질문", "답변", "사장님", "매장", "업무", "카드", "기준",
}


def _stem(word: str) -> str:
    lowered = word.lower()
    for tail in _TAILS:
        if lowered.endswith(tail) and len(lowered) - len(tail) >= 2:
            return lowered[: -len(tail)]
    return lowered


def _fact_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for word in _WORD.findall(text):
        stem = _stem(word)
        if len(stem) < 2 or stem in _NON_FACT_TERMS or stem.isdigit():
            continue
        terms.add(stem)
    return terms


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[\s,]", "", value).lower() for value in _NUMBER.findall(text)}


def validate_grounded_payload(
    payload: GroundedAnswerPayload,
    candidates: list[dict],
) -> tuple[bool, str | None, list[dict]]:
    """모델이 허용된 카드 밖의 사실 표현을 추가했으면 거부한다."""
    by_id = {int(card["id"]): card for card in candidates}
    requested_ids = list(dict.fromkeys(payload.card_ids))
    if not requested_ids or any(card_id not in by_id for card_id in requested_ids):
        return False, "unknown_citation", []

    selected = [by_id[card_id] for card_id in requested_ids]
    source_text = "\n".join(
        f"{card.get('title', '')}\n{card.get('content', '')}" for card in selected
    )
    answer = payload.answer.strip()
    if not answer:
        return False, "empty_answer", []

    if not _numbers(answer).issubset(_numbers(source_text)):
        return False, "unsupported_number", []

    unsupported_terms = _fact_terms(answer) - _fact_terms(source_text)
    if unsupported_terms:
        logger.info("grounded answer rejected: unsupported_terms")
        return False, "unsupported_terms", []

    return True, None, selected


def _usage_of(response: object) -> dict[str, int | None] | None:
    """모델 응답의 토큰 사용량. SDK 버전에 따라 없을 수 있으므로 실패해도 조용히 넘긴다."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None
    prompt = getattr(meta, "prompt_token_count", None)
    completion = getattr(meta, "candidates_token_count", None)
    if prompt is None and completion is None:
        return None
    return {
        "prompt_tokens": prompt if type(prompt) is int and prompt >= 0 else None,
        "completion_tokens": completion if type(completion) is int and completion >= 0 else None,
    }


def _fallback(
    candidates: list[dict],
    reason: str | None = None,
    *,
    usage: dict[str, int | None] | None = None,
    model_call_status: Literal["NOT_CALLED", "OBSERVED", "UNKNOWN"] = "UNKNOWN",
) -> AnswerComposition:
    top = candidates[0]
    return AnswerComposition(
        content=top["content"],
        candidates=[top],
        source="CARD_ORIGINAL",
        grounding_status="FALLBACK",
        fallback_reason=reason,
        usage=usage,
        model_call_status=model_call_status,
    )


async def compose_grounded_answer(
    question: str,
    candidates: list[dict],
    *,
    usage_context: UsageContext | None = None,
    usage_sink: UsageSink | None = None,
) -> AnswerComposition:
    """구조화 생성 → 서버 검증. 어느 실패든 승인 카드 원문으로 폴백한다."""
    if not candidates:
        raise ValueError("at least one approved card candidate is required")
    usage_context = checked_context(usage_context, usage_sink)

    settings = get_settings()
    if settings.answer_mode == "extractive":
        return _fallback(candidates, "extractive_mode", model_call_status="NOT_CALLED")
    if not settings.gemini_api_key:
        return _fallback(candidates, "missing_api_key", model_call_status="NOT_CALLED")

    usage = None
    model_call_status = "NOT_CALLED"
    try:
        from google import genai
        from google.genai import types

        evidence = [
            {
                "card_id": int(card["id"]),
                "title": card.get("title", ""),
                "content": card["content"],
            }
            for card in candidates[:3]
        ]
        prompt = PROMPT_PATH.read_text(encoding="utf-8").format(
            question=question,
            cards_json=json.dumps(evidence, ensure_ascii=False),
        )
        # SDK 내부 재시도를 숨기지 않는다. 1 receipt는 실제 시도 1회다.
        client = genai.Client(api_key=settings.gemini_api_key,
                              http_options=types.HttpOptions(
                                  retry_options=types.HttpRetryOptions(attempts=1)))
        async with answer_attempt(usage_sink, usage_context, model=settings.gemini_model,
                                  prompt_hash="sha256:" + hashlib.sha256(prompt.encode()).hexdigest()) as rec:
            if rec is not None:
                rec.measure_input(input_bytes=len(prompt.encode("utf-8")))
            model_call_status = "UNKNOWN"
            response = await client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GroundedAnswerPayload,
                    temperature=0.0,
                ),
            )
            model_call_status = "OBSERVED"
            usage = _usage_of(response)
            observe_answer(rec, response)
            payload = GroundedAnswerPayload.model_validate_json(response.text or "")
        valid, reason, selected = validate_grounded_payload(payload, candidates[:3])
        if not valid:
            return _fallback(candidates, reason, usage=usage, model_call_status=model_call_status)
        return AnswerComposition(
            content=payload.answer.strip(),
            candidates=selected,
            source="GROUNDED_LLM",
            grounding_status="VERIFIED",
            usage=usage,
            model_call_status=model_call_status,
        )
    except AnswerUsageStartError:
        raise
    except Exception as exc:
        logger.warning("grounded answer generation failed: %s", type(exc).__name__)
        return _fallback(candidates, "generation_failed", usage=usage, model_call_status=model_call_status)
