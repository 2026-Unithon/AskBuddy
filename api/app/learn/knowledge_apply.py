"""검토된 점주 답변 제안을 카드로 공개하는 원자 작업."""
from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable

import asyncpg

from app.cards import repository as card_repo
from app.config import get_settings
from app.publish.approval import CardChange, PublishCardsResult, publish_cards
from app.publish.service import _lock_publication

logger = logging.getLogger(__name__)

# 나중 승인할 수 있는 제안 상태
APPROVABLE_PROPOSAL_STATUSES = ("ANALYZED", "PENDING_REVIEW", "FAILED")

# R 완료 접점(finish_owner_review) 자리.
# (conn, owner_answer_id, card_id, card_version_id, knowledge_revision)
OwnerReviewNotifier = Callable[[asyncpg.Connection, int, int, int, int], Awaitable[None]]


async def prepare_proposal(db, store_id: int, proposal_id: int):
    proposal = await db.fetchrow(
        "select * from knowledge_change_proposals where store_id = $1 and proposal_id = $2",
        store_id, proposal_id)
    if proposal is None:
        raise LookupError("knowledge proposal not found")
    if proposal["status"] not in ("ANALYZED", "PENDING_REVIEW", "FAILED"):
        raise ValueError("proposal cannot be published")
    # 옛 색인(card_embeddings) 준비는 제거했다. 두 번째 값은 호출부(R v1 답변 경로)
    # 호환을 위해 자리만 남긴다 — 이 경로의 색인은 R 인계 문서 §7 참조
    return dict(proposal), None


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


async def create_owner_answer_card(
    db,
    *,
    store_id: int,
    category_id: int | None,
    title: str,
    content: str,
    answer_id: int,
    actor_id: int,
) -> tuple[int, int]:
    """점주 답변으로 **초안** 카드를 만든다. 공개하지 않는다.

    is_verified 를 켜지 않으므로 레거시 트리거가 초안 버전만 만든다. 공개는
    호출부가 정한다(worker 는 publish_cards, 레거시 경로는 즉시 승인).
    반환: (card_id, draft_version_id)
    """
    category_id = await resolve_owner_answer_category(
        db, store_id=store_id, category_id=category_id)
    card_id = int(
        await db.fetchval(
            """
            insert into knowledge_cards (
              store_id, category_id, source_id, title, content,
              confidence, is_verified, assignment_type
            ) values ($1, $2, null, $3, $4, 100.00, false, 'AUTOMATIC')
            returning card_id
            """,
            store_id,
            category_id,
            title,
            content,
        )
    )
    draft_version_id = int(
        await db.fetchval(
            "select draft_version_id from knowledge_cards where store_id = $1 and card_id = $2",
            store_id,
            card_id,
        )
    )
    await db.execute(
        """
        update card_versions
        set change_source = 'OWNER_ANSWER', created_by = $3, owner_answer_id = $4
        where store_id = $1 and version_id = $2
        """,
        store_id,
        draft_version_id,
        actor_id,
        answer_id,
    )
    await db.execute(
        """
        update owner_answers set card_id = $3
        where answer_id = $2
          and question_id in (select question_id from pending_questions where store_id = $1)
        """,
        store_id,
        answer_id,
        card_id,
    )
    return card_id, draft_version_id


async def publish_new_proposal(
    db: asyncpg.Connection,
    store_id: int,
    proposal_id: int,
    actor_id: int,
    *, preparation,
) -> tuple[int, int]:
    proposal = await db.fetchrow(
        """
        select * from knowledge_change_proposals
        where store_id = $1 and proposal_id = $2
        for update
        """,
        store_id,
        proposal_id,
    )
    if proposal is None:
        raise LookupError("knowledge proposal not found")
    expected, _ = preparation
    if dict(proposal) != expected:
        raise ValueError("knowledge proposal changed during embedding")
    if proposal["relation_type"] != "NEW":
        raise ValueError("proposal is not NEW")
    if proposal["status"] not in ("ANALYZED", "PENDING_REVIEW", "FAILED"):
        raise ValueError("proposal cannot be published")

    category_id = await resolve_owner_answer_category(
        db, store_id=store_id, category_id=proposal["category_id"])
    card_id, draft_version_id = await create_owner_answer_card(
        db,
        store_id=store_id,
        category_id=category_id,
        title=proposal["proposed_title"],
        content=proposal["proposed_content"],
        answer_id=int(proposal["answer_id"]),
        actor_id=actor_id,
    )
    # 레거시 경로는 검수 없이 즉시 공개한다. 동기화 트리거가 초안을 공개 포인터로 옮긴다
    await db.execute(
        "update knowledge_cards set is_verified = true where store_id = $1 and card_id = $2",
        store_id,
        card_id,
    )
    version_id = draft_version_id
    await db.execute(
        """
        update knowledge_change_proposals
        set status = 'PUBLISHED', result_card_id = $3, result_version_id = $4,
            error = null, resolved_at = now()
        where proposal_id = $2 and store_id = $1
        """,
        store_id,
        proposal_id,
        card_id,
        version_id,
    )
    await db.execute(
        """
        update knowledge_change_proposals set category_id = $3
        where store_id = $1 and proposal_id = $2
        """,
        store_id,
        proposal_id,
        category_id,
    )
    await _attach_owner_answer_citations(
        db, store_id, int(proposal["answer_id"]), card_id, version_id
    )
    return card_id, version_id


async def publish_existing_proposal(
    db: asyncpg.Connection,
    store_id: int,
    proposal_id: int,
    actor_id: int,
    *, preparation,
) -> tuple[int, int]:
    proposal = await db.fetchrow(
        """
        select * from knowledge_change_proposals
        where store_id = $1 and proposal_id = $2
        for update
        """,
        store_id,
        proposal_id,
    )
    if proposal is None:
        raise LookupError("knowledge proposal not found")
    expected, _ = preparation
    if dict(proposal) != expected:
        raise ValueError("knowledge proposal changed during embedding")
    if proposal["relation_type"] not in ("SUPPLEMENT", "CONFLICT"):
        raise ValueError("proposal does not update an existing card")
    if proposal["status"] != "PENDING_REVIEW":
        raise ValueError("proposal is not pending review")

    card_id = int(proposal["target_card_id"])
    card = await db.fetchrow(
        """
        select * from knowledge_cards
        where store_id = $1 and card_id = $2
        for update
        """,
        store_id,
        card_id,
    )
    if card is None or card["review_status"] != "APPROVED":
        raise ValueError("target card is not currently approved")
    if card["published_version_id"] != proposal["target_version_id"]:
        raise ValueError("target card version changed")
    if card["draft_version_id"] != card["published_version_id"]:
        raise ValueError("target card has another unpublished draft")

    version_id = int(
        await db.fetchval(
            """
            insert into card_versions (
              store_id, card_id, version_no, title, content,
              change_source, created_by, owner_answer_id
            )
            select $1, $2, coalesce(max(version_no), 0) + 1,
                   $3, $4, 'OWNER_ANSWER', $5, $6
            from card_versions where store_id = $1 and card_id = $2
            returning version_id
            """,
            store_id,
            card_id,
            proposal["proposed_title"],
            proposal["proposed_content"],
            actor_id,
            int(proposal["answer_id"]),
        )
    )
    await db.execute(
        """
        update knowledge_cards
        set title = $3, content = $4,
            draft_version_id = $5, published_version_id = $5
        where store_id = $1 and card_id = $2
        """,
        store_id,
        card_id,
        proposal["proposed_title"],
        proposal["proposed_content"],
        version_id,
    )
    await db.execute(
        "update owner_answers set card_id = $2 where answer_id = $1",
        int(proposal["answer_id"]),
        card_id,
    )
    await db.execute(
        """
        update knowledge_change_proposals
        set status = 'PUBLISHED', result_card_id = $3, result_version_id = $4,
            error = null, resolved_at = now()
        where proposal_id = $2 and store_id = $1
        """,
        store_id,
        proposal_id,
        card_id,
        version_id,
    )
    await db.execute(
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
        card_id,
    )
    await db.execute(
        """
        insert into card_review_events (
          store_id, card_id, actor_id, action, from_status, to_status, metadata
        ) values ($1, $2, $3, 'PUBLISH_EDIT', 'APPROVED', 'APPROVED', $4::jsonb)
        """,
        store_id,
        card_id,
        actor_id,
        json.dumps(
            {
                "proposal_id": proposal_id,
                "from_version_id": int(proposal["target_version_id"]),
                "to_version_id": version_id,
            }
        ),
    )
    await _attach_owner_answer_citations(
        db, store_id, int(proposal["answer_id"]), card_id, version_id
    )
    return card_id, version_id


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


async def _owner_answer_draft(conn, *, store_id: int, answer_id: int):
    """worker 가 REVIEW 로 넘기며 남긴 점주 답변 초안 카드(owner_answers.card_id)."""
    return await conn.fetchrow(
        """
        select k.card_id, k.draft_version_id, k.review_status
        from owner_answers oa
        join knowledge_cards k on k.card_id = oa.card_id
        where k.store_id = $1 and oa.answer_id = $2
        for update of k
        """,
        store_id,
        answer_id,
    )


async def _lock_target_card(conn, *, store_id: int, card_id: int):
    return await conn.fetchrow(
        """
        select card_id, draft_version_id, published_version_id, review_status
        from knowledge_cards
        where store_id = $1 and card_id = $2
        for update
        """,
        store_id,
        card_id,
    )


async def _mark_owner_answer_version(conn, *, store_id: int, version_id: int,
                                     answer_id: int) -> None:
    """새 초안이 점주 답변 판임을 적는다. RAW 블록 출처가 카드 자료가 아니라 이 답변이 된다.

    create_draft 가 이전 판의 자료 근거(card_evidence)를 복사하지만 이 판의 본문은
    자료가 아니라 점주 답변이다. 자료 근거로 보이지 않게 복사본을 지운다.
    """
    await conn.execute(
        """
        update card_versions set change_source = 'OWNER_ANSWER', owner_answer_id = $3
        where store_id = $1 and version_id = $2
        """,
        store_id,
        version_id,
        answer_id,
    )
    await conn.execute(
        "delete from card_evidence where store_id = $1 and version_id = $2",
        store_id,
        version_id,
    )


async def _read_version(conn, *, store_id: int, version_id: int):
    return await conn.fetchrow(
        """
        select change_source, title, content, owner_answer_id
        from card_versions
        where store_id = $1 and version_id = $2
        """,
        store_id,
        version_id,
    )


async def _set_proposal_category(conn, *, store_id: int, proposal_id: int,
                                 category_id: int) -> None:
    await conn.execute(
        """
        update knowledge_change_proposals set category_id = $3
        where store_id = $1 and proposal_id = $2
        """,
        store_id,
        proposal_id,
        category_id,
    )


def _is_staged_draft(version, proposal) -> bool:
    """카드의 미공개 초안이 앞선 승인 시도가 얹은 이 제안의 초안인가."""
    return (version is not None
            and version["change_source"] == "OWNER_ANSWER"
            and version["owner_answer_id"] == proposal["answer_id"]
            and version["title"] == proposal["proposed_title"]
            and version["content"] == proposal["proposed_content"])


async def _stage_proposal_card(conn, *, store_id: int, proposal, actor_id: int) -> tuple[int, int]:
    """공개할 카드 초안을 준비한다. 반환: (card_id, draft_version_id)."""
    relation = proposal["relation_type"]
    answer_id = int(proposal["answer_id"])
    if relation == "NEW":
        # 레거시처럼 실제로 쓸 카테고리를 제안에 되써 둔다(삭제·비활성 → 기타)
        category_id = await resolve_owner_answer_category(
            conn, store_id=store_id, category_id=proposal["category_id"])
        await _set_proposal_category(conn, store_id=store_id,
                                     proposal_id=int(proposal["proposal_id"]),
                                     category_id=category_id)
        # worker 가 이미 만든 초안 카드가 있으면 재사용한다. 같은 답변으로 카드를 두 번 만들지 않는다
        card = await _owner_answer_draft(conn, store_id=store_id, answer_id=answer_id)
        if card is not None and card["draft_version_id"] is not None:
            if card["review_status"] == "EXCLUDED":
                raise ValueError("점주 답변 카드가 제외되어 승인할 수 없습니다")
            return int(card["card_id"]), int(card["draft_version_id"])
        return await create_owner_answer_card(
            conn,
            store_id=store_id,
            category_id=category_id,
            title=proposal["proposed_title"],
            content=proposal["proposed_content"],
            answer_id=answer_id,
            actor_id=actor_id,
        )
    if relation in ("SUPPLEMENT", "CONFLICT"):
        target_id = proposal["target_card_id"]
        card = (None if target_id is None else
                await _lock_target_card(conn, store_id=store_id, card_id=int(target_id)))
        if card is None or card["review_status"] == "EXCLUDED":
            raise ValueError("대상 카드가 없거나 제외되었습니다")
        if card["draft_version_id"] is None:
            raise ValueError("대상 카드에 초안이 없습니다")
        # 제안을 만든 뒤 대상 카드가 다른 판으로 공개됐으면 옛 기준의 답으로 되돌리지 않는다
        if card["published_version_id"] != proposal["target_version_id"]:
            raise ValueError("제안 이후 대상 카드의 공개 판이 바뀌었습니다")
        if card["draft_version_id"] != card["published_version_id"]:
            draft = await _read_version(conn, store_id=store_id,
                                        version_id=int(card["draft_version_id"]))
            if not _is_staged_draft(draft, proposal):
                # 점주가 고친 미공개 초안을 덮지 않는다
                raise ValueError("대상 카드에 공개되지 않은 다른 초안이 있습니다")
            # 앞선 승인 시도(STALE·준비 실패)가 얹은 초안을 재사용한다. 판을 더 쌓지 않는다
            return int(card["card_id"]), int(card["draft_version_id"])
        # 공개판 위에 점주 답변 초안을 얹는다. 공개 CAS 는 이 새 초안 기준이다
        version_id = await card_repo.create_draft(
            conn,
            store_id,
            int(card["card_id"]),
            title=proposal["proposed_title"],
            content=proposal["proposed_content"],
            actor_id=actor_id,
            source_version_id=int(card["draft_version_id"]),
        )
        await _mark_owner_answer_version(conn, store_id=store_id, version_id=version_id,
                                         answer_id=answer_id)
        return int(card["card_id"]), int(version_id)
    raise ValueError(f"proposal relation {relation} cannot be approved")


async def _finish_proposal(conn, *, store_id: int, proposal, card_id: int,
                           version_id: int) -> None:
    """발행 트랜잭션 안에서 제안을 PUBLISHED 로 닫고 답변·인용을 카드에 잇는다."""
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
    if proposal["relation_type"] in ("SUPPLEMENT", "CONFLICT"):
        # 같은 카드에 남은 다른 검수 대기 제안이 있으면 사유를 다시 표시한다
        # (publish_cards 가 공개하며 needs_review_reason 을 비웠다)
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
            card_id,
        )
    await _attach_owner_answer_citations(conn, store_id, answer_id, card_id, version_id)


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
    """검수 대기 점주 답변 제안을 점주가 나중에 승인해 공개판에 올린다.

    1. 짧은 트랜잭션: 공개판 → 제안 → 카드 순으로 잠그고 초안을 준비한 뒤 커밋한다.
    2. 연결 없이 옛 색인 임베딩을 준비하고 `publish_cards` 를 부른다.
    3. hook(발행 트랜잭션 안): 제안을 다시 잠가 여전히 승인 가능한지 확인하고
       PUBLISHED 로 닫은 뒤 R 완료 접점(notify_r)을 부른다. 실패하면 발행째 롤백된다.

    NO_PROVENANCE·STALE·PREPARE_FAILED 는 결과를 그대로 돌려주고 제안은 건드리지
    않는다(다시 승인할 수 있다). 점주 답변 출처 공개 플래그가 꺼져 있으면 초안도 만들지
    않고 NO_PROVENANCE 를 돌려준다.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 공개판 행을 먼저 잠가 발행 트랜잭션과 직렬화한다. 그 안의 순서는 제안 → 카드이고
            # 발행 hook 은 카드 → 제안이지만, 둘 다 공개판 잠금 뒤라 서로 엇갈려 기다리지 않는다
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
            if not get_settings().w_owner_answer_raw_publish:
                # 점주 답변 제안의 공개 판은 언제나 점주 답변이 출처다(NEW 는 자료 없는 카드,
                # SUPPLEMENT·CONFLICT 는 owner_answer_id 판). 플래그가 꺼져 있으면 publish_cards 가
                # 반드시 NO_PROVENANCE 로 거절하므로, 초안을 먼저 커밋해 카드에 공개할 수 없는
                # 점주 답변 판을 남기지 않는다 — 카드·제안을 그대로 두고 멈춘다
                return PublishCardsResult(status="NO_PROVENANCE")
            card_id, version_id = await _stage_proposal_card(
                conn, store_id=store_id, proposal=proposal, actor_id=actor_user_id)

    async def hook(conn, snapshot_id: int, knowledge_revision: int) -> None:
        current = await _lock_proposal(conn, store_id=store_id, proposal_id=proposal_id)
        if current is None or current["status"] not in APPROVABLE_PROPOSAL_STATUSES:
            # 준비 사이 다른 경로가 제안을 닫았다. 발행째 롤백한다
            raise ValueError("knowledge proposal changed during publication")
        await _finish_proposal(conn, store_id=store_id, proposal=current,
                               card_id=card_id, version_id=version_id)
        if notify_r is None:
            logger.warning(
                "R 완료 접점 미연결 — 인계 문서 참조 store=%s proposal=%s answer=%s",
                store_id, proposal_id, current["answer_id"])
            return
        await notify_r(conn, int(current["answer_id"]), card_id, version_id,
                       knowledge_revision)

    return await publish_cards(
        pool,
        store_id=store_id,
        member_id=member_id,
        actor_user_id=actor_user_id,
        changes=[CardChange(card_id, version_id, version_id)],
        idempotency_key=f"owner-proposal:{proposal_id}",
        usage_context=usage_context,
        in_transaction=hook,
    )
