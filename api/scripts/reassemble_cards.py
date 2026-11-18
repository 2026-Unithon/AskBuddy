"""옛 카드 다시 조립(계획 10 Task 13). 저장된 사실로 조립만 다시 해 **초안 판**을 새로 만든다.

공개 판은 그대로다 — 사장님이 다시 공개해야 직원 화면이 바뀐다. 추출은 다시 하지 않는다.
운영 실행은 사용자가 한다. 먼저 --dry-run 으로 대상 수를 확인한다.

  python scripts/reassemble_cards.py --store <id> --dry-run
  python scripts/reassemble_cards.py --store <id>

조립 모델 호출(실행 모드)은 config.py 의 조립 모델을 쓴다. 이 도구는 작업(job) 밖에서 돌기 때문에
원가 장부(ai_usage_attempts)에 영수증을 남기지 않는다 — 호출 로그의 토큰을 따로 기록해야 한다.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest import card_plan, fact_assembly, fact_cards  # noqa: E402
from app.ingest.card_plan import EntityGroup, ProposedCard  # noqa: E402

logger = logging.getLogger(__name__)

PlanCall = Callable[[Sequence[EntityGroup]], Awaitable[Mapping[int, Sequence[ProposedCard]]]]


async def _fact_cards(conn, store_id: int) -> list[tuple[int, int, str | None]]:
    """다시 조립할 카드: 대상이 정해진, 블록 사실이 있는 판을 가진 카드. (card_id, entity_id, 카테고리 이름)."""
    rows = await conn.fetch(
        "select c.card_id, c.entity_id, t.category_name "
        "from knowledge_cards c "
        "left join task_categories t on t.store_id = c.store_id and t.category_id = c.category_id "
        "where c.store_id = $1 and c.entity_id is not null and c.review_status <> 'EXCLUDED' "
        "  and exists (select 1 from card_block_facts f where f.store_id = c.store_id "
        "              and f.card_version_id = coalesce(c.draft_version_id, c.published_version_id)) "
        "order by c.card_id",
        store_id)
    return [(int(r["card_id"]), int(r["entity_id"]), r["category_name"]) for r in rows]


async def reassemble_store(conn, store_id: int, *, plan_call: PlanCall, dry_run: bool) -> dict:
    """매장의 사실 카드마다 조립을 다시 해 초안 판을 만든다. 공개 판 포인터는 건드리지 않는다.

    대상 하나가 카드 한 장으로 나오지 않으면(여러 장·없음) 그 카드는 건너뛴다(skipped_published_only).
    """
    cards = await _fact_cards(conn, store_id)
    out = {"cards": len(cards), "new_drafts": 0, "skipped_published_only": 0}
    if dry_run or not cards:
        return out
    loaded = await fact_assembly.load_entity_groups(conn, store_id, [e for _, e, _ in cards])
    groups = {g.entity_id: g for g in loaded.groups if card_plan.check_group(g) is None}
    proposals = await plan_call([groups[e] for e in sorted(groups)])
    for card_id, entity_id, category in cards:
        group = groups.get(entity_id)
        if group is None:
            out["skipped_published_only"] += 1
            continue
        result = card_plan.plan_entity(group, proposals.get(entity_id, ()))
        if len(result.cards) != 1:
            logger.warning("다시 조립 건너뜀 store=%s card=%s 카드 %d장", store_id, card_id, len(result.cards))
            out["skipped_published_only"] += 1
            continue
        card = result.cards[0]
        facts = {f.fact_revision_id: f for f in group.facts}
        revisions = card.fact_revision_ids()
        async with conn.transaction():
            ctx = await fact_cards._render_context(conn, store_id, revisions, sorted({facts[r].fact_id for r in revisions}))
            rendered = fact_cards._render_one(card, facts, ctx, model_error=result.model_error)
            version_id = await fact_cards.create_extraction_draft(
                conn, store_id, card_id, title=card.title, content=rendered.content,
                confidence=rendered.confidence, entity_id=entity_id)
            await fact_cards._fix_version(conn, store_id, card_id, version_id, card, rendered, ctx, facts,
                                          group.canonical_name)
        out["new_drafts"] += 1
        logger.info("다시 조립 store=%s card=%s 새 초안 판 %s (category=%s)", store_id, card_id, version_id, category)
    return out


async def _model_plan_call(store_id: int, conn) -> PlanCall:
    """실제 조립 모델(설정의 조립 모델)로 부르는 plan_call."""
    categories = [r["category_name"] for r in await conn.fetch(
        "select category_name from task_categories where store_id = $1 order by sort_order, category_id", store_id)]

    async def call(groups: Sequence[EntityGroup]):
        outcome = await fact_assembly.plan_entities(
            source_id=0, groups=list(groups), categories=categories, glossary=[], strict=False)
        return outcome.proposals
    return call


async def _main(argv: list[str]) -> int:
    import asyncpg

    from app.config import get_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    conn = await asyncpg.connect(get_settings().supabase_db_url)
    try:
        plan_call = await _model_plan_call(args.store, conn)
        print(await reassemble_store(conn, args.store, plan_call=plan_call, dry_run=args.dry_run))
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
