"""점주 답변 반영 worker (W, Phase A Task 6).

R 이 남긴 `OWNER_ANSWER_SUBMITTED` 사건을 claim 해서 점주 답변을 지식에 반영하고
그 결과(LINKED / REVIEW / PUBLISHED / FAILED)를 R 에 돌려준다.

관계 분석(R knowledge_loop)을 부르지 않는다 — 점주 답변도 사실 수집 경로를 탄다.
  1. 답변 하나에 파일 없는 자료(OWNER_TEXT) 하나를 보장한다(owner_answer_sources).
  2. 그 자료에서 사실을 뽑아 원장 → 사실 조립 → 사실 카드까지 만든다(업로드와 같은 길).
  3. 그 자료가 이어진 카드로 결과를 정한다(`decide_outcome`).
     - 사실 0개 / 이어진 카드 없음 / 공개 카드에 새 초안 / 검수 필요 새 카드 → REVIEW
     - 새 카드만 있고 모두 검수 사유 없음 → 그 카드들을 `publish_cards` 로 공개(PUBLISHED).
       R 완료 보고(`finish_owner_event`)는 **발행 트랜잭션 hook 안에서만** 부른다 —
       finish 가 실패하면 발행까지 통째로 롤백돼 R 이 모르는 공개판이 남지 않는다.
     - 이미 공개된 같은 사실에만 이어짐 → LINKED(현재 서빙 가능할 때만, 아니면 REVIEW)
  4. 실패: 별도 트랜잭션에서 FAILED 를 보고한다. 재시도 여부는 ERROR_TABLE 이 정한다.

claim 뒤에는 연결을 오래 잡지 않는다. 추출·조립·색인 준비 같은 긴 단계 사이에
heartbeat 를 부르고, lease 를 잃었으면 아무것도 보고하지 않고 멈춘다(다른 worker 몫).
매장 격리는 코드 책임이다 (D1). 모든 조회는 store_id 로 제한한다.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Sequence

import asyncpg

from app.config import get_settings
from app.contracts.errors import ERROR_TABLE, ErrorDetail
from app.contracts.publication import ApplyOwnerAnswerResult
from app.contracts.usage import UsageContext
from app.errors import ApiError
from app.ingest import owner_text
from app.ingest.fact_cards import REVIEW_NEW_FACTS
from app.ingest.owner_text import AnswerCard
from app.learn.knowledge_apply import resolve_owner_answer_category
from app.learn.owner_handoff import (
    CONSUMER,
    claim_owner_event,
    finish_owner_event,
    heartbeat_owner_event,
)
from app.publish.approval import CardChange, publish_cards
from app.publish.bootstrap import READY, EMPTY, index_status
from app.publish.content import current_manifest
from app.usage.gemini import UsageStartError

logger = logging.getLogger(__name__)

# 한 주기에 한 매장에서 처리할 사건 상한. 한 매장이 주기를 독점하지 않게 한다
MAX_EVENTS_PER_STORE = 50


class _Failed(Exception):
    """처리를 멈추고 FAILED 로 보고할 사유. code 는 ERROR_TABLE 값이다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _LeaseLost(Exception):
    """heartbeat 실패. 다른 worker 가 가져갔으므로 보고하지 않는다."""


# ---------------------------------------------------------------------------
# DB 보조 (모두 store_id 필수)
# ---------------------------------------------------------------------------

async def _load_context(conn, *, store_id: int, owner_answer_id: int) -> dict:
    """답변 원문·질문, 매장 점주 멤버십, 기존 제안을 한 번에 읽는다."""
    source = await conn.fetchrow(
        """
        select oa.answer_id, oa.answer_text, pq.question_id, pq.question_text
        from r_owner_answer_revisions r
        join owner_answers oa
          on oa.answer_id = r.owner_answer_id and oa.question_id = r.question_id
        join pending_questions pq
          on pq.store_id = r.store_id and pq.question_id = r.question_id
        where r.store_id = $1 and r.owner_answer_id = $2
        """,
        store_id, owner_answer_id)
    owner = await conn.fetchrow(
        """
        select m.member_id, m.user_id from store_members m
        where m.store_id = $1 and m.member_role = 'OWNER'
        order by m.member_id limit 1
        """,
        store_id)
    proposal = await conn.fetchrow(
        """
        select proposal_id, status, relation_type, result_card_id, result_version_id
        from knowledge_change_proposals
        where store_id = $1 and answer_id = $2
        """,
        store_id, owner_answer_id)
    return dict(source=dict(source) if source else None,
                owner=dict(owner) if owner else None,
                proposal=dict(proposal) if proposal else None)


async def _insert_proposal(conn, *, store_id: int, answer_id: int, relation: str,
                           target_card_id: int | None, target_version_id: int | None,
                           category_id: int, title: str, content: str, reason: str,
                           status: str, result_card_id: int | None = None,
                           result_version_id: int | None = None) -> dict:
    """answer_id 당 제안 1행을 멱등으로 남기고, 실제로 남아 있는 행을 돌려준다."""
    await conn.execute(
        """
        insert into knowledge_change_proposals (
          store_id, answer_id, relation_type, target_card_id, target_version_id,
          category_id, proposed_title, proposed_content, reason, status,
          result_card_id, result_version_id, resolved_at
        ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::varchar, $11, $12,
                  case when $10::varchar = 'LINKED' then now() else null end)
        on conflict (answer_id) do nothing
        """,
        store_id, answer_id, relation, target_card_id, target_version_id, category_id,
        title[:200], content, reason, status, result_card_id, result_version_id)
    row = await conn.fetchrow(
        """
        select proposal_id, status, relation_type, result_card_id, result_version_id
        from knowledge_change_proposals
        where store_id = $1 and answer_id = $2
        for update
        """,
        store_id, answer_id)
    if row is None:
        # 다른 매장의 같은 answer_id 는 있을 수 없다. 있으면 격리 위반이다
        raise _Failed("INVALID_REFERENCE", "점주 답변 제안을 남기지 못했습니다.")
    return dict(row)


async def _set_proposal(conn, *, store_id: int, proposal_id: int, status: str,
                        result_card_id: int | None = None,
                        result_version_id: int | None = None) -> None:
    # $3 은 컬럼 대입(varchar)과 IN 비교(text) 양쪽에 쓰인다. 캐스트가 없으면 Postgres 가
    # "inconsistent types deduced for parameter $3" 로 거절한다(실제 DB 검증에서 발견)
    await conn.execute(
        """
        update knowledge_change_proposals
        set status = $3::varchar,
            result_card_id = coalesce($4, result_card_id),
            result_version_id = coalesce($5, result_version_id),
            error = null,
            resolved_at = case when $3::varchar in ('PUBLISHED', 'LINKED')
                               then now() else resolved_at end
        where store_id = $1 and proposal_id = $2
        """,
        store_id, proposal_id, status, result_card_id, result_version_id)


async def _lock_publication(conn, *, store_id: int):
    """공개 상태 행을 잠근다. R 의 잠금 순서(공개판 → 카드 → 대기 질문)를 따른다."""
    return await conn.fetchrow(
        """
        select current_snapshot_id, knowledge_revision from knowledge_publications
        where store_id = $1
        for update
        """,
        store_id)


async def _linked_target(conn, *, store_id: int, card_id: int | None) -> tuple[int, int] | None:
    """카드가 지금 서빙 가능한 공개 카드면 (card_version_id, knowledge_revision).

    R 의 `publication_evidence` 와 같은 조건을 먼저 확인한다 — 현재 공개판 manifest
    에 있고, APPROVED·is_verified 이며, 공개 포인터가 그 manifest 버전이어야 한다.
    manifest 는 EXCLUDED 만 거르므로 검수로 되돌린 카드도 남아 있다. 조건이 깨졌는데
    LINKED/PUBLISHED 로 보고하면 finish 가 STALE_KNOWLEDGE 로 되풀이 실패한다.
    반드시 트랜잭션 안에서 부른다(공개판 잠금이 커밋까지 유지돼야 한다).
    """
    publication = await _lock_publication(conn, store_id=store_id)
    if card_id is None:
        return None
    if publication is None or publication["current_snapshot_id"] is None:
        return None
    manifest = await current_manifest(conn, store_id=store_id)
    version_id = manifest.get(card_id)
    if version_id is None:
        return None
    card = await conn.fetchrow(
        """
        select review_status, is_verified, published_version_id
        from knowledge_cards
        where store_id = $1 and card_id = $2
        for share
        """,
        store_id, card_id)
    if (card is None or card["review_status"] != "APPROVED" or not card["is_verified"]
            or card["published_version_id"] != version_id):
        return None
    return version_id, int(publication["knowledge_revision"])


async def _flag_target_review(conn, *, store_id: int, card_id: int | None,
                              relation: str) -> None:
    """검수 대상 카드에 점주 답변 사유를 남긴다.

    안전 신호(NO_PROVENANCE·FACT_CONFLICT_OPEN·FALLBACK:* 등)는 덮지 않는다. 사유가 없거나
    단순히 새 사실이 붙었다는 표시(NEW_FACTS)일 때만 OWNER_ANSWER_<relation> 으로 바꾼다.
    """
    if card_id is None:
        return
    await conn.execute(
        """
        update knowledge_cards set needs_review_reason = $3
        where store_id = $1 and card_id = $2 and review_status <> 'EXCLUDED'
          and (needs_review_reason is null or needs_review_reason = $4)
        """,
        store_id, card_id, f"OWNER_ANSWER_{relation}", REVIEW_NEW_FACTS)


async def _card_text(conn, *, store_id: int, card: AnswerCard) -> tuple[str, str, int] | None:
    """제안에 적을 카드 초안 판의 제목·본문과 카드 카테고리."""
    row = await conn.fetchrow(
        """
        select v.title, v.content, k.category_id
        from knowledge_cards k
        join card_versions v on v.store_id = k.store_id and v.card_id = k.card_id
        where k.store_id = $1 and k.card_id = $2 and v.version_id = $3
        """,
        store_id, card.card_id, card.draft_version_id)
    if row is None:
        return None
    return row["title"] or "", row["content"] or "", int(row["category_id"])


async def _stores_with_pending(pool) -> list[int]:
    """아직 W 가 소비하지 않은 점주 답변 사건이 있는 매장."""
    async with pool.acquire() as conn:
        # store-isolation-ok: worker 가 처리할 매장 목록만 읽는다
        rows = await conn.fetch(
            """
            select distinct e.store_id from outbox_events e
            where e.event_type = 'OWNER_ANSWER_SUBMITTED'
              and not exists (
                select 1 from outbox_consumptions c
                where c.store_id = e.store_id and c.event_id = e.event_id
                  and c.consumer = $1)
            order by e.store_id
            """,
            CONSUMER)
    return [int(row["store_id"]) for row in rows]


# ---------------------------------------------------------------------------
# 결과 보고
# ---------------------------------------------------------------------------

def _usage_context(store_id: int, event_id: int, stage: str, suffix: str) -> UsageContext:
    return UsageContext(
        store_id=str(store_id), cost_phase="OPERATING", cost_purpose="PRODUCT",
        stage=stage, operation_id=f"owner-event:{event_id}",
        logical_call_id=f"owner-event:{event_id}:{suffix}")


def _error_code(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, _Failed):
        return exc.code, exc.message
    if isinstance(exc, ApiError) and exc.code in ERROR_TABLE:
        return exc.code, "지식 반영 결과를 확정하지 못했습니다."
    if isinstance(exc, UsageStartError):
        return "USAGE_UNAVAILABLE", "사용량 기록을 시작하지 못했습니다."
    if isinstance(exc, (asyncpg.PostgresError, OSError, asyncio.TimeoutError)):
        return "STORAGE_FAILED", "저장소 처리에 실패했습니다."
    return "INTERNAL_ERROR", "지식 반영 중 오류가 발생했습니다."


async def _finish(conn, *, store_id: int, event_id: int, token: str, status: str,
                  card_id: int | None = None, knowledge_revision: int | None = None) -> str:
    await finish_owner_event(
        conn, store_id=store_id, event_id=event_id, claim_token=token,
        result=ApplyOwnerAnswerResult(
            status=status,
            card_id=str(card_id) if card_id is not None else None,
            knowledge_revision=(str(knowledge_revision)
                                if knowledge_revision is not None else None)))
    return status


async def _finish_failed(pool, *, store_id: int, event_id: int, token: str,
                         code: str, message: str) -> str:
    """별도 트랜잭션에서 FAILED 를 보고한다. 보고 자체가 실패하면 기록만 남긴다."""
    retryable = ERROR_TABLE[code][1]
    request_id = f"owner-event:{event_id}"
    result = ApplyOwnerAnswerResult(
        status="FAILED", retryable=retryable,
        error=ErrorDetail(code=code, message=message, retryable=retryable,
                          request_id=request_id, operation_id=request_id))
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await finish_owner_event(conn, store_id=store_id, event_id=event_id,
                                         claim_token=token, result=result)
    except Exception:
        # lease 를 잃었거나 R 이 거절했다. 같은 사건을 여기서 다시 돌리지 않는다
        logger.exception("점주 답변 FAILED 보고 실패 store=%s event=%s code=%s",
                         store_id, event_id, code)
    return "FAILED"


async def _finish_recorded(conn, *, store_id: int, event_id: int, token: str,
                           proposal: dict) -> str:
    """이미 결론이 난 제안을 R 에 보고한다(재시도·경합 뒤 멱등 재실행).

    LINKED/PUBLISHED 는 카드가 지금도 서빙 가능한지 다시 확인한다. 그 사이 검수로
    되돌려졌으면 REVIEW 로 보고한다 — 같은 STALE_KNOWLEDGE 로 재시도를 소진하지 않는다.
    """
    status = proposal["status"]
    if status in ("LINKED", "PUBLISHED"):
        card_id = proposal["result_card_id"]
        linked = await _linked_target(conn, store_id=store_id, card_id=card_id)
        if linked is not None:
            return await _finish(conn, store_id=store_id, event_id=event_id, token=token,
                                 status=status, card_id=card_id,
                                 knowledge_revision=linked[1])
        if status == "LINKED":
            # 연결 대상이 더는 공개 카드가 아니다. 검수 대기 제안으로 돌린다
            await _set_proposal(conn, store_id=store_id,
                                proposal_id=int(proposal["proposal_id"]),
                                status="PENDING_REVIEW")
    return await _finish(conn, store_id=store_id, event_id=event_id, token=token,
                         status="REVIEW")


async def _heartbeat(pool, *, store_id: int, event_id: int, token: str) -> None:
    if not await heartbeat_owner_event(pool, store_id=store_id, event_id=event_id,
                                       claim_token=token):
        raise _LeaseLost()


# ---------------------------------------------------------------------------
# 처리
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnswerOutcome:
    kind: str  # NO_FACTS | FACTS_PENDING | REVIEW | PUBLISH | LINKED
    relation: str  # NEW | SUPPLEMENT | IDENTICAL (knowledge_change_proposals.relation_type)
    cards: tuple[AnswerCard, ...]
    target: AnswerCard | None


def decide_outcome(fact_count: int, cards: Sequence[AnswerCard]) -> AnswerOutcome:
    """점주 답변 자료가 이어진 카드로 결과를 정한다(설계 A-D3 를 카드 단위로).

    - 사실 0개 → NO_FACTS(검수). 사실은 있으나 이어진 카드 없음(보류) → FACTS_PENDING(검수).
    - 공개 카드에 새 초안이 생겼거나 새 카드가 검수 필요 → REVIEW
      (공개 카드 변경이 있으면 SUPPLEMENT·대상=첫 변경 카드, 아니면 NEW).
    - 새 카드만 있고 모두 PENDING·사유 없음 → PUBLISH(새 카드만 공개, 이미 공개된 같은 카드는 그대로).
    - 공개 카드에만 이어지고 바뀐 판 없음 → LINKED(IDENTICAL).
    """
    if fact_count == 0:
        return AnswerOutcome("NO_FACTS", "NEW", (), None)
    if not cards:
        return AnswerOutcome("FACTS_PENDING", "NEW", (), None)
    new = [c for c in cards if c.published_version_id is None]
    changed = [c for c in cards if c.published_version_id is not None
               and c.draft_version_id != c.published_version_id]
    linked = [c for c in cards if c.published_version_id is not None
              and c.draft_version_id == c.published_version_id]
    blocked = [c for c in new if c.review_status != "PENDING" or c.needs_review_reason]
    if changed or blocked:
        return AnswerOutcome("REVIEW", "SUPPLEMENT" if changed else "NEW",
                             tuple(changed + new), changed[0] if changed else None)
    if new:
        return AnswerOutcome("PUBLISH", "NEW", tuple(new), None)
    return AnswerOutcome("LINKED", "IDENTICAL", tuple(linked), linked[0])


def _outcome_reason(outcome: AnswerOutcome) -> str:
    if outcome.kind in ("NO_FACTS", "FACTS_PENDING"):
        return outcome.kind
    return f"OWNER_ANSWER_{outcome.kind}"


async def _read_outcome(conn, *, store_id: int, source_id: int) -> AnswerOutcome:
    cards = await owner_text.answer_cards(conn, store_id, source_id=source_id)
    count = await owner_text.answer_fact_count(conn, store_id, source_id=source_id)
    return decide_outcome(count, cards)


async def _flag_outcome(conn, *, store_id: int, outcome: AnswerOutcome) -> None:
    """검수로 넘기는 결과의 카드마다 점주 답변 사유를 남긴다(안전 신호는 덮지 않는다)."""
    targets = outcome.cards or ((outcome.target,) if outcome.target is not None else ())
    for card in targets:
        await _flag_target_review(conn, store_id=store_id, card_id=card.card_id,
                                  relation=outcome.relation)


async def _record_outcome(conn, *, store_id: int, event_id: int, token: str,
                          answer_id: int, outcome: AnswerOutcome, question: str,
                          answer: str) -> tuple[str | None, dict]:
    """판정을 제안으로 남긴다. LINKED·REVIEW 는 같은 트랜잭션에서 보고까지 닫는다.

    반환: (보고한 상태 또는 None, 제안 행). 상태가 None 이면 PUBLISH 공개 단계가 남았다.
    """
    text = (await _card_text(conn, store_id=store_id, card=outcome.cards[0])
            if outcome.cards else None)
    if text is not None:
        title, content, category_id = text
    else:
        # 카드가 없으면(사실 0개·보류) 질문·답변을 그대로 적고 시스템 '기타' 로 둔다
        title, content = question, answer
        category_id = await resolve_owner_answer_category(conn, store_id=store_id,
                                                          category_id=None)
    target = outcome.target
    fields = dict(store_id=store_id, answer_id=answer_id, relation=outcome.relation,
                  target_card_id=target.card_id if target is not None else None,
                  target_version_id=target.published_version_id if target is not None else None,
                  category_id=category_id, title=title, content=content,
                  reason=_outcome_reason(outcome))

    if outcome.kind == "LINKED":
        linked = await _linked_target(conn, store_id=store_id, card_id=target.card_id)
        if linked is not None:
            version_id, knowledge_revision = linked
            proposal = await _insert_proposal(conn, **fields, status="LINKED",
                                              result_card_id=target.card_id,
                                              result_version_id=version_id)
            if proposal["status"] != "LINKED":
                return await _finish_recorded(conn, store_id=store_id, event_id=event_id,
                                              token=token, proposal=proposal), proposal
            await conn.execute(
                """
                update owner_answers set card_id = $3
                where answer_id = $2
                  and question_id in (select question_id from pending_questions where store_id = $1)
                """,
                store_id, answer_id, target.card_id)
            return await _finish(conn, store_id=store_id, event_id=event_id, token=token,
                                 status="LINKED", card_id=target.card_id,
                                 knowledge_revision=knowledge_revision), proposal
        # 이어진 카드가 지금 서빙 가능한 공개 카드가 아니다. 검수로 넘긴다
    elif outcome.kind == "PUBLISH":
        proposal = await _insert_proposal(conn, **fields, status="ANALYZED")
        if proposal["status"] != "ANALYZED":
            return await _finish_recorded(conn, store_id=store_id, event_id=event_id,
                                          token=token, proposal=proposal), proposal
        return None, proposal

    # NO_FACTS·FACTS_PENDING·REVIEW, 서빙 불가 LINKED
    proposal = await _insert_proposal(conn, **fields, status="PENDING_REVIEW")
    if proposal["status"] != "PENDING_REVIEW":
        return await _finish_recorded(conn, store_id=store_id, event_id=event_id,
                                      token=token, proposal=proposal), proposal
    await _flag_outcome(conn, store_id=store_id, outcome=outcome)
    return await _finish(conn, store_id=store_id, event_id=event_id, token=token,
                         status="REVIEW"), proposal


async def _retarget_proposal(conn, *, store_id: int, proposal_id: int,
                             outcome: AnswerOutcome) -> None:
    """제안을 검수 대기로 돌리며 관계·대상·사유를 새 판정에 맞춘다.

    그래야 `_finish_proposal` 의 카드별 사유 재표시가 이 제안을 찾고, 검수 화면의
    관계 표시도 실제와 맞는다(Task 6 minor 1).
    """
    target = outcome.target
    await conn.execute(
        """
        update knowledge_change_proposals
        set status = 'PENDING_REVIEW', relation_type = $3, target_card_id = $4,
            target_version_id = $5, reason = $6, error = null
        where store_id = $1 and proposal_id = $2
        """,
        store_id, proposal_id, outcome.relation,
        target.card_id if target is not None else None,
        target.published_version_id if target is not None else None,
        _outcome_reason(outcome))


async def _resume_analyzed(pool, *, store_id: int, event_id: int, token: str,
                           answer_id: int, proposal: dict) -> str | tuple[AnswerCard, ...]:
    """앞선 시도가 ANALYZED(공개 대기)까지 남겼다. 카드를 다시 읽어 같은 판정으로 이어간다.

    여전히 PUBLISH 면 공개할 카드를 돌려준다. 그 사이 판정이 바뀌었으면(점주가 고침 등)
    제안을 검수 대기로 돌리고 REVIEW 로 보고한 상태 문자열을 돌려준다.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            source_id = await owner_text.owner_answer_source(conn, store_id,
                                                             owner_answer_id=answer_id)
            if source_id is None:
                raise _Failed("INVALID_REFERENCE", "점주 답변 자료를 찾을 수 없습니다.")
            outcome = await _read_outcome(conn, store_id=store_id, source_id=source_id)
            if outcome.kind == "PUBLISH":
                return outcome.cards
            await _retarget_proposal(conn, store_id=store_id,
                                     proposal_id=int(proposal["proposal_id"]), outcome=outcome)
            await _flag_outcome(conn, store_id=store_id, outcome=outcome)
            return await _finish(conn, store_id=store_id, event_id=event_id, token=token,
                                 status="REVIEW")


async def _publish_new(pool, *, store_id: int, event_id: int, token: str,
                       answer_id: int, owner: dict, proposal: dict,
                       cards: Sequence[AnswerCard]) -> str:
    """새 사실 카드 초안 전부를 한 번에 공개한다. 결과 카드는 첫 카드다."""
    if not cards:
        raise _Failed("INVALID_REFERENCE", "점주 답변 카드를 찾을 수 없습니다.")
    first = cards[0]
    card_id, draft_version_id = first.card_id, first.draft_version_id
    proposal_id = int(proposal["proposal_id"])

    await _heartbeat(pool, store_id=store_id, event_id=event_id, token=token)

    async def hook(conn, snapshot_id: int, knowledge_revision: int) -> None:
        # 발행 트랜잭션 안: 제안 확정과 R 완료 보고가 발행과 함께 커밋·롤백된다
        await _set_proposal(conn, store_id=store_id, proposal_id=proposal_id,
                            status="PUBLISHED", result_card_id=card_id,
                            result_version_id=draft_version_id)
        await conn.execute(
            """
            update owner_answers set card_id = $3
            where answer_id = $2
              and question_id in (select question_id from pending_questions where store_id = $1)
            """,
            store_id, answer_id, card_id)
        await _finish(conn, store_id=store_id, event_id=event_id, token=token,
                      status="PUBLISHED", card_id=card_id,
                      knowledge_revision=knowledge_revision)

    async def extend_lease() -> bool:
        # 색인 준비(임베딩)가 길면 lease 가 끝났을 수 있다. 공개 트랜잭션 전에 연장한다
        return await heartbeat_owner_event(pool, store_id=store_id, event_id=event_id,
                                           claim_token=token)

    result = await publish_cards(
        pool, store_id=store_id, member_id=int(owner["member_id"]),
        actor_user_id=int(owner["user_id"]),
        changes=[CardChange(c.card_id, c.draft_version_id, c.draft_version_id) for c in cards],
        idempotency_key=f"owner-answer:{answer_id}",
        usage_context=_usage_context(store_id, event_id, "EMBED", "embed"),
        in_transaction=hook, after_prepare=extend_lease)

    if result.status == "LEASE_LOST":
        # 다른 worker 몫이다. 공개도 보고도 하지 않는다(기존 lease 상실 처리와 같다)
        raise _LeaseLost()
    if result.status == "PUBLISHED":
        return "PUBLISHED"
    if result.status == "ALREADY_APPLIED":
        # 같은 발행이 이미 커밋됐다. 현재 판 기준으로 보고만 다시 한다
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _lock_publication(conn, store_id=store_id)
                await _set_proposal(conn, store_id=store_id, proposal_id=proposal_id,
                                    status="PUBLISHED", result_card_id=card_id,
                                    result_version_id=draft_version_id)
                return await _finish_recorded(
                    conn, store_id=store_id, event_id=event_id, token=token,
                    proposal=dict(proposal_id=proposal_id, status="PUBLISHED",
                                  result_card_id=card_id))
    if result.status == "NO_PROVENANCE":
        # 근거 없는 사실 카드(드문 경우)는 공개하지 않는다. 검수로 넘긴다
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _set_proposal(conn, store_id=store_id, proposal_id=proposal_id,
                                    status="PENDING_REVIEW")
                return await _finish(conn, store_id=store_id, event_id=event_id,
                                     token=token, status="REVIEW")
    if result.status == "INVALID_CONTENT":
        # 카드 본문이 비었거나 블록 상한을 넘는다. 다시 해도 같으므로 재시도하지 않는다
        raise _Failed("INVALID_CONTRACT", "답변 내용이 비어 있거나 너무 길어 공개할 수 없습니다.")
    if result.status == "STALE":
        code = result.error_code if result.error_code in ERROR_TABLE else "STALE_PUBLICATION"
        raise _Failed(code, "공개판이 바뀌어 다시 시도해야 합니다.")
    code = result.error_code if result.error_code in ERROR_TABLE else "INDEX_PREPARE_TIMEOUT"
    raise _Failed(code, "검색 색인을 준비하지 못했습니다.")


async def _apply(pool, *, store_id: int, event_id: int, token: str, answer_id: int) -> str:
    async with pool.acquire() as conn:
        context = await _load_context(conn, store_id=store_id, owner_answer_id=answer_id)
    source, owner, proposal = context["source"], context["owner"], context["proposal"]
    if source is None:
        raise _Failed("NOT_FOUND", "점주 답변을 찾을 수 없습니다.")
    if owner is None:
        raise _Failed("NOT_FOUND", "매장 점주 멤버십을 찾을 수 없습니다.")

    if proposal is not None and proposal["status"] != "ANALYZED":
        # 앞선 시도가 결론까지 남겼다. 수집을 다시 하지 않고 보고만 한다
        async with pool.acquire() as conn:
            async with conn.transaction():
                return await _finish_recorded(conn, store_id=store_id, event_id=event_id,
                                              token=token, proposal=proposal)

    question, answer = source["question_text"], source["answer_text"]
    if proposal is None:
        await _heartbeat(pool, store_id=store_id, event_id=event_id, token=token)
        async with pool.acquire() as conn:
            async with conn.transaction():
                source_id, status = await owner_text.ensure_owner_answer_source(
                    conn, store_id, owner_answer_id=answer_id,
                    actor_id=int(owner["user_id"]), question=question, answer=answer)
        if status != "DONE":
            # 추출·조립은 모델을 부른다. ingest_owner_text 는 연결을 짧게만 빌린다
            await _heartbeat(pool, store_id=store_id, event_id=event_id, token=token)
            await owner_text.ingest_owner_text(
                pool, store_id=store_id, source_id=source_id, question=question,
                answer=answer, run_tag=int(time.time() * 1000))
            await _heartbeat(pool, store_id=store_id, event_id=event_id, token=token)
        async with pool.acquire() as conn:
            async with conn.transaction():
                outcome = await _read_outcome(conn, store_id=store_id, source_id=source_id)
                finished, proposal = await _record_outcome(
                    conn, store_id=store_id, event_id=event_id, token=token,
                    answer_id=answer_id, outcome=outcome, question=question, answer=answer)
        if finished is not None:
            return finished
        cards = outcome.cards
    else:
        resumed = await _resume_analyzed(pool, store_id=store_id, event_id=event_id,
                                         token=token, answer_id=answer_id, proposal=proposal)
        if isinstance(resumed, str):
            return resumed
        cards = resumed

    return await _publish_new(pool, store_id=store_id, event_id=event_id, token=token,
                              answer_id=answer_id, owner=owner, proposal=proposal,
                              cards=cards)


async def process_next_owner_event(pool, *, store_id: int) -> str | None:
    """사건 하나를 처리한다. None(할 일 없음)|STALE|LINKED|REVIEW|PUBLISHED|FAILED."""
    claim = await claim_owner_event(pool, store_id=store_id)
    if claim is None:
        return None
    if claim.get("stale"):
        return "STALE"
    event_id = int(claim["event_id"])
    token = claim["claim_token"]
    answer_id = int(claim["owner_answer_id"])
    try:
        return await _apply(pool, store_id=store_id, event_id=event_id, token=token,
                            answer_id=answer_id)
    except _LeaseLost:
        logger.warning("점주 답변 lease 상실 store=%s event=%s", store_id, event_id)
        return "FAILED"
    except Exception as exc:
        code, message = _error_code(exc)
        logger.warning("점주 답변 반영 실패 store=%s event=%s code=%s type=%s",
                       store_id, event_id, code, type(exc).__name__)
        return await _finish_failed(pool, store_id=store_id, event_id=event_id,
                                    token=token, code=code, message=message)


async def _index_ready(pool, *, store_id: int, warned: dict[int, str]) -> bool:
    """활성 공개 색인이 있거나 승인 카드가 없는 매장의 사건을 처리한다.

    승인 지식이 있는데 색인이 없으면 INDEX_UNAVAILABLE 장애로 구분한다.
    사건을 태우지 않고 남겨 둔 채 건너뛰고, 상태가 바뀔 때만 한 번 경고한다.
    준비는 scripts/bootstrap_store_index.py 로 한다.
    """
    async with pool.acquire() as conn:
        status = await index_status(conn, store_id=store_id)
    if status.status in (READY, EMPTY):
        warned.pop(store_id, None)
        return True
    if warned.get(store_id) != status.status:
        warned[store_id] = status.status
        logger.warning(
            "공개 색인이 준비되지 않아 점주 답변 처리를 미룬다 store=%s status=%s "
            "— scripts/bootstrap_store_index.py 로 준비",
            store_id, status.status)
    return False


async def run_owner_answer_worker(pool, *, stop: asyncio.Event) -> None:
    """주기마다 사건이 있는 매장을 찾아 매장별로 비울 때까지 처리한다."""
    warned: dict[int, str] = {}
    while not stop.is_set():
        try:
            for store_id in await _stores_with_pending(pool):
                if not await _index_ready(pool, store_id=store_id, warned=warned):
                    continue
                for _ in range(MAX_EVENTS_PER_STORE):
                    if stop.is_set():
                        break
                    if await process_next_owner_event(pool, store_id=store_id) is None:
                        break
                if stop.is_set():
                    break
        except Exception:
            logger.exception("점주 답변 worker 주기 실패")
        try:
            await asyncio.wait_for(stop.wait(),
                                   timeout=get_settings().w_owner_answer_worker_interval_sec)
        except asyncio.TimeoutError:
            pass
