"""검토된 점주 답변 제안을 카드로 공개하는 원자 작업."""
from __future__ import annotations

import json

import asyncpg

from app.ingest.embed import embed_card, prepare_embedding


async def prepare_proposal(db, store_id: int, proposal_id: int):
    proposal = await db.fetchrow(
        "select * from knowledge_change_proposals where store_id = $1 and proposal_id = $2",
        store_id, proposal_id)
    if proposal is None:
        raise LookupError("knowledge proposal not found")
    if proposal["status"] not in ("ANALYZED", "PENDING_REVIEW", "FAILED"):
        raise ValueError("proposal cannot be published")
    prepared = await prepare_embedding(store_id, proposal["proposed_title"],
                                       proposal["proposed_content"], cost_phase="OPERATING")
    return dict(proposal), prepared


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
    expected, prepared = preparation
    if dict(proposal) != expected:
        raise ValueError("knowledge proposal changed during embedding")
    if proposal["relation_type"] != "NEW":
        raise ValueError("proposal is not NEW")
    if proposal["status"] not in ("ANALYZED", "PENDING_REVIEW", "FAILED"):
        raise ValueError("proposal cannot be published")

    category_id = await db.fetchval(
        """
        select category_id from task_categories
        where store_id = $1 and category_id = $2
          and deleted_at is null and is_enabled = true
        """,
        store_id,
        proposal["category_id"],
    )
    if category_id is None:
        category_id = await db.fetchval(
            """
            select category_id from task_categories
            where store_id = $1 and is_system = true
              and deleted_at is null and is_enabled = true
            """,
            store_id,
        )
    if category_id is None:
        raise ValueError("system Other category is missing")

    card_id = int(
        await db.fetchval(
            """
            insert into knowledge_cards (
              store_id, category_id, source_id, title, content,
              confidence, is_verified, assignment_type
            ) values ($1, $2, null, $3, $4, 100.00, true, 'AUTOMATIC')
            returning card_id
            """,
            store_id,
            category_id,
            proposal["proposed_title"],
            proposal["proposed_content"],
        )
    )
    card = await db.fetchrow(
        """
        select draft_version_id, published_version_id
        from knowledge_cards where store_id = $1 and card_id = $2
        """,
        store_id,
        card_id,
    )
    version_id = int(card["published_version_id"])
    await db.execute(
        """
        update card_versions
        set change_source = 'OWNER_ANSWER', created_by = $3
        where store_id = $1 and version_id = $2
        """,
        store_id,
        version_id,
        actor_id,
    )
    await embed_card(db, store_id, card_id, prepared=prepared)
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
    expected, prepared = preparation
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
              change_source, created_by
            )
            select $1, $2, coalesce(max(version_no), 0) + 1,
                   $3, $4, 'OWNER_ANSWER', $5
            from card_versions where store_id = $1 and card_id = $2
            returning version_id
            """,
            store_id,
            card_id,
            proposal["proposed_title"],
            proposal["proposed_content"],
            actor_id,
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
    await embed_card(db, store_id, card_id, prepared=prepared)
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
