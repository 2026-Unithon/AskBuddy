"""검토된 점주 답변 제안을 카드로 공개하는 원자 작업."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Sequence

import asyncpg

from app.ingest.owner_text import answer_cards, answer_fact_count, owner_answer_source
from app.publish.approval import CardChange, PublishCardsResult, publish_cards
from app.publish.service import _lock_publication

logger = logging.getLogger(__name__)

# 나중 승인할 수 있는 제안 상태
APPROVABLE_PROPOSAL_STATUSES = ("ANALYZED", "PENDING_REVIEW", "FAILED")

# R 완료 접점(finish_owner_review) 자리.
# (conn, owner_answer_id, card_id, card_version_id, knowledge_revision)
OwnerReviewNotifier = Callable[[asyncpg.Connection, int, int, int, int], Awaitable[None]]


async def _attach_owner_answer_citations(
    db: asyncpg.Connection,
    store_id: int,
    answer_id: int,
    card_id: int,
    version_id: int,
) -> None:
    await db.execute(
        """
        insert into message_citations (message_id, card_id, version_id, relevance)
        select m.message_id, $2, $3, 100.00
        from chat_messages m
        join chat_sessions s on s.session_id=m.session_id
        where m.owner_answer_id = $1
          and s.store_id = $4
          and not exists (
            select 1 from message_citations existing
            where existing.message_id = m.message_id
              and existing.card_id = $2 and existing.version_id = $3
          )
        """,
        answer_id,
        card_id,
        version_id,
        store_id,
    )


async def resolve_owner_answer_category(db, *, store_id: int, category_id: int | None) -> int:
    """제안 카테고리가 살아 있으면 그대로, 아니면 시스템 '기타' 로 보낸다."""
    resolved = await db.fetchval(
        """
        select category_id from task_categories
        where store_id = $1 and category_id = $2
          and deleted_at is null and is_enabled = true
        """,
        store_id,
        category_id,
    )
    if resolved is None:
        resolved = await db.fetchval(
            """
            select category_id from task_categories
            where store_id = $1 and is_system = true
              and deleted_at is null and is_enabled = true
            """,
            store_id,
        )
    if resolved is None:
        raise ValueError("system Other category is missing")
    return int(resolved)


# ---------------------------------------------------------------------------
# 나중 승인: 검수 대기(REVIEW) 제안 → publish_cards (W, Task 6)
# ---------------------------------------------------------------------------

async def _lock_proposal(conn, *, store_id: int, proposal_id: int):
    return await conn.fetchrow(
        """
        select * from knowledge_change_proposals
        where store_id = $1 and proposal_id = $2
        for update
        """,
        store_id,
        proposal_id,
    )


async def _finish_proposal(conn, *, store_id: int, proposal, card_id: int,
                           version_id: int, card_ids: Sequence[int] = ()) -> None:
    """발행 트랜잭션 안에서 제안을 PUBLISHED 로 닫고 답변·인용을 카드에 잇는다.

    card_ids: 이번에 함께 공개한 카드. publish_cards 가 공개하며 needs_review_reason 을
    비웠으므로, 같은 카드를 대상으로 남은 다른 검수 대기 제안이 있으면 사유를 다시 표시한다.
    """
    proposal_id = int(proposal["proposal_id"])
    answer_id = int(proposal["answer_id"])
    await conn.execute(
        """
        update knowledge_change_proposals
        set status = 'PUBLISHED', result_card_id = $3, result_version_id = $4,
            error = null, resolved_at = now()
        where store_id = $1 and proposal_id = $2
        """,
        store_id,
        proposal_id,
        card_id,
        version_id,
    )
    await conn.execute(
        """
        update owner_answers set card_id = $3
        where answer_id = $2
          and question_id in (select question_id from pending_questions where store_id = $1)
        """,
        store_id,
        answer_id,
        card_id,
    )
    for reviewed in dict.fromkeys([card_id, *card_ids]):
        await conn.execute(
            """
            update knowledge_cards k
            set needs_review_reason = (
              select 'OWNER_ANSWER_' || p.relation_type
              from knowledge_change_proposals p
              where p.store_id = $1 and p.target_card_id = $2
                and p.status = 'PENDING_REVIEW'
              order by p.created_at desc, p.proposal_id desc
              limit 1
            )
            where k.store_id = $1 and k.card_id = $2
            """,
            store_id,
            reviewed,
        )
    await _attach_owner_answer_citations(conn, store_id, answer_id, card_id, version_id)


LEGACY_PROPOSAL_MESSAGE = "예전 방식 제안이라 카드로 만들 수 없어요. 카드 화면에서 직접 고쳐 주세요."
NO_DRAFT_MESSAGE = "이 답변에서 카드에 넣을 내용을 찾지 못했어요. 제안을 닫아 주세요."
FACTS_HELD_MESSAGE = ("이 답변의 내용은 점주님이 고치던 카드 초안 때문에 보류됐어요. "
                      "그 카드를 먼저 검수한 뒤 제안을 닫아 주세요.")


async def _close_already_published(conn, *, store_id: int, proposal, cards,
                                   notify_r: "OwnerReviewNotifier | None") -> bool:
    """답변 자료 카드가 모두 이미 공개돼 지금 서빙 가능하면 제안을 PUBLISHED 로 닫는다.

    카드 화면에서 초안을 먼저 공개한 경우다. worker 의 LINKED 판정과 같은 확인
    (`_linked_target`)을 쓴다. 공개판 잠금을 쥔 트랜잭션 안에서만 부른다.
    닫았으면 True. 하나라도 서빙 불가면 아무것도 바꾸지 않고 False.
    """
    # 지연 import: worker 가 이 모듈을 import 한다(순환 방지)
    from app.cards.owner_answer_worker import _linked_target
    if not cards:
        return False
    targets = []
    for card in cards:
        linked = await _linked_target(conn, store_id=store_id, card_id=card.card_id)
        if linked is None:
            return False
        targets.append(linked)
    first = cards[0]
    version_id, knowledge_revision = targets[0]
    await _finish_proposal(conn, store_id=store_id, proposal=proposal, card_id=first.card_id,
                           version_id=version_id, card_ids=[c.card_id for c in cards])
    if notify_r is None:
        logger.warning("R 완료 접점 미연결 — 인계 문서 참조 store=%s proposal=%s answer=%s",
                       store_id, proposal["proposal_id"], proposal["answer_id"])
    else:
        await notify_r(conn, int(proposal["answer_id"]), first.card_id, version_id,
                       knowledge_revision)
    return True


async def approve_owner_proposal(
    pool,
    *,
    store_id: int,
    member_id: int,
    actor_user_id: int,
    proposal_id: int,
    usage_context,
    notify_r: OwnerReviewNotifier | None = None,
) -> PublishCardsResult:
    """점주 답변 제안을 승인한다 = 그 답변 자료가 만든 사실 카드 초안을 모두 공개한다.

    사실 초안이 없는 제안(v1 관계 분석 제안·사실 0개)은 ValueError — R 라우트가 409 로 바꾼다.
    초안은 없지만 답변 카드가 모두 이미 공개돼 서빙 중이면(카드 화면에서 먼저 공개) 제안을
    PUBLISHED 로 닫고 R 에 보고한 뒤 ALREADY_APPLIED 를 돌려준다.

    1. 짧은 트랜잭션: 공개판 → 제안 순으로 잠그고 이 답변 자료(OWNER_TEXT)의 초안 카드를 고른다.
    2. 연결 없이 `publish_cards` 를 부른다(색인 준비는 그 안에서).
    3. hook(발행 트랜잭션 안): 제안을 다시 잠가 여전히 승인 가능한지 확인하고
       PUBLISHED 로 닫은 뒤 R 완료 접점(notify_r)을 부른다. 실패하면 발행째 롤백된다.

    NO_PROVENANCE·STALE·PREPARE_FAILED 는 결과를 그대로 돌려주고 제안은 건드리지
    않는다(다시 승인할 수 있다).
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 공개판 행을 먼저 잠가 발행 트랜잭션과 직렬화한다
            await _lock_publication(conn, store_id)
            proposal = await _lock_proposal(conn, store_id=store_id, proposal_id=proposal_id)
            if proposal is None:
                raise LookupError("knowledge proposal not found")
            if (proposal["status"] == "PUBLISHED"
                    and proposal["result_card_id"] is not None
                    and proposal["result_version_id"] is not None):
                # 같은 승인의 재요청. 이미 같은 트랜잭션에서 공개·R 보고까지 끝났다
                return PublishCardsResult(status="ALREADY_APPLIED")
            if proposal["status"] not in APPROVABLE_PROPOSAL_STATUSES:
                raise ValueError("승인할 수 없는 상태의 제안입니다")
            source_id = await owner_answer_source(
                conn, store_id, owner_answer_id=int(proposal["answer_id"]))
            if source_id is None:
                # 관계 분석(v1) 시절 제안 — 사실 자료가 없어 카드로 만들 수 없다
                raise ValueError(LEGACY_PROPOSAL_MESSAGE)
            cards = await answer_cards(conn, store_id, source_id=source_id)
            drafts = [c for c in cards
                      if c.published_version_id is None
                      or c.draft_version_id != c.published_version_id]
            if not drafts:
                # 카드 화면에서 이미 공개했다 → 제안·R 상태를 같은 결론(PUBLISHED)으로 닫는다
                if await _close_already_published(conn, store_id=store_id, proposal=proposal,
                                                  cards=cards, notify_r=notify_r):
                    return PublishCardsResult(status="ALREADY_APPLIED")
                if not cards and await answer_fact_count(conn, store_id, source_id=source_id):
                    raise ValueError(FACTS_HELD_MESSAGE)
                raise ValueError(NO_DRAFT_MESSAGE)
    first = drafts[0]

    async def hook(conn, snapshot_id: int, knowledge_revision: int) -> None:
        current = await _lock_proposal(conn, store_id=store_id, proposal_id=proposal_id)
        if current is None or current["status"] not in APPROVABLE_PROPOSAL_STATUSES:
            # 준비 사이 다른 경로가 제안을 닫았다. 발행째 롤백한다
            raise ValueError("knowledge proposal changed during publication")
        await _finish_proposal(conn, store_id=store_id, proposal=current,
                               card_id=first.card_id, version_id=first.draft_version_id,
                               card_ids=[c.card_id for c in drafts])
        if notify_r is None:
            logger.warning(
                "R 완료 접점 미연결 — 인계 문서 참조 store=%s proposal=%s answer=%s",
                store_id, proposal_id, current["answer_id"])
            return
        await notify_r(conn, int(current["answer_id"]), first.card_id, first.draft_version_id,
                       knowledge_revision)

    return await publish_cards(
        pool,
        store_id=store_id,
        member_id=member_id,
        actor_user_id=actor_user_id,
        changes=[CardChange(c.card_id, c.draft_version_id, c.draft_version_id) for c in drafts],
        idempotency_key=f"owner-proposal:{proposal_id}",
        usage_context=usage_context,
        in_transaction=hook,
    )
