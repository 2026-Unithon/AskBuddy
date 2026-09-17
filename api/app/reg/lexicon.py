"""승인된 버전별 검색 사전. 별칭을 사실 또는 규격 확정으로 승격하지 않는다."""
import json
import re
import unicodedata
from datetime import date
from typing import Literal
from uuid import uuid4

from pydantic import Field,model_validator

from app.contracts.common import Contract
from app.contracts.hashing import digest
from app.errors import ApiError
from app.learn.owner_delivery import require_owner


def normalized(text):return ' '.join(unicodedata.normalize('NFKC',text).casefold().split())


class LexiconEntry(Contract):
    layer:Literal['COMMON','STORE']
    term:str=Field(min_length=1,max_length=80)
    variants:tuple[str,...]=Field(min_length=1,max_length=30)
    source:Literal['OWNER','PUBLIC_WEB']='OWNER'
    source_url:str|None=Field(default=None,max_length=2000)
    collected_at:date|None=None
    usage_basis:str|None=Field(default=None,max_length=300)

    @model_validator(mode='after')
    def validate_terms(self):
        for term in (self.term,*self.variants):
            if not re.fullmatch(r'[가-힣A-Za-z][가-힣A-Za-z -]{0,79}',term):
                raise ValueError('dictionary entries are terms, not quantities or recipe assertions')
        terms=[normalized(v) for v in self.variants]
        if len(terms)!=len(set(terms)) or normalized(self.term) in terms:raise ValueError('duplicate alias')
        if self.source=='PUBLIC_WEB' and (not self.source_url or not self.source_url.startswith('https://') or not self.collected_at or not self.usage_basis):
            raise ValueError('public term requires source URL, collection date and usage basis')
        return self


def validated_entries(entries):
    if not 0<=len(entries)<=500:raise ValueError('dictionary must contain at most 500 entries')
    entries=tuple(LexiconEntry.model_validate(e.model_dump()) for e in entries)
    aliases={}
    for entry in entries:
        for alias in entry.variants:
            key=normalized(alias)
            if key in aliases and aliases[key]!=entry.term:raise ValueError('ambiguous alias requires review')
            aliases[key]=entry.term
    return tuple(sorted(entries,key=lambda e:(e.layer,e.term)))


async def approve_lexicon(pool,*,store_id:int,member_id:int,entries:tuple[LexiconEntry,...]) -> str:
    entries=validated_entries(entries)
    payload=[e.model_dump(mode='json') for e in entries]
    content_hash=digest(payload)
    async with pool.acquire() as conn:
        async with conn.transaction():
            user_id=await require_owner(conn,store_id=store_id,member_id=member_id)
            return await conn.fetchval("""insert into r_search_lexicons(store_id,version,content_hash,entries,approved_by)
                values($1,$2,$3,$4::jsonb,$5) on conflict(store_id,content_hash) do nothing returning version""",
                store_id,'rlex:'+uuid4().hex,content_hash,json.dumps(payload),user_id) or await conn.fetchval(
                'select version from r_search_lexicons where store_id=$1 and content_hash=$2',store_id,content_hash)


async def load_lexicon(conn,*,store_id:int,version:str) -> tuple[LexiconEntry,...]:
    # 기존 fixture의 glossary/v1에는 R 사전 manifest가 없으며 alias를 쓰지 않는다.
    if not version.startswith('rlex:'):return ()
    row=await conn.fetchrow('select entries,content_hash from r_search_lexicons where store_id=$1 and version=$2',store_id,version)
    if row is None:raise ApiError(503,'INDEX_UNAVAILABLE','공개 사전 버전을 확인할 수 없습니다.',retryable=True)
    payload=json.loads(row['entries']) if isinstance(row['entries'],str) else row['entries']
    if digest(payload)!=row['content_hash']:raise ApiError(409,'HASH_MISMATCH','사전 버전의 내용이 다릅니다.')
    return validated_entries(tuple(LexiconEntry.model_validate(e) for e in payload))


def matched_terms(question:str,entries:tuple[LexiconEntry,...])->tuple[str,...]:
    query=normalized(question)
    terms=set()
    for entry in entries:
        if any(re.search(r'(?<![가-힣a-z])'+re.escape(normalized(alias))+r'(?:은|는|이|가|을|를|에|의)?(?![가-힣a-z])',query) for alias in entry.variants):
            terms.add(entry.term)
    return tuple(sorted(terms))
