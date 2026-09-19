"""점주 원문 답변을 기존 지식과 비교해 안전한 반영 계획으로 만든다."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

import asyncpg
from pydantic import BaseModel, Field

from app.config import get_settings
from app.reg.embeddings import recorded_embeddings, vector_literal
from app.contracts.usage import UsageContext
from app.usage import DbUsageSink
from app.usage.gemini import UsageStartError, checked_context, recorded_generate

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "owner_answer_relation.ko.txt"

RelationType = Literal["IDENTICAL", "SUPPLEMENT", "CONFLICT", "NEW"]


class KnowledgeRelationPayload(BaseModel):
    relation_type: RelationType
    target_card_id: int | None = None
    category_name: str
    reason: str = Field(max_length=500)


@dataclass(frozen=True)
class KnowledgePlan:
    relation_type: RelationType
    target_card_id: int | None
    target_version_id: int | None
    category_id: int
    category_name: str
    proposed_title: str
    proposed_content: str
    reason: str
    auto_publish: bool


_NORMALIZE = re.compile(r"[^0-9a-z가-힣]+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_NEGATION = re.compile(r"(?:안|않|말아|금지|불가|없|하지\s*마|지\s*마)")


def _normalized_content(text: str) -> str:
    return _NORMALIZE.sub("", text.lower())


def _obvious_conflict(existing: str, answer: str) -> bool:
    old_numbers = set(_NUMBER.findall(existing))
    new_numbers = set(_NUMBER.findall(answer))
    if old_numbers and new_numbers and old_numbers != new_numbers:
        return True
    return bool(_NEGATION.search(existing)) != bool(_NEGATION.search(answer))


def _strictly_identical(existing: str, answer: str) -> bool:
    return _normalized_content(existing) == _normalized_content(answer)


async def find_owner_answer_candidates(
    db: asyncpg.Connection,
    store_id: int,
    question: str,
    answer: str,
    top_k: int = 5,
    *, usage_context=None, usage_sink=None,
) -> list[dict]:
    """직원 질문과 점주 답변을 함께 임베딩해 현재 승인 카드만 찾는다."""
    context = checked_context(usage_context, usage_sink, "RELATION", store_id=store_id)
    embed_context = context.model_copy(update={"stage": "EMBED",
        "logical_call_id": f"owner-plan:{context.operation_id}:embed"})
    query_vec = (await recorded_embeddings([f"{question}\n{answer}"],
        context=embed_context, sink=usage_sink))[0]
    rows = await db.fetch(
        """
        select m.card_id as id, m.title, m.content, m.score,
               c.published_version_id as version_id,
               c.category_id, c.assignment_type,
               coalesce(tc.category_name, '') as category_name
        from match_cards($1, $2::vector, $3) m
        join knowledge_cards c
          on c.store_id = $1 and c.card_id = m.card_id
        left join task_categories tc
          on tc.store_id = c.store_id and tc.category_id = c.category_id
        where c.review_status = 'APPROVED'
          and c.is_verified = true
          and c.published_version_id is not null
        order by m.score desc
        """,
        store_id,
        vector_literal(query_vec),
        top_k,
    )
    return [dict(row) for row in rows]


def _safe_fallback_plan(
    question: str,
    answer: str,
    categories: list[dict],
    candidates: list[dict],
    reason: str,
) -> KnowledgePlan:
    other = next(category for category in categories if category["is_system"])
    if candidates:
        target = candidates[0]
        target_category_id = target.get("category_id") or other["category_id"]
        target_category_name = target.get("category_name") or other["category_name"]
        return KnowledgePlan(
            relation_type="SUPPLEMENT",
            target_card_id=int(target["id"]),
            target_version_id=int(target["version_id"]),
            category_id=int(target_category_id),
            category_name=target_category_name,
            proposed_title=target["title"],
            proposed_content=f"{target['content'].rstrip()}\n\n추가 안내: {answer}",
            reason=reason,
            auto_publish=False,
        )
    return KnowledgePlan(
        relation_type="NEW",
        target_card_id=None,
        target_version_id=None,
        category_id=int(other["category_id"]),
        category_name=other["category_name"],
        proposed_title=question[:200],
        proposed_content=answer,
        reason=reason,
        auto_publish=False,
    )


def validate_knowledge_plan(
    payload: KnowledgeRelationPayload,
    question: str,
    answer: str,
    categories: list[dict],
    candidates: list[dict],
) -> KnowledgePlan:
    category_by_name = {category["category_name"]: category for category in categories}
    other = next(category for category in categories if category["is_system"])
    candidate_by_id = {int(card["id"]): card for card in candidates}

    relation = payload.relation_type
    target = candidate_by_id.get(payload.target_card_id) if payload.target_card_id else None
    if relation != "NEW" and target is None:
        return _safe_fallback_plan(
            question, answer, categories, candidates, "모델이 유효하지 않은 대상 카드를 선택함"
        )

    if relation == "NEW":
        category = category_by_name.get(payload.category_name, other)
        return KnowledgePlan(
            relation_type="NEW",
            target_card_id=None,
            target_version_id=None,
            category_id=int(category["category_id"]),
            category_name=category["category_name"],
            proposed_title=question[:200],
            proposed_content=answer,
            reason=payload.reason,
            auto_publish=True,
        )

    assert target is not None
    target_category_id = target.get("category_id") or other["category_id"]
    target_category_name = target.get("category_name") or other["category_name"]
    if relation == "IDENTICAL" and not _strictly_identical(target["content"], answer):
        relation = "SUPPLEMENT"
    if relation == "SUPPLEMENT" and _obvious_conflict(target["content"], answer):
        relation = "CONFLICT"

    if relation == "IDENTICAL":
        proposed_title = target["title"]
        proposed_content = target["content"]
        auto_publish = False
    elif relation == "SUPPLEMENT":
        proposed_title = target["title"]
        proposed_content = f"{target['content'].rstrip()}\n\n추가 안내: {answer}"
        auto_publish = False
    else:
        proposed_title = target["title"]
        proposed_content = answer
        auto_publish = False

    return KnowledgePlan(
        relation_type=relation,
        target_card_id=int(target["id"]),
        target_version_id=int(target["version_id"]),
        category_id=int(target_category_id),
        category_name=target_category_name,
        proposed_title=proposed_title,
        proposed_content=proposed_content,
        reason=payload.reason,
        auto_publish=auto_publish,
    )


async def build_knowledge_plan(
    db: asyncpg.Connection,
    store_id: int,
    question: str,
    answer: str,
    *, usage_context=None, usage_sink=None,
) -> KnowledgePlan:
    if usage_context is None and usage_sink is None:
        # 이 단계에는 owner_answer_id가 아직 없다. 서버 분석 operation으로 두 호출을 묶는다.
        from app.deps import get_pool
        operation = str(uuid4())
        usage_context = UsageContext(store_id=str(store_id), cost_phase="OPERATING",
            cost_purpose="PRODUCT", stage="RELATION", operation_id=operation,
            logical_call_id=f"owner-plan:{operation}:relation")
        usage_sink = DbUsageSink(get_pool())
    context = checked_context(usage_context, usage_sink, "RELATION", store_id=store_id)
    if context.operation_id is None:
        raise ValueError("점주 답변 분석에는 서버 operation_id가 필요하다")
    rows = await db.fetch(
        """
        select category_id, category_name, is_system
        from task_categories
        where store_id = $1 and deleted_at is null and is_enabled = true
        order by is_system, sort_order, category_id
        """,
        store_id,
    )
    categories = [dict(row) for row in rows]
    if not categories or not any(category["is_system"] for category in categories):
        raise RuntimeError("system Other category is missing")

    try:
        candidates = await find_owner_answer_candidates(db, store_id, question, answer,
            usage_context=context, usage_sink=usage_sink)
    except Exception as exc:
        logger.warning("owner-answer candidate search failed type=%s", type(exc).__name__)
        return _safe_fallback_plan(
            question, answer, categories, [], "유사 카드 검색 실패로 수동 검토 필요"
        )

    # 모델 판단과 무관하게 본문이 엄격히 같은 카드는 새 카드로 만들지 않는다.
    # 카테고리와 수동 배정 여부도 기존 카드 값을 그대로 유지한다.
    identical = next(
        (card for card in candidates if _strictly_identical(card["content"], answer)),
        None,
    )
    if identical is not None:
        other = next(category for category in categories if category["is_system"])
        category_id = identical.get("category_id") or other["category_id"]
        category_name = identical.get("category_name") or other["category_name"]
        return KnowledgePlan(
            relation_type="IDENTICAL",
            target_card_id=int(identical["id"]),
            target_version_id=int(identical["version_id"]),
            category_id=int(category_id),
            category_name=category_name,
            proposed_title=identical["title"],
            proposed_content=identical["content"],
            reason="점주 답변이 기존 공개 카드 본문과 엄격히 동일함",
            auto_publish=False,
        )

    settings = get_settings()
    if settings.answer_mode != "grounded_llm" or not settings.gemini_api_key:
        fallback_candidates = [
            card
            for card in candidates
            if float(card["score"]) >= settings.retrieval_threshold
        ]
        return _safe_fallback_plan(
            question,
            answer,
            categories,
            fallback_candidates,
            "지식 관계 분석을 사용할 수 없어 수동 검토 필요",
        )

    evidence = [
        {
            "card_id": int(card["id"]),
            "title": card["title"],
            "content": card["content"],
            "category": card["category_name"],
        }
        for card in candidates
    ]
    prompt = PROMPT_PATH.read_text(encoding="utf-8").format(
        question=question,
        answer=answer,
        categories_json=json.dumps(
            [category["category_name"] for category in categories], ensure_ascii=False
        ),
        cards_json=json.dumps(evidence, ensure_ascii=False),
    )
    try:
        payload = await recorded_generate(prompt, KnowledgeRelationPayload, settings,
                                          context=context, sink=usage_sink)
        return validate_knowledge_plan(payload, question, answer, categories, candidates)
    except UsageStartError:
        raise
    except Exception as exc:
        logger.warning("owner-answer relation analysis failed type=%s", type(exc).__name__)
        fallback_candidates = [
            card
            for card in candidates
            if float(card["score"]) >= settings.retrieval_threshold
        ]
        return _safe_fallback_plan(
            question,
            answer,
            categories,
            fallback_candidates,
            "지식 관계 분석 실패로 수동 검토 필요",
        )
