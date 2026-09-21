"""질문 기록을 복제 카드 없이 현재 승인 카드에 연결한 FAQ 파생 뷰."""
from __future__ import annotations

from collections import Counter
import json
import asyncpg
from app.contracts.hashing import digest

from app.reg.retrieve import _STOP, _TAIL, _anchors

_QUESTION_PREFIXES = ("어디", "언제", "어떻게", "무엇", "무슨", "누구", "왜", "얼마")


def _faq_terms(question: str) -> set[str]:
    terms: set[str] = set()
    for term in _anchors(question):
        base = term
        for tail in _TAIL:
            if base.endswith(tail) and len(base) - len(tail) >= 2:
                base = base[: -len(tail)]
                break
        if base in _STOP or base.startswith(_QUESTION_PREFIXES):
            continue
        terms.add(base)
    return terms


def _similar_intent(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    return len(left & right) / min(len(left), len(right)) >= 0.75


def cluster_faq_rows(rows: list[dict]) -> list[dict]:
    clusters: list[dict] = []
    for row in rows:
        terms = _faq_terms(row["question_text"])
        cluster = next(
            (
                item
                for item in clusters
                if item["card_id"] == int(row["card_id"])
                and item.get('scope_key')==row.get('scope_key')
                and (
                    item["question_keys"].get(row["question_key"], 0) > 0
                    or (row.get('scope_key') is None and _similar_intent(item["terms"], terms))
                )
            ),
            None,
        )
        if cluster is None:
            cluster = {
                "card_id": int(row["card_id"]),
                "scope_key":row.get('scope_key'),
                "published_version_id": int(row["published_version_id"]),
                "card_title": row["card_title"],
                "card_content": row["card_content"],
                "category_id": int(row["category_id"]),
                "category_name": row["category_name"],
                "terms": set(terms),
                "question_keys": Counter(),
                "question_texts": {},
                "member_ids": set(),
                "question_count": 0,
                "last_asked_at": row["created_at"],
            }
            clusters.append(cluster)
        cluster["terms"] |= terms
        cluster["question_keys"][row["question_key"]] += 1
        cluster["question_texts"][row["question_key"]] = row["question_text"]
        cluster["member_ids"].add(int(row["member_id"]))
        cluster["question_count"] += 1
        cluster["last_asked_at"] = max(cluster["last_asked_at"], row["created_at"])

    output: list[dict] = []
    for cluster in clusters:
        representative_key = max(
            cluster["question_keys"],
            key=lambda key: (cluster["question_keys"][key], key),
        )
        output.append(
            {
                "question": cluster["question_texts"][representative_key],
                "question_count": cluster["question_count"],
                "distinct_questioners": len(cluster["member_ids"]),
                "last_asked_at": cluster["last_asked_at"],
                "card_id": cluster["card_id"],
                "published_version_id": cluster["published_version_id"],
                "card_title": cluster["card_title"],
                "card_content": cluster["card_content"],
                "category_id": cluster["category_id"],
                "category_name": cluster["category_name"],
            }
        )
    return output


async def list_faqs(
    db: asyncpg.Connection,
    store_id: int,
    *,
    min_questions: int,
    limit: int,
) -> list[dict]:
    rows = await db.fetch(
        """
        select um.content as question_text,
               askbuddy_normalize_question_text(um.content) as question_key,
               s.member_id, um.created_at,
               k.card_id, k.published_version_id,
               v.title as card_title, v.content as card_content,
               tc.category_id, tc.category_name
        from chat_messages um
        join chat_sessions s
          on s.session_id = um.session_id and s.store_id = $1
        left join lateral (
          select mc.card_id
          from chat_messages bm
          join message_citations mc on mc.message_id = bm.message_id
          join knowledge_cards current_card
            on current_card.store_id = $1
           and current_card.card_id = mc.card_id
           and current_card.review_status = 'APPROVED'
           and current_card.is_verified = true
           and current_card.published_version_id = mc.version_id
          where bm.session_id = um.session_id
            and bm.message_id > um.message_id
            and bm.sender_type = 'BUDDY'
            and bm.answer_type = 'ANSWERED'
            and bm.answer_source in ('GROUNDED_LLM', 'CARD_ORIGINAL')
          order by bm.message_id, mc.citation_id
          limit 1
        ) ai on true
        left join lateral (
          select coalesce(p.result_card_id, p.target_card_id) as card_id
          from pending_questions q
          join owner_answers a on a.question_id = q.question_id
          join knowledge_change_proposals p on p.answer_id = a.answer_id
          where q.store_id = $1
            and q.normalized_question = askbuddy_normalize_question_text(um.content)
            and p.status in ('LINKED', 'PUBLISHED')
          order by p.resolved_at desc nulls last, p.proposal_id desc
          limit 1
        ) owner_knowledge on ai.card_id is null
        join knowledge_cards k
          on k.store_id = $1
         and k.card_id = coalesce(ai.card_id, owner_knowledge.card_id)
         and k.review_status = 'APPROVED'
         and k.is_verified = true
         and k.published_version_id is not null
        join card_versions v
          on v.store_id = k.store_id and v.version_id = k.published_version_id
        join task_categories tc
          on tc.store_id = k.store_id and tc.category_id = k.category_id
         and tc.deleted_at is null and tc.is_enabled = true
        where um.sender_type = 'USER' and s.contract_version='v1'
        order by um.created_at desc, um.message_id desc
        limit 2000
        """,
        store_id,
    )
    v2_rows=await v2_faq_rows(db,store_id=store_id)
    clusters = cluster_faq_rows([dict(row) for row in rows]+v2_rows)
    visible = [item for item in clusters if item["question_count"] >= min_questions]
    visible.sort(
        key=lambda item: (
            item["question_count"],
            item["distinct_questioners"],
            item["last_asked_at"],
        ),
        reverse=True,
    )
    return visible[:limit]


async def v2_faq_rows(db:asyncpg.Connection,*,store_id:int) -> list[dict]:
    """Read-through view: only currently approved published knowledge, never owner raw alone."""
    rows=await db.fetch("""select distinct r.receipt_id,r.original_question,r.resolved_query,r.context_snapshot,r.member_id,
        r.created_at,k.card_id,k.published_version_id,v.title as card_title,v.content as card_content,
        tc.category_id,tc.category_name
        from r_answer_receipts r
        join store_members m on m.store_id=r.store_id and m.member_id=r.member_id
        left join r_answer_citations rc on rc.store_id=r.store_id and rc.receipt_id=r.receipt_id
            and r.response->>'action'='ANSWER'
        left join lateral (
            select case when ks.status in ('LINKED','PUBLISHED') then ks.result else null end as result from r_owner_answer_revisions ar
            join r_owner_knowledge_states ks on ks.store_id=ar.store_id and ks.owner_answer_id=ar.owner_answer_id
            where ar.store_id=r.store_id and ar.question_id=r.pending_id
            order by ar.revision_no desc limit 1
        ) owner_result on r.pending_id is not null
        join knowledge_cards k on k.store_id=r.store_id and k.review_status='APPROVED' and k.is_verified=true
            and k.published_version_id is not null and (
              (k.card_id=rc.card_id and k.published_version_id=rc.card_version_id)
              or (rc.card_id is null and owner_result.result->>'status' in ('LINKED','PUBLISHED')
                  and k.card_id::text=owner_result.result->>'card_id'
                  and k.published_version_id::text=owner_result.result->>'published_card_version_id'))
        join card_versions v on v.store_id=k.store_id and v.version_id=k.published_version_id
        join task_categories tc on tc.store_id=k.store_id and tc.category_id=k.category_id
            and tc.deleted_at is null and tc.is_enabled=true
        where r.store_id=$1
        order by r.created_at desc,r.receipt_id desc limit 2000""",store_id)
    output=[]
    for source in rows:
        row=dict(source)
        resolved=json.loads(row.pop('resolved_query')) if isinstance(row['resolved_query'],str) else row.pop('resolved_query')
        # Full resolved question keeps conditions and follow-up scope. No fuzzy clustering.
        context=row.pop('context_snapshot',None)
        context=json.loads(context) if isinstance(context,str) else context
        original=(context or {}).get('context',{}).get('original_question')
        question=resolved.get('question') or ((original+' '+row['original_question']) if original else row['original_question'])
        scope=digest(dict(entity=resolved.get('entity'),predicate=resolved.get('predicate'),
            variants=resolved.get('variants'),slots=resolved.get('confirmed_slots'),
            question=question,version=str(row['published_version_id'])))
        row.update(question_text=question,question_key=scope,scope_key='v2:'+scope)
        output.append(row)
    return output
