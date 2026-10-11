"""카드 승인 → 공개 조정자 `publish_cards` (W, Task 3 / W_CONTRACT_INPUT ③).

**색인 준비는 트랜잭션 밖, 공개 전환은 짧은 트랜잭션 하나.**

  1. 준비: 공개 상태·카드 CAS 를 읽고, manifest 를 만들고, 각 카드 버전이
     사실 블록 카드인지 한 장씩 확인한 뒤 `KnowledgeContent` 를 조립한다. 연결은 여기서 놓는다.
  2. R 색인 준비: 임베딩을 부르므로 **연결을 잡지 않은 채** 호출한다.
  3. 공개: publication 잠금 → 카드 CAS 재확인 → `publish_knowledge` → 카드
     공개 포인터 → `activate_prepared_index` → (선택) 같은 트랜잭션 hook →
     커밋. 어느 단계든 실패하면 전부 롤백된다 — 판만 오르고 색인이 안 바뀐
     상태, 카드만 승인되고 판이 안 오른 상태를 남기지 않는다.

매장 격리는 코드 책임이다 (D1). `store_id` 는 JWT·worker 신뢰 범위에서 온다.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import asyncpg
import pydantic

from app.cards import repository as card_repo
from app.config import get_settings
from app.contracts.common import SCHEMA_PUBLISHED
from app.contracts.hashing import digest, knowledge_content_payload
from app.contracts.publication import IdempotencyKey, PrepareIndexRequest, TrustedScope
from app.learn.approved_renderer import RENDERER_VERSION
from app.publish.content import (
    InvalidContent,
    NoProvenance,
    build_knowledge_content,
    current_manifest,
)
from app.publish.service import _lock_publication, publish_knowledge
from app.reg.index_preparation import activate_prepared_index, prepare_index_request

logger = logging.getLogger(__name__)

# 공개판이 아직 없을 때의 용어집 판. 공개판이 있으면 그 값을 이어 쓴다
DEFAULT_GLOSSARY_VERSION = "glossary/v1"
# R 준비 멱등 키의 시간 창(초). R 준비 TTL 이 지나면 같은 키를 다시 못 쓰므로 창을 나눈다
PREPARE_KEY_WINDOW_SECONDS = 600
# 호출부 멱등 키 상한. R 준비 키(키:판:hash16:창)가 R 상한 80자를 넘지 않게 한다
MAX_IDEMPOTENCY_KEY = 40

InTransactionHook = Callable[[asyncpg.Connection, int, int], Awaitable[None]]
# 색인 준비 직후·공개 트랜잭션 전에 부른다. False 면 공개하지 않는다(점유 연장 실패 등)
AfterPrepareHook = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class CardChange:
    card_id: int
    expected_draft_version_id: int
    target_card_version_id: int


@dataclass(frozen=True)
class PublishCardsResult:
    # PUBLISHED | ALREADY_APPLIED | STALE | PREPARE_FAILED | NO_PROVENANCE
    # | INVALID_CONTENT (변경 카드 원문이 비었거나 너무 길다)
    # | EMPTY_MANIFEST (승인 카드는 있지만 출처 실패로 모두 manifest에서 빠졌다)
    # | LEASE_LOST (after_prepare 가 False — 호출부가 작업 점유를 잃었다. 아무것도 쓰지 않았다)
    status: str
    snapshot_id: int | None = None
    knowledge_revision: int | None = None
    error_code: str | None = None


class _Stale(Exception):
    """트랜잭션 안에서 CAS 가 깨졌다. 부분 쓰기를 남기지 않게 롤백시키는 신호다."""


class _ChangedWithoutProvenance(Exception):
    """승인 대상 카드에 출처가 없다. 블록 고정 트랜잭션을 통째로 롤백시킨다."""


class _ChangedInvalidContent(Exception):
    """승인 대상 카드 원문이 비었거나 너무 길다. 블록 고정 트랜잭션을 통째로 롤백시킨다."""


# ---------------------------------------------------------------------------
# DB 읽기·쓰기 (모두 store_id 필수)
# ---------------------------------------------------------------------------

async def _read_operation(conn, *, store_id: int, member_id: int,
                          idempotency_key: str) -> dict | None:
    """같은 멱등 키로 앞서 들어온 공개 요청. 없으면 None."""
    row = await conn.fetchrow(
        """
        select body_hash, status, response
        from operations
        where store_id = $1 and member_id is not distinct from $2
          and operation = 'PUBLISH' and idempotency_key = $3
        """,
        store_id, member_id, idempotency_key)
    return dict(row) if row is not None else None


async def _read_publication(conn, *, store_id: int) -> dict:
    """(publication_revision, knowledge_revision, current_snapshot_id, glossary_version).

    행이 없으면 아직 한 번도 공개하지 않은 매장이다 — 판 0, 기본 용어집.
    """
    row = await conn.fetchrow(
        """
        select kp.publication_revision, kp.knowledge_revision,
               kp.current_snapshot_id, ks.glossary_version
        from knowledge_publications kp
        left join knowledge_snapshots ks
          on ks.store_id = kp.store_id and ks.snapshot_id = kp.current_snapshot_id
        where kp.store_id = $1
        """,
        store_id)
    if row is None:
        return dict(publication_revision=0, knowledge_revision=0,
                    current_snapshot_id=None,
                    glossary_version=DEFAULT_GLOSSARY_VERSION)
    return dict(publication_revision=row["publication_revision"],
                knowledge_revision=row["knowledge_revision"],
                current_snapshot_id=row["current_snapshot_id"],
                glossary_version=row["glossary_version"] or DEFAULT_GLOSSARY_VERSION)


async def _read_cards(conn, *, store_id: int, card_ids: list[int],
                      for_update: bool) -> dict[int, dict]:
    """카드 상태를 card_id 오름차순으로 읽는다. 잠글 때 순서를 고정해 교착을 막는다."""
    lock = " for update" if for_update else ""
    rows = await conn.fetch(
        f"""
        select card_id, draft_version_id, published_version_id, review_status
        from knowledge_cards
        where store_id = $1 and card_id = any($2::bigint[])
        order by card_id{lock}
        """,
        store_id, sorted(card_ids))
    return {row["card_id"]: dict(row) for row in rows}


def _cas_holds(cards: dict[int, dict], changes: list[CardChange],
               manifest: dict[int, int] | None = None) -> bool:
    """검수자가 본 초안 그대로이고, 그 초안을 공개하며, 제외되지 않았는가.

    `manifest` 를 주면 함께 실릴 카드도 모두 살아 있고 제외되지 않았는지 본다 —
    제외는 판을 올리는 트랜잭션 밖에서 일어나므로 준비 사이 제외된 카드가 새
    공개에 섞일 수 있다. 변경하지 않는 카드는 manifest 를 만든 뒤 공개 포인터가
    그대로(여전히 APPROVED, 같은 `published_version_id`)인지도 본다 — 준비 사이
    레거시 경로가 포인터를 옮겼으면 옛 버전을 싣지 않고 STALE 로 다시 시도한다.
    """
    changed_ids = {change.card_id for change in changes}
    for card_id, version_id in (manifest or {}).items():
        card = cards.get(card_id)
        if card is None or card["review_status"] == "EXCLUDED":
            return False
        if card_id not in changed_ids and (
                card["review_status"] != "APPROVED"
                or card["published_version_id"] != version_id):
            return False
    for change in changes:
        card = cards.get(change.card_id)
        if (card is None
                or card["draft_version_id"] != change.expected_draft_version_id
                or change.target_card_version_id != change.expected_draft_version_id
                or card["review_status"] == "EXCLUDED"):
            return False
    return True


async def _mark_published(conn, *, store_id: int, actor_user_id: int,
                          change: CardChange, card: dict) -> None:
    """카드 공개 포인터를 옮기고 검수 사건을 남긴다. 승인 라우터와 같은 규칙이다."""
    action = (
        "PUBLISH_EDIT"
        if card["published_version_id"] is not None
        and card["published_version_id"] != change.target_card_version_id
        else "APPROVE"
    )
    await conn.execute(
        """
        update knowledge_cards
        set review_status = 'APPROVED', published_version_id = $3,
            excluded_at = null, excluded_by = null, needs_review_reason = null
        where store_id = $1 and card_id = $2
        """,
        store_id, change.card_id, change.target_card_version_id)
    await card_repo.add_event(
        conn, store_id, change.card_id, actor_user_id, action,
        from_status=card["review_status"], to_status="APPROVED",
        metadata={"published_version_id": change.target_card_version_id})


# ---------------------------------------------------------------------------
# hash·요청 조립
# ---------------------------------------------------------------------------

def snapshot_hash_for(content, knowledge_revision: int) -> str:
    """임시 snapshot 을 만들지 않고 `snapshot_digest` 와 같은 값을 계산한다."""
    return digest({"schema_version": SCHEMA_PUBLISHED,
                   "knowledge_revision": str(knowledge_revision),
                   **knowledge_content_payload(content)})


def build_prepare_request(*, store_id: int, member_id: int, idempotency_key: str,
                          content, expected_publication_revision: int) -> PrepareIndexRequest:
    """R 준비 요청. body_hash 는 R 규칙(멱등 필드를 뺀 요청 digest)과 같게 만든다."""
    content_hash = digest(knowledge_content_payload(content))
    hex_part = content_hash.split(":", 1)[1]
    # 같은 공개 키라도 예상 판·내용·시간 창이 다르면 R 준비 키가 달라야 한다
    # (R 은 같은 키에 다른 요청을 거절하고, TTL 이 지난 키는 다시 받지 않는다)
    prepare_key = (f"{idempotency_key}:{expected_publication_revision}:"
                   f"{hex_part[:16]}:"
                   f"{int(time.time() // PREPARE_KEY_WINDOW_SECONDS)}")
    placeholder = IdempotencyKey(key=prepare_key, body_hash="sha256:" + "0" * 64)
    request = PrepareIndexRequest(
        scope=TrustedScope(store_id=str(store_id), member_id=str(member_id)),
        idempotency=placeholder,
        card_ids=tuple(sorted((c.card_id for c in content.cards), key=int)),
        content_hash=content_hash,
        expected_publication_revision=str(expected_publication_revision),
        expected_card_revisions=(),
        embedding_model=get_settings().embedding_model,
        glossary_version=content.glossary_version,
        renderer_version=content.renderer_version,
    )
    body_hash = digest(request.model_dump(mode="json", exclude={"idempotency"}))
    return request.model_copy(update={
        "idempotency": IdempotencyKey(key=prepare_key, body_hash=body_hash)})


# ---------------------------------------------------------------------------
# 준비 단계
# ---------------------------------------------------------------------------

async def _check_cards(conn, *, store_id: int, manifest: dict[int, int],
                       changed_ids: set[int], glossary_version: str) -> dict[int, int]:
    """manifest 의 카드가 사실 블록 카드인지 한 장씩 확인한다.

    카드마다 savepoint 를 두고 그 카드 하나만으로 조립해 본다. **변경하지 않는
    카드**가 어떤 이유로든(사실 블록 아님, 출처 없음, 계약 검증 실패) 실패하면 그
    카드만 manifest 에서 빼고 경고한다 — 낡은 카드 하나 때문에 매장 전체 승인이
    막히지 않게 한다. **승인 대상 카드**가 사실 블록 카드가 아니거나 출처가 없으면
    호출부에 알린다. 그 밖의 예외는 삼키지 않는다.
    """
    kept = dict(manifest)
    async with conn.transaction():
        for card_id, version_id in sorted(manifest.items()):
            try:
                async with conn.transaction():
                    # 한 장만으로 조립해 계약 검증까지 여기서 걸러 둔다
                    await build_knowledge_content(
                        conn, store_id=store_id, manifest={card_id: version_id},
                        glossary_version=glossary_version)
            except (NoProvenance, ValueError) as exc:
                if card_id in changed_ids:
                    if isinstance(exc, NoProvenance):
                        raise _ChangedWithoutProvenance(card_id) from exc
                    if isinstance(exc, (InvalidContent, pydantic.ValidationError)):
                        raise _ChangedInvalidContent(card_id) from exc
                    raise
                logger.warning(
                    "공개할 수 없는 기존 공개 카드를 manifest 에서 뺀다 "
                    "store=%s card=%s version=%s reason=%s",
                    store_id, card_id, version_id, exc)
                kept.pop(card_id)
    return kept


# ---------------------------------------------------------------------------
# 조정자
# ---------------------------------------------------------------------------

async def publish_cards(
    pool, *, store_id: int, member_id: int, actor_user_id: int,
    changes: list[CardChange], idempotency_key: str, usage_context,
    in_transaction: InTransactionHook | None = None,
    after_prepare: AfterPrepareHook | None = None,
    initialize_empty: bool = False,
) -> PublishCardsResult:
    """카드 버전을 공개판으로 올린다. 색인 준비와 공개 전환을 한 묶음으로 닫는다.

    `changes=[]` 는 "현재 공개 포인터 그대로 다시 발행" 이다 — 제외·복원처럼 카드
    공개 포인터는 그대로 두고 실릴 카드 집합만 바뀐 경우에 쓴다. 이때 카드 CAS·
    공개 포인터 이동·검수 사건은 없고, manifest 전체 잠금과 제외 확인, 멱등 키는
    그대로 적용된다. 승인 카드가 없으면 문서 0개의 정상 공개판을 발행한다.

    `after_prepare` 는 R 준비가 PREPARED 로 끝난 직후, 공개 트랜잭션을 열기 전에
    부른다(연결을 잡지 않은 상태). 색인 준비가 길어 worker 점유가 끊겼을 수 있으므로
    여기서 점유를 연장한다. False 면 트랜잭션을 열지 않고 LEASE_LOST 를 돌려준다.
    """
    if member_id is None:
        raise ValueError("색인 준비에는 member_id 가 필요하다")
    if len(idempotency_key) > MAX_IDEMPOTENCY_KEY:
        raise ValueError(f"멱등 키는 {MAX_IDEMPOTENCY_KEY}자 이하다")
    if len({c.card_id for c in changes}) != len(changes):
        raise ValueError("같은 카드가 두 번 실렸다")

    changed_ids = {c.card_id for c in changes}
    body_hash = digest([dataclasses.asdict(c) for c in changes])

    # 0. 재시도 확인 — 이미 커밋된 같은 요청이면 준비·CAS 없이 그 결과를 돌려준다.
    #    판이 오른 뒤라 다시 준비하면 R 이 같은 키를 다른 요청으로 보고 거절한다
    async with pool.acquire() as conn:
        operation = await _read_operation(conn, store_id=store_id, member_id=member_id,
                                          idempotency_key=idempotency_key)
    if operation is not None:
        if operation["body_hash"] != body_hash:
            return PublishCardsResult(status="STALE", error_code="IDEMPOTENCY_CONFLICT")
        if operation["status"] == "SUCCEEDED":
            response = operation["response"]
            if isinstance(response, str):
                response = json.loads(response)
            return PublishCardsResult(status="ALREADY_APPLIED",
                                      snapshot_id=response.get("snapshot_id"),
                                      knowledge_revision=response.get("knowledge_revision"))
        # STARTED 는 앞선 시도가 결과를 못 남긴 것이다. 이어서 진행한다

    # 1. 준비 — 연결은 짧게 잡고 R 호출 전에 놓는다
    async with pool.acquire() as conn:
        publication = await _read_publication(conn, store_id=store_id)
        if changes:
            cards = await _read_cards(conn, store_id=store_id,
                                      card_ids=sorted(changed_ids), for_update=False)
            if not _cas_holds(cards, changes):
                return PublishCardsResult(status="STALE")

        manifest = await current_manifest(conn, store_id=store_id)
        if initialize_empty and (manifest or publication['current_snapshot_id'] is not None or changes):
            return PublishCardsResult(status="STALE")
        had_approved_cards = bool(manifest)
        for change in changes:
            manifest[change.card_id] = change.target_card_version_id

        glossary_version = publication["glossary_version"]
        try:
            manifest = await _check_cards(
                conn, store_id=store_id, manifest=manifest,
                changed_ids=changed_ids,
                glossary_version=glossary_version)
        except _ChangedWithoutProvenance:
            return PublishCardsResult(status="NO_PROVENANCE")
        except _ChangedInvalidContent:
            return PublishCardsResult(status="INVALID_CONTENT")
        if not manifest and had_approved_cards:
            # 출처 실패로 모든 카드를 잃은 상태를 정상적인 빈 공개판으로 숨기지 않는다.
            return PublishCardsResult(status="EMPTY_MANIFEST")

        content = await build_knowledge_content(
            conn, store_id=store_id, manifest=manifest,
            glossary_version=glossary_version)

    expected_publication_revision = publication["publication_revision"]

    # 2. R 색인 준비 — 임베딩을 부르므로 연결을 잡지 않는다
    request = build_prepare_request(
        store_id=store_id, member_id=member_id, idempotency_key=idempotency_key,
        content=content, expected_publication_revision=expected_publication_revision)
    prepared = await prepare_index_request(
        pool, request=request, content=content, usage_context=usage_context)
    if prepared.status != "PREPARED":
        return PublishCardsResult(status="PREPARE_FAILED",
                                  error_code=prepared.error.code)

    # 2-1. 색인 준비 뒤 점유 확인 — 연결을 잡지 않은 채 부른다
    if after_prepare is not None and not await after_prepare():
        return PublishCardsResult(status="LEASE_LOST")

    card_versions = sorted(manifest.items())

    # 3. 공개 — 한 트랜잭션. 예외는 삼키지 않고 밖으로 올려 전부 롤백한다
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                current = await _lock_publication(conn, store_id)
                if initialize_empty and (current['current_snapshot_id'] is not None
                        or await current_manifest(conn, store_id=store_id)):
                    raise _Stale()
                # manifest 전체를 card_id 오름차순으로 잠근다(변경 카드 포함)
                locked = await _read_cards(conn, store_id=store_id,
                                           card_ids=sorted(manifest),
                                           for_update=True)
                if not _cas_holds(locked, changes, manifest=manifest):
                    raise _Stale()

                snapshot_hash = snapshot_hash_for(
                    content, current["knowledge_revision"] + 1)
                outcome = await publish_knowledge(
                    conn, store_id=store_id, member_id=member_id,
                    idempotency_key=idempotency_key, body_hash=body_hash,
                    expected_publication_revision=expected_publication_revision,
                    snapshot_hash=snapshot_hash,
                    glossary_version=glossary_version,
                    renderer_version=RENDERER_VERSION,
                    card_versions=card_versions)
                if outcome.status == "ALREADY_APPLIED":
                    # 앞선 같은 요청이 이미 커밋했다. 아무것도 더 쓰지 않는다
                    return PublishCardsResult(
                        status="ALREADY_APPLIED", snapshot_id=outcome.snapshot_id,
                        knowledge_revision=outcome.knowledge_revision)
                if outcome.status != "PUBLISHED":
                    raise _Stale()

                for change in sorted(changes, key=lambda c: c.card_id):
                    await _mark_published(
                        conn, store_id=store_id, actor_user_id=actor_user_id,
                        change=change, card=locked[change.card_id])

                await activate_prepared_index(
                    conn, store_id=store_id,
                    prepared_id=int(prepared.prepared_id),
                    snapshot_id=outcome.snapshot_id)

                if in_transaction is not None:
                    await in_transaction(conn, outcome.snapshot_id,
                                         outcome.knowledge_revision)
    except _Stale:
        return PublishCardsResult(status="STALE")

    return PublishCardsResult(status="PUBLISHED", snapshot_id=outcome.snapshot_id,
                              knowledge_revision=outcome.knowledge_revision)
