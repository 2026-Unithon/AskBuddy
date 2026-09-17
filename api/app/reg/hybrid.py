"""현재 공개된 불변 색인의 lexical/vector 독립 회수. 순위는 답변 허가가 아니다."""
from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass

from app.contracts.hashing import verify_snapshot_hash
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.errors import ApiError
from app.reg.embeddings import vector_literal
from app.reg.lexicon import load_lexicon,matched_terms
from app.reg.index_audit import audit_index_universe, IndexUniverseMismatch

NORMALIZATION_VERSION = "r-query-nfkc/v1"
RRF_VERSION = "rrf-k60/v1"
LEXICAL_QUERY_VERSION = 'r-lexical-or/v1'


def normalize_query(question: str) -> str:
    return " ".join(unicodedata.normalize("NFKC",question).casefold().split())


def lexical_query(question:str) -> str:
    """질문 전체 AND로 회수 0이 되지 않도록 검색용 토큰만 OR 확장한다.

    조사 제거는 후보 회수용 변형일 뿐이다. 이 문자열로 질문의 사실/규격을 확정하지 않는다.
    """
    tokens=re.findall(r'[가-힣a-z]+|[0-9]+(?:\.[0-9]+)?',normalize_query(question))[:32]
    expanded=[]
    for token in tokens:
        expanded.append(token)
        for suffix in ('에서는','으로는','에서','으로','에게','은','는','이','가','을','를','에','의'):
            if token.endswith(suffix) and len(token)>len(suffix):
                expanded.append(token[:-len(suffix)])
                break
    # 인용부호로 OR 등 사용자 토큰을 연산자가 아닌 낱말로 둔다.
    return ' OR '.join('"'+token+'"' for token in dict.fromkeys(expanded))


@dataclass(frozen=True)
class Candidate:
    card_id: str
    card_version_id: str
    block_id: str
    lexical_score: float | None
    vector_score: float | None
    rrf_score: float


@dataclass(frozen=True)
class SearchResult:
    snapshot: PublishedKnowledgeSnapshot
    index_revision: int
    candidates: tuple[Candidate,...]
    normalized_query: str
    rerank_status: str = 'NOT_CALLED'
    alias_terms: tuple[str,...] = ()


def fuse(lexical, vector, *, limit: int) -> tuple[Candidate,...]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("candidate limit must be 1..100")
    rows = {}
    for channel, ranked in (("lexical",lexical),("vector",vector)):
        seen = set()
        for rank, row in enumerate(ranked,1):
            key = (str(row["card_id"]),str(row["card_version_id"]),row["block_id"])
            if key in seen:
                raise ValueError("duplicate candidate within channel")
            seen.add(key)
            score = float(row["score"])
            if not math.isfinite(score):
                raise ValueError("non-finite candidate score")
            result = rows.setdefault(key,dict(lexical_score=None,vector_score=None,rrf_score=0.0))
            result[channel+"_score"] = score
            result["rrf_score"] += 1/(60+rank)
    ranked = sorted(rows,key=lambda k:(-rows[k]["rrf_score"],int(k[0]),int(k[1]),k[2]))
    return tuple(Candidate(*key,**rows[key]) for key in ranked[:limit])


async def read_current_index(conn, *, store_id: int):
    row = await conn.fetchrow("""
        select s.snapshot_id,s.knowledge_revision,s.snapshot_hash,s.created_at,
          s.glossary_version,s.renderer_version,p.index_revision,i.prepared_id,i.content
        from knowledge_publications p
        join knowledge_snapshots s on s.store_id=p.store_id and s.snapshot_id=p.current_snapshot_id
          and s.knowledge_revision=p.knowledge_revision
        join r_index_publications a on a.store_id=p.store_id and a.snapshot_id=s.snapshot_id
        join r_index_preparations i on i.store_id=a.store_id and i.prepared_id=a.prepared_id
          and i.state='CONSUMED'
        where p.store_id=$1
        """,store_id)
    if row is None:
        raise ApiError(503,"INDEX_UNAVAILABLE","공개 지식의 색인이 준비되지 않았습니다.",retryable=True)
    content = json.loads(row["content"]) if isinstance(row["content"],str) else row["content"]
    snapshot = PublishedKnowledgeSnapshot(**content,snapshot_id=str(row["snapshot_id"]),
        knowledge_revision=str(row["knowledge_revision"]),snapshot_hash=row["snapshot_hash"],created_at=row["created_at"])
    if (snapshot.store_id != str(store_id) or snapshot.glossary_version != row["glossary_version"]
            or snapshot.renderer_version != row["renderer_version"]):
        raise ApiError(503,"INDEX_UNAVAILABLE","공개 색인 구성이 일치하지 않습니다.",retryable=True)
    verify_snapshot_hash(snapshot)
    return snapshot,row["prepared_id"],row["index_revision"]


@dataclass(frozen=True)
class ChannelSearchResult:
    snapshot: PublishedKnowledgeSnapshot
    index_revision: int
    lexical: tuple[dict, ...]
    vector: tuple[dict, ...]
    normalized_query: str
    alias_terms: tuple[str, ...]
    eligible_references: tuple[tuple[str, str, str], ...] | None
    universe_audit: dict | None = None


async def search_channels(pool, *, store_id: int, question: str, query_vector: list[float],
                          channel_limit: int = 20, include_universe: bool = False) -> ChannelSearchResult:
    """제품과 평가가 공유하는 독립 채널 조회. 평가만 현재 승인 모집단도 수집한다."""
    if (type(channel_limit) is not int or not 1<=channel_limit<=100
            or type(include_universe) is not bool
            or len(query_vector)!=1536 or not any(query_vector)
            or any(type(x) not in (int,float) or not math.isfinite(x) for x in query_vector)):
        raise ValueError("invalid query vector or candidate limit")
    query = normalize_query(question)
    if not query:
        raise ValueError("empty query")
    async with pool.acquire() as conn:
        # 두 채널은 같은 공개 판을 읽는다. 임베딩은 이 함수 호출 전에 끝난다.
        async with conn.transaction(isolation="repeatable_read",readonly=True):
            snapshot,pid,index_revision = await read_current_index(conn,store_id=store_id)
            aliases=matched_terms(question,await load_lexicon(conn,store_id=store_id,version=snapshot.glossary_version))
            lexical = await conn.fetch("""
                select d.card_id,d.card_version_id,d.block_id,
                  ts_rank_cd(d.lexical_tsv,websearch_to_tsquery('simple',$3)) as score
                from r_index_documents d join knowledge_cards c
                  on c.store_id=d.store_id and c.card_id=d.card_id
                  and c.published_version_id=d.card_version_id
                  and c.review_status='APPROVED' and c.is_verified=true
                where d.store_id=$1 and d.prepared_id=$2
                  and d.lexical_tsv @@ websearch_to_tsquery('simple',$3)
                order by score desc,d.card_id,d.block_id limit $4
                """,store_id,pid,lexical_query(' '.join((query,*aliases))),channel_limit)
            vector = await conn.fetch("""
                select d.card_id,d.card_version_id,d.block_id,1-(d.embedding <=> $3::vector) as score
                from r_index_documents d join knowledge_cards c
                  on c.store_id=d.store_id and c.card_id=d.card_id
                  and c.published_version_id=d.card_version_id
                  and c.review_status='APPROVED' and c.is_verified=true
                where d.store_id=$1 and d.prepared_id=$2
                order by d.embedding <=> $3::vector,d.card_id,d.block_id limit $4
                """,store_id,pid,vector_literal(query_vector),channel_limit)
            eligible = None
            audit = None
            if include_universe:
                indexed = await conn.fetch("""
                    select d.card_id,d.card_version_id,d.block_id
                    from r_index_documents d
                    where d.store_id=$1 and d.prepared_id=$2
                    order by d.card_id,d.card_version_id,d.block_id
                    """,store_id,pid)
                refs = tuple((str(r['card_id']),str(r['card_version_id']),r['block_id']) for r in indexed)
                audit = audit_index_universe(snapshot,refs)
                if not audit['complete']:
                    raise IndexUniverseMismatch(audit)
                approved = await conn.fetch("""
                    select card_id,published_version_id from knowledge_cards
                    where store_id=$1 and review_status='APPROVED' and is_verified=true
                    """,store_id)
                current = {(str(r['card_id']),str(r['published_version_id'])) for r in approved}
                eligible = tuple(ref for ref in refs if ref[:2] in current)
    return ChannelSearchResult(snapshot,index_revision,tuple(dict(r) for r in lexical),
        tuple(dict(r) for r in vector),query,aliases,eligible,audit)


async def hybrid_search(pool, *, store_id: int, question: str, query_vector: list[float],
                        channel_limit: int = 20, candidate_limit: int = 10) -> SearchResult:
    if type(candidate_limit) is not int or not 1<=candidate_limit<=100:
        raise ValueError('candidate limit must be 1..100')
    result = await search_channels(pool,store_id=store_id,question=question,
        query_vector=query_vector,channel_limit=channel_limit)
    return SearchResult(result.snapshot,result.index_revision,
        fuse(result.lexical,result.vector,limit=candidate_limit),result.normalized_query,
        alias_terms=result.alias_terms)
