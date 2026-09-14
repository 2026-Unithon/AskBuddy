"""발행·제외·자료 삭제의 트랜잭션 서비스 (C0 결정서 §4.2~4.4, CP-04).

**여기서 지키는 것은 "한 번만, 순서대로, 되돌리지 않고" 다.**

  - 발행은 매장 publication 행을 잠그고 예상 판을 확인한 뒤에만 판을 올린다.
    잠그지 않으면 두 요청이 같은 판 번호를 발급받아 둘 중 하나가 사라진다.
  - 같은 멱등 키의 재시도는 원래 응답을 그대로 돌려준다. 판을 올리지 않는다.
  - 자료 삭제는 tombstone 이다. 사실을 지우면 이미 나간 답변의 근거가 사라진다 (D20).

외부 모델 호출을 트랜잭션 안에서 하지 않는다. 임베딩·hash 는 바깥에서 준비하고
여기서는 짧게 잠그고 판단만 한다 (§4.2).

매장 격리는 전부 코드 책임이다 (D1). 모든 함수가 `store_id` 를 필수로 받고,
그 값은 JWT 에서 꺼낸 것이어야 한다 — 요청 본문의 값을 그대로 넘기지 않는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass


class IdempotencyConflict(RuntimeError):
    """같은 키로 다른 본문이 왔다. 조용히 덮지 않는다 (§4.3)."""


class SourceInUse(RuntimeError):
    """승인 지식이 이 자료를 근거로 쓰고 있다. 물리 삭제하지 않는다 (D20)."""


@dataclass
class PublishOutcome:
    status: str                      # PUBLISHED / ALREADY_APPLIED / STALE
    knowledge_revision: int | None = None
    snapshot_id: int | None = None
    publication_revision: int | None = None


async def claim_operation(
    conn, *, store_id: int, member_id: int | None, operation: str,
    idempotency_key: str, body_hash: str,
) -> tuple[int, dict | None]:
    """(operation_id, 이미 끝난 응답).

    응답이 돌아오면 **업무를 다시 하지 않는다.** 그대로 내보낸다.
    """
    row = await conn.fetchrow(
        """
        select operation_id, body_hash, status, response
        from operations
        where store_id = $1 and member_id is not distinct from $2
          and operation = $3 and idempotency_key = $4
        """,
        store_id, member_id, operation, idempotency_key)

    if row is not None:
        if row["body_hash"] != body_hash:
            raise IdempotencyConflict(
                f"같은 멱등 키에 다른 본문이다: {operation}/{idempotency_key}")
        if row["status"] == "SUCCEEDED":
            return row["operation_id"], json.loads(row["response"])
        # STARTED 로 남은 것은 앞선 시도가 결과를 못 남긴 경우다. 이어서 진행한다
        return row["operation_id"], None

    operation_id = await conn.fetchval(
        """
        insert into operations (store_id, member_id, operation,
                                idempotency_key, body_hash)
        values ($1, $2, $3, $4, $5)
        returning operation_id
        """,
        store_id, member_id, operation, idempotency_key, body_hash)
    return operation_id, None


async def finish_operation(conn, operation_id: int, response: dict) -> None:
    await conn.execute(
        """
        update operations
           set status = 'SUCCEEDED', response = $2::jsonb, finished_at = now()
         where operation_id = $1
        """,
        operation_id, json.dumps(response, ensure_ascii=False))


async def _lock_publication(conn, store_id: int):
    """매장의 공개 상태를 잠근다. 잠금 순서는 publication → card → session (§4.2)."""
    await conn.execute(
        """
        insert into knowledge_publications (store_id) values ($1)
        on conflict (store_id) do nothing
        """, store_id)
    return await conn.fetchrow(
        """
        select publication_revision, knowledge_revision
        from knowledge_publications where store_id = $1 for update
        """, store_id)


async def publish_knowledge(
    conn, *, store_id: int, member_id: int | None, idempotency_key: str,
    body_hash: str, expected_publication_revision: int,
    snapshot_hash: str, glossary_version: str, renderer_version: str,
    card_versions: list[tuple[int, int]] | None = None,
) -> PublishOutcome:
    """한 트랜잭션에서 판을 올리고 snapshot·공개 포인터·사건을 함께 남긴다.

    호출부가 트랜잭션을 열어 준다 — 사건만 따로 커밋되면 소비자가 아직 없는 판을
    보러 온다.
    """
    operation_id, replay = await claim_operation(
        conn, store_id=store_id, member_id=member_id, operation="PUBLISH",
        idempotency_key=idempotency_key, body_hash=body_hash)
    if replay is not None:
        return PublishOutcome(status="ALREADY_APPLIED", **replay)

    current = await _lock_publication(conn, store_id)
    if current["publication_revision"] != expected_publication_revision:
        # 그 사이 다른 변경이 있었다. 덮어쓰지 않고 되돌려보낸다
        return PublishOutcome(status="STALE",
                              publication_revision=current["publication_revision"])

    knowledge_revision = current["knowledge_revision"] + 1
    snapshot_id = await conn.fetchval(
        """
        insert into knowledge_snapshots (store_id, knowledge_revision,
                                         snapshot_hash, glossary_version,
                                         renderer_version)
        values ($1, $2, $3, $4, $5)
        returning snapshot_id
        """,
        store_id, knowledge_revision, snapshot_hash, glossary_version,
        renderer_version)

    for card_id, card_version_id in (card_versions or []):
        await conn.execute(
            """
            insert into snapshot_card_versions
                (store_id, snapshot_id, card_id, card_version_id)
            values ($1, $2, $3, $4)
            """, store_id, snapshot_id, card_id, card_version_id)

    await conn.execute(
        """
        update knowledge_publications
           set publication_revision = publication_revision + 1,
               knowledge_revision = $2,
               current_snapshot_id = $3,
               updated_at = now()
         where store_id = $1
        """, store_id, knowledge_revision, snapshot_id)

    await _emit(conn, store_id, "KNOWLEDGE_PUBLISHED", snapshot_id,
                knowledge_revision=knowledge_revision)

    payload = dict(knowledge_revision=knowledge_revision, snapshot_id=snapshot_id,
                   publication_revision=expected_publication_revision + 1)
    await finish_operation(conn, operation_id, payload)
    return PublishOutcome(status="PUBLISHED", **payload)


async def set_card_visibility(
    conn, *, store_id: int, member_id: int | None, idempotency_key: str,
    body_hash: str, card_id: int, exclude: bool,
    expected_publication_revision: int, reason: str | None = None,
) -> PublishOutcome:
    """카드 제외·복원. 보이는 지식이 달라지므로 판 번호도 오른다 (§4.2)."""
    if exclude and not reason:
        raise ValueError("제외에는 사유가 필요하다. 나중에 왜 빠졌는지 답해야 한다")

    operation_id, replay = await claim_operation(
        conn, store_id=store_id, member_id=member_id, operation="VISIBILITY",
        idempotency_key=idempotency_key, body_hash=body_hash)
    if replay is not None:
        return PublishOutcome(status="ALREADY_APPLIED", **replay)

    current = await _lock_publication(conn, store_id)
    if current["publication_revision"] != expected_publication_revision:
        return PublishOutcome(status="STALE",
                              publication_revision=current["publication_revision"])

    knowledge_revision = current["knowledge_revision"] + 1
    await conn.execute(
        """
        update knowledge_cards
           set status = $3, updated_at = now()
         where store_id = $1 and card_id = $2
        """, store_id, card_id, "EXCLUDED" if exclude else "APPROVED")
    await conn.execute(
        """
        update knowledge_publications
           set publication_revision = publication_revision + 1,
               knowledge_revision = $2, updated_at = now()
         where store_id = $1
        """, store_id, knowledge_revision)
    await _emit(conn, store_id,
                "CARD_EXCLUDED" if exclude else "CARD_RESTORED", card_id,
                knowledge_revision=knowledge_revision)

    payload = dict(knowledge_revision=knowledge_revision, snapshot_id=None,
                   publication_revision=expected_publication_revision + 1)
    await finish_operation(conn, operation_id, payload)
    return PublishOutcome(status="PUBLISHED", **payload)


async def delete_source(conn, *, store_id: int, source_id: int) -> str:
    """자료를 tombstone 으로 남긴다 (D20).

    사실·카드·인용을 지우지 않는다. 이미 나간 답변의 근거를 없애면 "그때 왜
    그렇게 답했나" 에 답할 수 없다. 인용 칩에는 끊김만 표시된다.
    """
    updated = await conn.execute(
        """
        update sources
           set source_availability = 'DELETED', deleted_at = now()
         where store_id = $1 and source_id = $2
           and source_availability <> 'DELETED'
        """, store_id, source_id)
    return "ALREADY_DELETED" if updated.endswith(" 0") else "DELETED"


async def purge_source(conn, *, store_id: int, source_id: int) -> None:
    """물리 삭제. 근거로 쓰이는 자료는 지우지 못한다.

    개인정보 삭제 요청은 이 경로가 아니라 별도 운영 절차로 처리한다 (§4.4).
    """
    in_use = await conn.fetchval(
        """
        select count(*) from source_facts
         where store_id = $1 and source_id = $2
        """, store_id, source_id)
    if in_use:
        raise SourceInUse(
            f"자료 {source_id} 를 근거로 하는 사실이 {in_use}건 있다. tombstone 으로 남긴다")
    await conn.execute(
        "delete from sources where store_id = $1 and source_id = $2",
        store_id, source_id)


async def _emit(conn, store_id: int, event_type: str, aggregate_id: int, *,
                knowledge_revision: int | None = None,
                owner_answer_id: int | None = None) -> None:
    await conn.execute(
        """
        insert into outbox_events (store_id, event_type, aggregate_id,
                                   knowledge_revision, owner_answer_id)
        values ($1, $2, $3, $4, $5)
        on conflict do nothing
        """, store_id, event_type, aggregate_id, knowledge_revision,
        owner_answer_id)
