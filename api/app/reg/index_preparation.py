"""R PrepareIndex 구현. 공개·최종 revision 발급은 W의 같은 transaction이 소유한다."""
from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from uuid import uuid4

from app.config import get_settings
from app.contracts.errors import ErrorDetail, ERROR_TABLE
from app.contracts.hashing import digest, knowledge_content_payload, snapshot_digest
from app.contracts.publication import PrepareIndexResult
from app.contracts.snapshot import KnowledgeContent, PublishedKnowledgeSnapshot
from app.contracts.usage import UsageContext
from app.errors import ApiError
from app.reg.lexicon import load_lexicon
from app.reg.embeddings import recorded_embeddings, vector_literal
from app.usage import DbUsageSink

INDEX_CONFIG_VERSION = "r-block-index/v1"


@dataclass(frozen=True)
class IndexDocument:
    card_id: str
    card_version_id: str
    block_id: str
    approved_text: str
    retrieval_text: str


def documents(content: KnowledgeContent) -> tuple[IndexDocument, ...]:
    """승인 원문과 검색 문맥을 분리한다. 검색 문자열은 답변 원문으로 쓰지 않는다."""
    result = []
    for card in sorted(content.cards, key=lambda c: int(c.card_id)):
        for block in sorted(card.blocks, key=lambda b: b.order):
            if block.raw_span_id:
                text = next(r.text for r in content.raw_spans if r.raw_span_id == block.raw_span_id)
                context = []
            else:
                facts = [content.fact(fid) for fid in block.fact_revision_ids]
                if any(f.entity_id != card.entity_id for f in facts):
                    raise ValueError("fact/card entity mismatch")
                text = "\n".join(part for fact in facts
                                 for part in (fact.assertion, *fact.conditions, *fact.exceptions))
                context = [" ".join(v for v in (f.subject, f.predicate, f.variant.temperature,
                                               f.variant.size) if v) for f in facts]
            result.append(IndexDocument(card.card_id, card.card_version_id, block.block_id,
                                        text, "\n".join((card.title, *context, text))))
    return tuple(result)


def _failed(code: str, key: str) -> PrepareIndexResult:
    return PrepareIndexResult(status="FAILED", error=ErrorDetail(code=code,
        message="색인 준비를 완료하지 못했습니다. 현재 상태를 확인해 주세요.",
        request_id=key, retryable=ERROR_TABLE[code][1]))


def _prepared(row) -> PrepareIndexResult:
    return PrepareIndexResult(status="PREPARED", prepared_id=str(row["prepared_id"]),
        payload_hash=row["content_hash"], index_config_version=row["index_config_version"],
        expires_at=row["expires_at"])


async def prepare_index(pool, *, store_id: int, member_id: int, idempotency_key: str,
                        expected_publication_revision: int, content: KnowledgeContent,
                        usage_context: UsageContext, embedder=None) -> PrepareIndexResult:
    """신뢰된 W 승인 preview를 준비한다. HTTP payload/LLM에 직접 연결하지 않는다.

    crash 뒤 lease가 지난 같은 키는 새 attempt로 복구한다. TTL 지난 준비는 새 키가 필요하다.
    publish 권한·draft/card CAS는 준비 성공과 별개로 W 공개 transaction에서 검사한다.
    """
    content = KnowledgeContent.model_validate(content.model_dump(mode="json"))
    if len(content.model_dump_json().encode("utf-8")) > 10 * 1024 * 1024:
        raise ValueError("index content exceeds 10 MiB")
    if (content.store_id != str(store_id) or usage_context.store_id != str(store_id)
            or usage_context.stage != "EMBED" or not 8 <= len(idempotency_key) <= 80
            or type(expected_publication_revision) is not int or expected_publication_revision < 0):
        raise ValueError("invalid trusted index preparation scope")
    settings = get_settings()
    if settings.embedding_dim != 1536:
        raise ValueError("r-block-index/v1 requires 1536 dimensions")
    model = settings.embedding_model
    content_hash = digest(knowledge_content_payload(content))
    request_hash = digest(dict(content_hash=content_hash, model=model, config=INDEX_CONFIG_VERSION,
                               expected_publication_revision=expected_publication_revision))
    docs = documents(content)
    claim = uuid4()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("select pg_advisory_xact_lock(hashtextextended($1,0))",
                               f"r:prepare:{store_id}:{member_id}:{idempotency_key}")
            member = await conn.fetchval("select member_id from store_members where store_id=$1 and member_id=$2",
                                        store_id, member_id)
            if member is None:
                return _failed("INVALID_REFERENCE", idempotency_key)
            try:await load_lexicon(conn,store_id=store_id,version=content.glossary_version)
            except ApiError:return _failed('INVALID_REFERENCE',idempotency_key)
            row = await conn.fetchrow("""select *, clock_timestamp() as checked_at from r_index_preparations
                where store_id=$1 and member_id=$2 and idempotency_key=$3 for update""",
                store_id, member_id, idempotency_key)
            if row:
                if row["request_hash"] != request_hash:
                    return _failed("IDEMPOTENCY_CONFLICT", idempotency_key)
                if row["expires_at"] <= row["checked_at"]:
                    return _failed("INDEX_PREPARE_TIMEOUT", idempotency_key)
                if row["state"] in ("PREPARED", "CONSUMED"):
                    return _prepared(row)
                if row["state"] == "FAILED":
                    return _failed(row["error_code"], idempotency_key)
                if row["lease_expires_at"] > row["checked_at"]:
                    return _failed("INDEX_PREPARE_FAILED", idempotency_key)
            revision = await conn.fetchval("select publication_revision from knowledge_publications where store_id=$1",
                                           store_id)
            if (revision or 0) != expected_publication_revision:
                return _failed("STALE_PUBLICATION", idempotency_key)
            if row:
                row = await conn.fetchrow("""update r_index_preparations set claim_id=$3,
                    attempt_no=attempt_no+1, lease_expires_at=clock_timestamp()+interval '45 seconds'
                    where store_id=$1 and prepared_id=$2 returning *""", store_id, row["prepared_id"], claim)
            else:
                row = await conn.fetchrow("""insert into r_index_preparations(store_id,member_id,idempotency_key,
                    request_hash,content_hash,content,expected_publication_revision,embedding_model,index_config_version,
                    state,claim_id,lease_expires_at,expires_at)
                    values($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,'PREPARING',$10,
                           clock_timestamp()+interval '45 seconds',clock_timestamp()+interval '15 minutes') returning *""",
                    store_id,member_id,idempotency_key,request_hash,content_hash,content.model_dump_json(),
                    expected_publication_revision,model,INDEX_CONFIG_VERSION,claim)
    prepared_id = row["prepared_id"]
    context = usage_context.model_copy(update=dict(operation_id=f"index:{prepared_id}",
        logical_call_id=f"index:{prepared_id}:embed", attempt_no=row["attempt_no"]))
    try:
        vectors = await asyncio.wait_for((embedder or recorded_embeddings)(
            [d.retrieval_text for d in docs], context=context, sink=DbUsageSink(pool)), timeout=30)
        if len(vectors) != len(docs) or any(len(v) != 1536 or any(
                type(x) not in (int,float) or not math.isfinite(x) for x in v)
                or not any(x != 0 for x in v) for v in vectors):
            raise ValueError("invalid embedding response")
    except Exception as exc:
        code = "INDEX_PREPARE_TIMEOUT" if isinstance(exc, TimeoutError) else "INDEX_PREPARE_FAILED"
        async with pool.acquire() as conn:
            await conn.execute("""update r_index_preparations set state='FAILED',error_code=$4
                where store_id=$1 and prepared_id=$2 and claim_id=$3 and state='PREPARING'""",
                store_id, prepared_id, claim, code)
        return _failed(code, idempotency_key)
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""select *, clock_timestamp() as checked_at from r_index_preparations
                where store_id=$1 and prepared_id=$2 for update""",store_id,prepared_id)
            if row["claim_id"] != claim or row["state"] != "PREPARING" or row["expires_at"] <= row["checked_at"]:
                return _failed("INDEX_PREPARE_TIMEOUT",idempotency_key)
            for doc, vector in zip(docs,vectors):
                await conn.execute("""insert into r_index_documents(store_id,prepared_id,card_id,card_version_id,
                    block_id,approved_text,retrieval_text,embedding) values($1,$2,$3,$4,$5,$6,$7,$8::vector)""",
                    store_id,prepared_id,int(doc.card_id),int(doc.card_version_id),doc.block_id,
                    doc.approved_text,doc.retrieval_text,vector_literal(vector))
            row = await conn.fetchrow("""update r_index_preparations set state='PREPARED'
                where store_id=$1 and prepared_id=$2 returning *""",store_id,prepared_id)
    return _prepared(row)


async def activate_prepared_index(conn, *, store_id: int, prepared_id: int, snapshot_id: int):
    """W가 공개 포인터를 전환하는 바로 그 transaction 안에서 호출한다.

    공개 카드/draft 승인 CAS는 W가 수행한다. 여기서는 준비 내용과 발행 manifest 동일성을
    확인한다. 준비 성공만으로 이 함수를 호출하거나 별도 commit하지 않는다.
    """
    if not conn.is_in_transaction():
        raise RuntimeError("activation requires publication transaction")
    publication = await conn.fetchrow("select * from knowledge_publications where store_id=$1 for update",store_id)
    row = await conn.fetchrow("""select *,clock_timestamp() as checked_at from r_index_preparations
        where store_id=$1 and prepared_id=$2 for update""",store_id,prepared_id)
    snapshot = await conn.fetchrow("select * from knowledge_snapshots where store_id=$1 and snapshot_id=$2",
                                   store_id,snapshot_id)
    if (not row or not snapshot or not publication or publication["current_snapshot_id"] != snapshot_id
            or publication["knowledge_revision"] != snapshot["knowledge_revision"]):
        raise ApiError(409,"STALE_KNOWLEDGE","현재 공개 준비 상태가 다릅니다.",retryable=True)
    if row["state"] == "CONSUMED":
        existing = await conn.fetchval("""select snapshot_id from r_index_publications
            where store_id=$1 and prepared_id=$2""",store_id,prepared_id)
        if existing == snapshot_id:
            return
    if (row["state"] != "PREPARED" or row["expires_at"] <= row["checked_at"]
            or publication["publication_revision"] != row["expected_publication_revision"]+1):
        raise ApiError(409,"STALE_KNOWLEDGE","색인 준비가 만료되거나 변경됐습니다.",retryable=True)
    payload = json.loads(row["content"]) if isinstance(row["content"],str) else row["content"]
    content = KnowledgeContent.model_validate(payload)
    bound = PublishedKnowledgeSnapshot(**content.model_dump(), snapshot_id=str(snapshot_id),
        knowledge_revision=str(snapshot["knowledge_revision"]),created_at=snapshot["created_at"],
        snapshot_hash=snapshot["snapshot_hash"])
    versions = await conn.fetch("select card_id,card_version_id from snapshot_card_versions where store_id=$1 and snapshot_id=$2",
                                store_id,snapshot_id)
    if (snapshot_digest(bound) != snapshot["snapshot_hash"]
            or content.glossary_version != snapshot["glossary_version"]
            or content.renderer_version != snapshot["renderer_version"]
            or {(int(c.card_id),int(c.card_version_id)) for c in content.cards}
                != {(r["card_id"],r["card_version_id"]) for r in versions}):
        raise ApiError(409,"HASH_MISMATCH","발행 내용과 준비한 색인이 다릅니다.")
    await conn.execute("insert into r_index_publications(store_id,snapshot_id,prepared_id) values($1,$2,$3)",
                       store_id,snapshot_id,prepared_id)
    await conn.execute("update r_index_preparations set state='CONSUMED' where store_id=$1 and prepared_id=$2",
                       store_id,prepared_id)
