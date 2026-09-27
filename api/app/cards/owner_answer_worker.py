"""점주 답변 반영 worker (W, Task 5).

R 이 남긴 `OWNER_ANSWER_SUBMITTED` 사건을 claim 해서 점주 답변을 지식에 반영하고
그 결과(LINKED / REVIEW / PUBLISHED / FAILED)를 R 에 돌려준다.

  - IDENTICAL: 현재 공개판에 있는 카드면 LINKED. 아니면 REVIEW 로 강등한다.
  - SUPPLEMENT·CONFLICT: 공개본을 바꾸지 않고 REVIEW(검수 대기 제안).
  - NEW(자동 공개 가능): 초안 카드를 만들고 `publish_cards` 로 공개한다. R 완료
    보고(`finish_owner_event`)는 **발행 트랜잭션 hook 안에서만** 부른다 — finish 가
    실패하면 발행까지 통째로 롤백돼 R 이 모르는 공개판이 남지 않는다.
  - 실패: 별도 트랜잭션에서 FAILED 를 보고한다. 재시도 여부는 ERROR_TABLE 이 정한다.

claim 뒤에는 연결을 오래 잡지 않는다. 관계 분석·색인 준비 같은 긴 단계 사이에
heartbeat 를 부르고, lease 를 잃었으면 아무것도 보고하지 않고 멈춘다(다른 worker 몫).
매장 격리는 코드 책임이다 (D1). 모든 조회는 store_id 로 제한한다.
"""
from __future__ import annotations

import asyncio
import logging

import asyncpg

from app.config import get_settings
from app.contracts.errors import ERROR_TABLE, ErrorDetail
from app.contracts.publication import ApplyOwnerAnswerResult
from app.contracts.usage import UsageContext
from app.db_session import ShortSession
from app.errors import ApiError
from app.learn.knowledge_apply import create_owner_answer_card
from app.learn.knowledge_loop import build_knowledge_plan
from app.learn.owner_handoff import (
    CONSUMER,
    claim_owner_event,
    finish_owner_event,
    heartbeat_owner_event,
)
from app.publish.approval import CardChange, publish_cards
from app.publish.content import current_manifest
from app.usage import DbUsageSink
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


async def _insert_proposal(conn, *, store_id: int, answer_id: int, plan, status: str,
                           result_card_id: int | None = None,
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
        store_id, answer_id, plan.relation_type, plan.target_card_id,
        plan.target_version_id, plan.category_id, plan.proposed_title[:200],
        plan.proposed_content, plan.reason, status, result_card_id, result_version_id)
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
    """검수 대상 카드에 사유를 남긴다. 레거시 점주 답변 경로와 같은 표시다."""
    if card_id is None:
        return
    await conn.execute(
        """
        update knowledge_cards set needs_review_reason = $3
        where store_id = $1 and card_id = $2 and review_status <> 'EXCLUDED'
        """,
        store_id, card_id, f"OWNER_ANSWER_{relation}")


async def _owner_answer_card(conn, *, store_id: int, answer_id: int) -> tuple[int, int] | None:
    """앞선 시도가 만든 카드(owner_answers.card_id)와 그 현재 초안 버전."""
    row = await conn.fetchrow(
        """
        select k.card_id, k.draft_version_id
        from owner_answers oa
        join knowledge_cards k on k.card_id = oa.card_id
        where k.store_id = $1 and oa.answer_id = $2
        """,
        store_id, answer_id)
    if row is None or row["draft_version_id"] is None:
        return None
    return int(row["card_id"]), int(row["draft_version_id"])


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

async def _record_plan(conn, *, store_id: int, event_id: int, token: str,
                       answer_id: int, actor_id: int, plan) -> tuple[str | None, dict, tuple | None]:
    """계획을 제안으로 남긴다. LINKED·REVIEW 는 같은 트랜잭션에서 보고까지 닫는다.

    반환: (보고한 상태 또는 None, 제안 행, NEW 카드 (card_id, draft_version_id)).
    상태가 None 이면 NEW 공개 단계가 남았다.
    """
    relation = plan.relation_type
    if relation == "IDENTICAL":
        linked = await _linked_target(conn, store_id=store_id, card_id=plan.target_card_id)
        if linked is not None:
            version_id, knowledge_revision = linked
            proposal = await _insert_proposal(
                conn, store_id=store_id, answer_id=answer_id, plan=plan, status="LINKED",
                result_card_id=plan.target_card_id, result_version_id=version_id)
            if proposal["status"] != "LINKED":
                return await _finish_recorded(conn, store_id=store_id, event_id=event_id,
                                              token=token, proposal=proposal), proposal, None
            await conn.execute(
                """
                update owner_answers set card_id = $3
                where answer_id = $2
                  and question_id in (select question_id from pending_questions where store_id = $1)
                """,
                store_id, answer_id, plan.target_card_id)
            return await _finish(conn, store_id=store_id, event_id=event_id, token=token,
                                 status="LINKED", card_id=plan.target_card_id,
                                 knowledge_revision=knowledge_revision), proposal, None
    elif relation == "NEW" and plan.auto_publish:
        proposal = await _insert_proposal(conn, store_id=store_id, answer_id=answer_id,
                                          plan=plan, status="ANALYZED")
        if proposal["status"] != "ANALYZED":
            return await _finish_recorded(conn, store_id=store_id, event_id=event_id,
                                          token=token, proposal=proposal), proposal, None
        # 앞선 시도가 만든 카드가 있으면 재사용한다. 같은 답변으로 카드를 두 번 만들지 않는다
        card = await _owner_answer_card(conn, store_id=store_id, answer_id=answer_id)
        if card is None:
            card = await create_owner_answer_card(
                conn, store_id=store_id, category_id=plan.category_id,
                title=plan.proposed_title[:200], content=plan.proposed_content,
                answer_id=answer_id, actor_id=actor_id)
        return None, proposal, card

    # SUPPLEMENT·CONFLICT, 공개판에 없는 IDENTICAL, 자동 공개 불가 NEW
    proposal = await _insert_proposal(conn, store_id=store_id, answer_id=answer_id,
                                      plan=plan, status="PENDING_REVIEW")
    if proposal["status"] != "PENDING_REVIEW":
        return await _finish_recorded(conn, store_id=store_id, event_id=event_id,
                                      token=token, proposal=proposal), proposal, None
    await _flag_target_review(conn, store_id=store_id, card_id=plan.target_card_id,
                              relation=relation)
    return await _finish(conn, store_id=store_id, event_id=event_id, token=token,
                         status="REVIEW"), proposal, None


async def _publish_new(pool, *, store_id: int, event_id: int, token: str,
                       answer_id: int, owner: dict, proposal: dict,
                       card: tuple[int, int] | None) -> str:
    if card is None:
        # 앞선 시도가 ANALYZED 까지 남겼다. 그때 만든 카드를 이어서 공개한다
        async with pool.acquire() as conn:
            card = await _owner_answer_card(conn, store_id=store_id, answer_id=answer_id)
    if card is None:
        raise _Failed("INVALID_REFERENCE", "점주 답변 카드를 찾을 수 없습니다.")
    card_id, draft_version_id = card
    proposal_id = int(proposal["proposal_id"])

    await _heartbeat(pool, store_id=store_id, event_id=event_id, token=token)

    async def hook(conn, snapshot_id: int, knowledge_revision: int) -> None:
        # 발행 트랜잭션 안: 제안 확정과 R 완료 보고가 발행과 함께 커밋·롤백된다
        await _set_proposal(conn, store_id=store_id, proposal_id=proposal_id,
                            status="PUBLISHED", result_card_id=card_id,
                            result_version_id=draft_version_id)
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
        changes=[CardChange(card_id, draft_version_id, draft_version_id)],
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
        # 출처 없는 점주 답변 카드를 아직 공개하지 않는다(플래그 OFF). 검수로 넘긴다
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _set_proposal(conn, store_id=store_id, proposal_id=proposal_id,
                                    status="PENDING_REVIEW")
                return await _finish(conn, store_id=store_id, event_id=event_id,
                                     token=token, status="REVIEW")
    if result.status == "INVALID_CONTENT":
        # 답변 원문이 비었거나 블록 상한을 넘는다. 다시 해도 같으므로 재시도하지 않는다
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
        # 앞선 시도가 결론까지 남겼다. 분석을 다시 부르지 않고 보고만 한다
        async with pool.acquire() as conn:
            async with conn.transaction():
                return await _finish_recorded(conn, store_id=store_id, event_id=event_id,
                                              token=token, proposal=proposal)

    card = None
    if proposal is None:
        await _heartbeat(pool, store_id=store_id, event_id=event_id, token=token)
        # 관계 분석은 모델을 부른다. 쿼리마다 연결을 짧게 빌리는 ShortSession 을 넘겨
        # 모델 호출 중에는 풀 연결을 쥐지 않는다(build_knowledge_plan 은 트랜잭션을 쓰지 않는다)
        plan = await build_knowledge_plan(
            ShortSession(pool), store_id, source["question_text"], source["answer_text"],
            usage_context=_usage_context(store_id, event_id, "RELATION", "relation"),
            usage_sink=DbUsageSink(pool))
        await _heartbeat(pool, store_id=store_id, event_id=event_id, token=token)
        async with pool.acquire() as conn:
            async with conn.transaction():
                finished, proposal, card = await _record_plan(
                    conn, store_id=store_id, event_id=event_id, token=token,
                    answer_id=answer_id, actor_id=int(owner["user_id"]), plan=plan)
        if finished is not None:
            return finished

    return await _publish_new(pool, store_id=store_id, event_id=event_id, token=token,
                              answer_id=answer_id, owner=owner, proposal=proposal,
                              card=card)


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


async def run_owner_answer_worker(pool, *, stop: asyncio.Event) -> None:
    """주기마다 사건이 있는 매장을 찾아 매장별로 비울 때까지 처리한다."""
    while not stop.is_set():
        try:
            for store_id in await _stores_with_pending(pool):
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
