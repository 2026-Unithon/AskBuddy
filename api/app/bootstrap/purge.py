"""매장 파기(D22). 사장님 탈퇴 유예가 지난 매장의 모든 행을 지운다.

불변 트리거는 `askbuddy_purging(store_id)` 가 참일 때만 비켜 준다. 참이 되려면
이 트랜잭션이 `askbuddy.purge_store_id` 를 그 매장으로 설정했고, 그 매장의 `purge_due_at` 이
지나 있어야 한다. 원가 장부(ai_usage_attempts, cost_assessments)와 비운 stores 행만 남는다.
"""
from __future__ import annotations

import logging
from collections import defaultdict

import asyncpg

from app.config import get_settings
from app.ingest.preprocess import storage

logger = logging.getLogger(__name__)

# 지우지 않는 표. stores 는 비우기만 한다(장부가 RESTRICT FK 로 가리킨다)
KEEP: frozenset[str] = frozenset({"stores", "ai_usage_attempts", "cost_assessments"})

# 매장이 아니라 사용자 단위 표. 다른 매장에 속하지 않은 사용자만 users 행째 지운다(cascade)
USER_SCOPED: frozenset[str] = frozenset({"users", "auth_refresh_tokens", "user_identities", "push_subscriptions"})

# store_id 가 없는 표 → 그 표를 CASCADE 로 지워 주는 부모
VIA_CASCADE: dict[str, str] = {
    "chat_messages": "chat_sessions", "facts": "knowledge_cards", "learning_progress": "roadmap_stages",
    "message_citations": "knowledge_cards", "pending_question_occurrences": "pending_questions",
    "roadmap_items": "roadmap_stages", "source_frames": "sources", "source_kakao": "sources",
    "source_scan": "sources", "source_video": "sources", "source_voice": "sources",
}

# 자식이 부모보다 먼저 지워지는 순서(RESTRICT/NO ACTION FK). 표가 늘면 test_every_table_is_classified 가 멈춘다
PURGE_ORDER: tuple[str, ...] = (
    "user_feedback", "access_logs", "card_embeddings", "card_evidence", "card_fact_edits", "card_facts", "card_review_events",
    "card_version_fact_provenance", "checklist_card_shifts", "checklist_cards", "checklist_check_events",
    "checklist_checks", "checklist_submissions", "evaluation_results", "extraction_raw_responses",
    "extraction_results", "fact_conflicts", "fact_rejections", "fact_revision_meta", "fact_revision_requires",
    "ingest_job_sources", "intake_route_decisions", "invite_codes", "knowledge_change_proposals",
    "knowledge_entity_aliases", "knowledge_entity_candidates", "knowledge_entity_events", "knowledge_publications",
    "member_shifts", "notification_deliveries", "notification_events", "operations", "outbox_consumptions",
    "outbox_cursors", "outbox_events", "outbox_leases", "owner_answer_attachments", "owner_answer_sources",
    "owner_ui_state", "quality_evaluations", "r_answer_citations", "r_evaluation_reservations",
    "r_failed_user_turns", "r_index_documents", "r_index_publications", "r_owner_answer_deliveries",
    "r_owner_knowledge_states", "r_question_contexts", "r_request_leases", "r_search_lexicons",
    "reclassification_jobs", "reclassification_results", "roadmap_stages", "snapshot_card_versions",
    "source_fact_occurrences", "source_fact_revision_links", "source_facts", "store_glossary",
    "store_join_requests", "store_shifts", "today_task_targets", "today_tasks", "upload_change_proposal_facts",
    "upload_change_proposals", "card_block_facts", "card_version_blocks", "evaluation_cases", "evaluation_runs",
    "extraction_runs", "fact_occurrences", "fact_owner_answer_links", "ingest_jobs", "knowledge_cards",
    "r_answer_receipts", "r_evaluation_budgets", "r_index_preparations", "r_owner_answer_revisions",
    "task_categories", "card_versions", "chat_sessions", "knowledge_facts", "knowledge_snapshots", "raw_spans",
    "owner_answers", "pending_questions", "store_members", "fact_revisions", "knowledge_entities", "sources",
)


class PurgeNotDue(Exception):
    """매장이 없거나, 이미 파기됐거나, 유예 기한이 지나지 않았다."""


async def purge_store(conn: asyncpg.Connection, *, store_id: int) -> list[int]:
    """기한이 지난 매장 하나를 한 트랜잭션에서 비운다. 지운 사용자 번호를 돌려준다.

    Storage 파일은 지우지 않는다. 파일 경로가 이 행들에 있으므로 호출자(purge_due_stores)가 먼저 지운다.
    """
    async with conn.transaction():
        # 트랜잭션 안에서만 유효(is_local=true). 기한 확인은 askbuddy_purging 이 DB 에서 다시 한다
        await conn.execute("select set_config('askbuddy.purge_store_id', $1::text, true)", str(store_id))
        due = await conn.fetchrow(
            "select purge_due_at, purge_due_at <= now() as passed from stores "
            "where store_id = $1 and deleted_at is null for update",
            store_id)
        if due is None or due["purge_due_at"] is None or not due["passed"]:
            raise PurgeNotDue(store_id)
        members = [int(r["user_id"]) for r in await conn.fetch(
            "select user_id from store_members where store_id = $1", store_id)]
        for table in PURGE_ORDER:
            if table == "owner_answers":
                # owner_answers 에는 store_id 가 없다. 질문을 거쳐 이 매장 것만 고른다
                await conn.execute(
                    "delete from owner_answers where question_id in "
                    "(select question_id from pending_questions where store_id = $1)", store_id)
            else:
                # 표 이름은 위 상수에서만 온다
                await conn.execute(f"delete from {table} where store_id = $1", store_id)
        await conn.execute(
            "update stores set owner_id = null, store_name = '삭제된 매장', store_slug = null, deleted_at = now() "
            "where store_id = $1", store_id)
        # store-isolation-ok: 사용자는 매장 밖 단위다. 다른 매장 소속을 확인하고 지운다
        removed = await conn.fetch(
            "delete from users u where u.user_id = any($1::bigint[]) "
            "  and not exists (select 1 from store_members m where m.user_id = u.user_id) "
            "  and not exists (select 1 from stores s where s.owner_id = u.user_id) "
            "returning u.user_id",
            members)
    return sorted(int(r["user_id"]) for r in removed)


async def _store_files(conn: asyncpg.Connection, store_id: int) -> dict[str, list[str]]:
    """이 매장이 Storage 에 남긴 파일(자료 원본, 이 매장에만 속한 사람의 사진)을 버킷별로."""
    urls = [r["file_url"] for r in await conn.fetch(
        "select file_url from sources where store_id = $1 and file_url is not null", store_id)]
    urls += [r["avatar_path"] for r in await conn.fetch(
        "select u.avatar_path from store_members m join users u on u.user_id = m.user_id "
        "where m.store_id = $1 and u.avatar_path is not null "
        "  and not exists (select 1 from store_members o where o.user_id = m.user_id and o.store_id <> $1)",
        store_id)]
    supabase_url = get_settings().supabase_url
    by_bucket: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        # 우리 Storage 가 아닌 주소는 지울 파일이 없다. 그 때문에 파기가 막히지 않게 건너뛴다
        if url.startswith(("http://", "https://")) and not (supabase_url and url.startswith(supabase_url)):
            continue
        bucket, path = storage.split_object_path(url)
        by_bucket[bucket].append(path)
    return dict(by_bucket)


async def purge_due_stores(pool: asyncpg.Pool, *, delete_objects=None) -> list[int]:
    """기한이 지난 매장마다 파일 삭제 → purge_store. 지운 매장 번호를 돌려준다.

    파일을 먼저 지운다(DB 를 먼저 지우면 파일 경로를 잃는다). 파일 삭제가 실패하면 그 매장의 DB 는
    손대지 않고 다음 매장으로 간다. 다음 번에 처음부터 다시 한다(파일 삭제는 여러 번 해도 같다).
    """
    delete_objects = delete_objects or storage.delete_objects
    async with pool.acquire() as conn:
        # store-isolation-ok: 기한이 지난 매장을 찾는 운영 작업
        due = [int(r["store_id"]) for r in await conn.fetch(
            "select store_id from stores where purge_due_at <= now() and deleted_at is null order by store_id")]
    purged: list[int] = []
    for store_id in due:
        try:
            async with pool.acquire() as conn:
                files = await _store_files(conn, store_id)
                for bucket, paths in sorted(files.items()):
                    await delete_objects(bucket, paths)
                await purge_store(conn, store_id=store_id)
        except Exception as exc:  # noqa: BLE001 — 한 매장 실패가 다른 매장 파기를 막지 않는다
            # 예외 본문에는 경로·이름이 섞일 수 있어 종류만 남긴다
            logger.warning("store purge failed store=%s error=%s", store_id, type(exc).__name__)
            continue
        purged.append(store_id)
    return purged
