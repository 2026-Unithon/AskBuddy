"""실제 DB: Phase A 사실 전용 경로 합성 종단 검증. 모델·임베딩은 합성 대역이다(비용 0).

verify_r_schema_rebuild 가 부른다. 시나리오마다 새 합성 매장을 만든다.
  (c) 공개 카드 대상에 새 사실 → 모델 재조립 없이 공개판 사실 + 새 사실로 새 초안(A-D4)
    c-1 첫 자료로 카드를 만들고 공개
    c-2 새 사실을 가진 둘째 자료 → 같은 카드의 새 초안·NEW_FACTS·공개판은 그대로
    c-3 새 초안 승인 → 공개판이 새 판으로
    c-4 같은 사실만 가진 셋째 자료 → 새 판 없음·그 자료 occurrence 는 그 카드로 LINKED
    c-5 수동 배정 카드 → 새 사실은 REVIEW_PENDING·EXISTING_CARD·새 판 없음
    c-6 공개 사실과 값이 다른 새 사실(열린 충돌) → 새 초안의 검수 표시는 FACT_CONFLICT_OPEN
    c-7 승인 전 재초안이 있는 대상에 둘째 새 자료 → 그 재초안 위에 이어 붙인 새 초안(I5)·
        같은 대상 점주 답변 → REVIEW(SUPPLEMENT)·답변 사실이 초안에 들어간다
  (b) 점주 답변 → OWNER_TEXT 자료 → 사실 카드 (A-D3). 추출은 합성 대역, 벡터는 합성이다
    b-1 새 대상 답변 → 사실 카드 자동 공개(PUBLISHED)·근거는 그 자료 occurrence·R 답변이 그 사실을 인용
    b-2 같은 대상에 새 사실 답변 → REVIEW(SUPPLEMENT)·새 초안·공개판 그대로 → 나중 승인으로 공개
    b-3 사실 0개 답변 → REVIEW(NO_FACTS)·카드 수 불변·승인은 NO_DRAFT_MESSAGE 로 거절
    b-4 같은 매장에서 같은 글의 답변이 또 와도 자료를 따로 만든다(content_hash null, I1)
    b-5 SUPPLEMENT 초안을 카드 화면에서 먼저 공개 → 제안 승인은 ALREADY_APPLIED·
        제안 PUBLISHED·R 상태 PUBLISHED(I4)
  (d) 카드 판 1 은 코드가 만든다 — 레거시 판 생성 트리거 제거(Phase A Task 7)
    d-1 업로드 경로(seed_fact_card)·점주 답변 경로(b 의 카드) —
        초안 포인터가 가리키는 판이 있고 version_no = 1
    d-2 knowledge_cards 직접 INSERT 는 판을 만들지 않는다(draft_version_id null)
    d-3 pg_trigger 에 trg_knowledge_cards_version_legacy_write 가 없다
  (a) 1회 삭제 migration 리허설(A-D5) — (b)·(c)·(d) 가 데이터를 채운 뒤 migration 파일을 한 번 더 실행한다
    a-0 평가 기록(quality_evaluations) 행이 있으면 예외로 멈추고 아무것도 지우지 않는다(롤백)
    a-1 남길 표 행 수 불변·지울 표 0행·카드 연결 null·guide_completed_at null·불변 트리거 다시 켜짐
    a-2 첫 직원 질문 → R ensure_initial_publication 이 빈 공개판을 만들고 질문은 근거 없음으로 이관
    a-3 같은 파일을 빈 DB 에서 한 번 더 실행해도 오류가 없다
출력 줄 머리는 `PASS WA <시나리오 id> <설명>`.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from _fact_card_fixture import (_mock_settings, _vectors, assertion, edit_fact_value, publish_card,
                                seed_fact_card)
from app.cards.owner_answer_worker import process_next_owner_event
from app.contracts.usage import UsageContext
from app.ingest import extract, fact_cards
from app.ingest.owner_text import answer_cards, owner_answer_source
from app.ingest.schemas import FactExtractionResult
from app.learn.answer_storage import save_answer
from app.learn.knowledge_apply import NO_DRAFT_MESSAGE, approve_owner_proposal
from app.learn.owner_delivery import submit_owner_answer
from app.learn.owner_handoff import finish_owner_review
from app.learn.planner import decide
from app.publish.empty import ensure_initial_publication
from app.reg.hybrid import hybrid_search, read_current_index

Z = "음료Z"


def _checker(scenario: str):
    def check(name: str, ok: bool) -> None:
        assert ok, f"WA {scenario} {name}"
        print(f"PASS WA {scenario} {name}")
    return check


async def _store(db) -> NS:
    """합성 매장 — 점주·점주 멤버·'기타' 카테고리."""
    user = await db.fetchval(
        "insert into users (name, phone, role) values ('합성점주','010-0000-0000','OWNER') "
        "returning user_id")
    store = await db.fetchval(
        "insert into stores (owner_id, store_name, business_type) "
        "values ($1,'합성 매장','CAFE') returning store_id", user)
    member = await db.fetchval(
        "insert into store_members (store_id, user_id, member_role) values ($1,$2,'OWNER') "
        "returning member_id", store, user)
    await db.execute(
        "insert into task_categories (store_id, category_name) values ($1, '기타') "
        "on conflict (store_id, category_name) do nothing", store)
    return NS(user=user, store=store, member=member)


async def _card(db, store, card_id):
    return await db.fetchrow(
        "select card_id, draft_version_id, published_version_id, review_status, "
        "needs_review_reason, assignment_type from knowledge_cards "
        "where store_id=$1 and card_id=$2", store, card_id)


async def _version_count(db, store, card_id) -> int:
    return int(await db.fetchval(
        "select count(*) from card_versions where store_id=$1 and card_id=$2", store, card_id))


async def _block_predicates(db, store, version_id) -> list[str]:
    rows = await db.fetch(
        "select r.predicate from card_block_facts b "
        "join fact_revisions r on r.store_id = b.store_id "
        "  and r.fact_revision_id = b.fact_revision_id "
        "where b.store_id=$1 and b.card_version_id=$2 order by b.block_id, b.position",
        store, version_id)
    return [r["predicate"] for r in rows]


async def _published_card_version(pool, store, card_id) -> str | None:
    async with pool.acquire() as conn:
        snapshot, _, _ = await read_current_index(conn, store_id=store)
    card = snapshot.card(str(card_id)) if snapshot is not None else None
    return card.card_version_id if card is not None else None


async def _latest_source(db, store) -> int:
    return int(await db.fetchval(
        "select max(source_id) from sources where store_id=$1", store))


async def _occurrences(db, store, source):
    return await db.fetch(
        "select disposition, reason, card_id from fact_occurrences "
        "where store_id=$1 and source_id=$2 order by occurrence_id", store, source)


async def _scenario_c(pool, db) -> None:
    check = _checker("c")
    w = await _store(db)

    # c-1 첫 자료 → 카드 → 공개
    card_id, v1 = await seed_fact_card(
        pool, store_id=w.store, owner_user_id=w.user,
        assertions=[assertion("f1", Z, "물", "225", unit="ml")], title="합성 자료 1")
    result = await publish_card(pool, store_id=w.store, member_id=w.member,
                                actor_user_id=w.user, card_id=card_id)
    check("c-1 첫 카드 공개 PUBLISHED", result.status == "PUBLISHED")
    check("c-1 공개판 카드 판 = v1",
          await _published_card_version(pool, w.store, card_id) == str(v1))

    # c-2 새 사실(시럽)을 가진 둘째 자료 → 같은 카드의 새 초안
    card_2, v2 = await seed_fact_card(
        pool, store_id=w.store, owner_user_id=w.user,
        assertions=[assertion("f1", Z, "물", "225", unit="ml"),
                    assertion("f2", Z, "시럽", "30", unit="ml")], title="합성 자료 2")
    row = await _card(db, w.store, card_id)
    check("c-2 같은 카드 id", card_2 == card_id)
    check("c-2 새 초안 ≠ 공개판",
          row["draft_version_id"] == v2 and v2 != v1 and row["published_version_id"] == v1)
    check("c-2 needs_review_reason NEW_FACTS·review_status APPROVED",
          row["needs_review_reason"] == fact_cards.REVIEW_NEW_FACTS
          and row["review_status"] == "APPROVED")
    check("c-2 새 판 블록 사실 = 물·시럽",
          sorted(await _block_predicates(db, w.store, v2)) == sorted(["물", "시럽"]))
    check("c-2 공개판 snapshot 의 카드 판은 여전히 v1",
          await _published_card_version(pool, w.store, card_id) == str(v1))
    src2 = await _latest_source(db, w.store)
    check("c-2 둘째 자료 occurrence 모두 그 카드로 LINKED",
          all(r["disposition"] == "LINKED" and r["card_id"] == card_id
              for r in await _occurrences(db, w.store, src2)))

    # c-3 새 초안 승인 → 공개판이 새 판으로
    result = await publish_card(pool, store_id=w.store, member_id=w.member,
                                actor_user_id=w.user, card_id=card_id)
    row = await _card(db, w.store, card_id)
    check("c-3 새 초안 공개 PUBLISHED", result.status == "PUBLISHED")
    check("c-3 공개판 카드 판 = 새 판·needs_review_reason null",
          await _published_card_version(pool, w.store, card_id) == str(v2)
          and row["published_version_id"] == v2 and row["needs_review_reason"] is None)

    # c-4 같은 사실만 가진 셋째 자료 → 새 판 없음
    versions = await _version_count(db, w.store, card_id)
    card_4, v4 = await seed_fact_card(
        pool, store_id=w.store, owner_user_id=w.user,
        assertions=[assertion("f1", Z, "물", "225", unit="ml")], title="합성 자료 3")
    src3 = await _latest_source(db, w.store)
    occ = await _occurrences(db, w.store, src3)
    row = await _card(db, w.store, card_id)
    check("c-4 새 판 없음",
          card_4 == card_id and v4 == v2 and await _version_count(db, w.store, card_id) == versions
          and row["draft_version_id"] == row["published_version_id"] == v2
          and row["needs_review_reason"] is None)
    check("c-4 셋째 자료 occurrence 가 그 카드로 LINKED",
          occ and all(r["disposition"] == "LINKED" and r["card_id"] == card_id for r in occ))

    # c-5 수동 배정 카드 → 새 사실은 검수 대기, 새 판 없음
    await db.execute("update knowledge_cards set assignment_type='MANUAL' "
                     "where store_id=$1 and card_id=$2", w.store, card_id)
    try:
        await seed_fact_card(
            pool, store_id=w.store, owner_user_id=w.user,
            assertions=[assertion("f1", Z, "얼음", "150", unit="g")], title="합성 자료 4")
        linked = True
    except RuntimeError as e:
        if "합성 사실 카드가 만들어지지 않았다" not in str(e):
            raise
        linked = False  # 이 자료의 사실이 어느 카드에도 이어지지 않았다(기대)
    src4 = await _latest_source(db, w.store)
    occ = await _occurrences(db, w.store, src4)
    row = await _card(db, w.store, card_id)
    check("c-5 새 사실 REVIEW_PENDING·EXISTING_CARD",
          not linked and occ
          and all(r["disposition"] == "REVIEW_PENDING"
                  and r["reason"] == fact_cards.REASON_EXISTING_CARD and r["card_id"] is None
                  for r in occ))
    check("c-5 새 판 없음",
          await _version_count(db, w.store, card_id) == versions
          and row["draft_version_id"] == row["published_version_id"] == v2)


async def _scenario_c6(pool, db) -> None:
    """새 사실이 공개 사실과 충돌하면 NEW_FACTS 가 충돌 표시를 덮지 않는다."""
    check = _checker("c")
    w = await _store(db)
    card_id, v1 = await seed_fact_card(
        pool, store_id=w.store, owner_user_id=w.user,
        assertions=[assertion("f1", Z, "물", "225", unit="ml")], title="합성 자료 1")
    result = await publish_card(pool, store_id=w.store, member_id=w.member,
                                actor_user_id=w.user, card_id=card_id)
    check("c-6 첫 카드 공개 PUBLISHED", result.status == "PUBLISHED")
    card_2, v2 = await seed_fact_card(
        pool, store_id=w.store, owner_user_id=w.user,
        assertions=[assertion("f1", Z, "물", "250", unit="ml")], title="합성 자료 2")
    open_conflicts = int(await db.fetchval(
        "select count(*) from fact_conflicts where store_id=$1 and status='OPEN'", w.store))
    row = await _card(db, w.store, card_id)
    check("c-6 열린 충돌 행이 있다", open_conflicts >= 1)
    check("c-6 같은 카드의 새 초안·공개판 그대로",
          card_2 == card_id and v2 != v1 and row["draft_version_id"] == v2
          and row["published_version_id"] == v1 and row["review_status"] == "APPROVED")
    check("c-6 새 판에 두 값이 나란히(물·물)",
          await _block_predicates(db, w.store, v2) == ["물", "물"])
    check("c-6 needs_review_reason FACT_CONFLICT_OPEN (NEW_FACTS 아님)",
          row["needs_review_reason"] == fact_cards.REVIEW_CONFLICT)


async def _scenario_c7(pool, db) -> None:
    """승인 전 시스템 재초안 위에 다음 자료·점주 답변의 새 사실을 이어 붙인다(I5)."""
    check = _checker("c")
    w = await _store(db)
    card_id, v1 = await seed_fact_card(
        pool, store_id=w.store, owner_user_id=w.user,
        assertions=[assertion("f1", Z, "물", "225", unit="ml")], title="합성 자료 1")
    await publish_card(pool, store_id=w.store, member_id=w.member, actor_user_id=w.user,
                       card_id=card_id)
    _, v2 = await seed_fact_card(
        pool, store_id=w.store, owner_user_id=w.user,
        assertions=[assertion("f1", Z, "시럽", "30", unit="ml")], title="합성 자료 2")
    card_3, v3 = await seed_fact_card(
        pool, store_id=w.store, owner_user_id=w.user,
        assertions=[assertion("f1", Z, "얼음", "150", unit="g")], title="합성 자료 3")
    row = await _card(db, w.store, card_id)
    src3 = await _latest_source(db, w.store)
    check("c-7 둘째 새 자료 → 같은 카드의 새 초안(재초안 위에)·공개판 그대로",
          card_3 == card_id and v3 not in (v1, v2) and row["draft_version_id"] == v3
          and row["published_version_id"] == v1
          and await _published_card_version(pool, w.store, card_id) == str(v1))
    check("c-7 새 초안 블록 사실 = 물·시럽·얼음(앞 재초안의 사실을 잃지 않는다)",
          sorted(await _block_predicates(db, w.store, v3)) == sorted(["물", "시럽", "얼음"]))
    check("c-7 셋째 자료 occurrence 모두 그 카드로 LINKED",
          all(r["disposition"] == "LINKED" and r["card_id"] == card_id
              for r in await _occurrences(db, w.store, src3)))

    text = "음료Z 휘핑은 20g"
    answer = await _owner_answer(pool, db, w, key="c7-answer", question="음료Z 휘핑은요?", answer=text)
    status = await _process(pool, w, _said(text, "f1", "휘핑", "20", "g"))
    proposal = await _proposal(db, w.store, answer)
    row = await _card(db, w.store, card_id)
    check("c-7 점주 답변 → REVIEW·SUPPLEMENT·대상 = 그 카드",
          status == "REVIEW" and proposal["relation_type"] == "SUPPLEMENT"
          and proposal["target_card_id"] == card_id and proposal["reason"] != "FACTS_PENDING")
    check("c-7 답변 사실이 새 초안에 들어간다·공개판 그대로",
          row["draft_version_id"] != v3 and row["published_version_id"] == v1
          and sorted(await _block_predicates(db, w.store, row["draft_version_id"]))
          == sorted(["물", "시럽", "얼음", "휘핑"]))

    # 점주가 고치던 초안(OWNER_EDIT)은 덮지 않는다 — 다음 자료는 보류
    edited = await edit_fact_value(pool, store_id=w.store, owner_user_id=w.user,
                                   card_id=card_id, value="230", key="wa-c7-edit")
    check("c-7 점주 사실 편집 → OWNER_EDIT 초안",
          (await _version(db, w.store, edited))["change_source"] == "OWNER_EDIT")
    try:
        await seed_fact_card(
            pool, store_id=w.store, owner_user_id=w.user,
            assertions=[assertion("f1", Z, "컵", "1", unit="개")], title="합성 자료 4")
        linked = True
    except RuntimeError as e:
        if "합성 사실 카드가 만들어지지 않았다" not in str(e):
            raise
        linked = False
    occ = await _occurrences(db, w.store, await _latest_source(db, w.store))
    check("c-7 점주 편집 초안 위에는 붙이지 않는다(REVIEW_PENDING·EXISTING_CARD)",
          not linked and occ and all(r["disposition"] == "REVIEW_PENDING"
                                     and r["reason"] == fact_cards.REASON_EXISTING_CARD
                                     for r in occ))


def _extracting(*assertions):
    """추출 대역 — 정해 둔 사실만 돌려준다(유료 호출 0). 근거 자료는 호출된 자료로 맞춘다."""
    async def fake(*, source_id, **kwargs):
        return FactExtractionResult(assertions=[
            a.model_copy(update={"evidence": a.evidence.model_copy(update={"source_id": source_id})})
            for a in assertions])
    return fake


async def _owner_answer(pool, db, w, *, key: str, question: str, answer: str) -> int:
    """v2 대기 질문을 만들고 R 접점으로 점주 답변을 제출한다. owner_answer_id."""
    qid = await db.fetchval(
        "insert into pending_questions (store_id, member_id, question_text, contract_version, "
        "semantic_key) values ($1,$2,$3,'v2',$4) returning question_id",
        w.store, w.member, question, f"synthetic-wa-{key}")
    reply = await submit_owner_answer(pool, store_id=w.store, member_id=w.member,
                                      question_id=qid, request_id=f"wa-b-{key}",
                                      answer=answer, expected_revision=0)
    return int(reply["owner_answer_id"])


async def _process(pool, w, *assertions) -> str | None:
    settings = _mock_settings()
    with patch("app.ingest.extract.extract_facts", _extracting(*assertions)), \
            patch.object(extract, "get_settings", lambda: settings), \
            patch("app.reg.index_preparation.recorded_embeddings", _vectors):
        return await process_next_owner_event(pool, store_id=w.store)


async def _proposal(db, store, answer_id):
    return await db.fetchrow(
        "select proposal_id, relation_type, status, reason, target_card_id, result_card_id "
        "from knowledge_change_proposals where store_id=$1 and answer_id=$2", store, answer_id)


async def _approve(pool, w, proposal_id, *, with_r: bool = False):
    context = UsageContext(store_id=str(w.store), stage="EMBED", cost_phase="OPERATING",
                           cost_purpose="PRODUCT", logical_call_id=f"wa-b-approve:{proposal_id}")

    async def notify_r(conn, answer_id, card_id, version_id, revision):
        # R 라우트(approve_knowledge_proposal)가 넘기는 것과 같은 완료 접점
        await finish_owner_review(conn, store_id=w.store, proposal_id=proposal_id,
                                  owner_answer_id=answer_id, card_id=card_id,
                                  card_version_id=version_id, knowledge_revision=revision)

    with patch("app.reg.index_preparation.recorded_embeddings", _vectors):
        return await approve_owner_proposal(
            pool, store_id=w.store, member_id=w.member, actor_user_id=w.user,
            proposal_id=proposal_id, usage_context=context,
            notify_r=notify_r if with_r else None)


def _said(text: str, ref: str, attribute: str, value: str, unit: str, variant: str = ""):
    return assertion(ref, Z, attribute, value, unit=unit).model_copy(
        update={"original_assertion": text, "variant": variant})


async def _scenario_b(pool, db) -> None:
    check = _checker("b")
    w = await _store(db)

    # b-1 새 대상 답변 → 사실 카드 자동 공개
    text = "음료Z HOT 물은 225ml 넣어요"
    first = await _owner_answer(pool, db, w, key="first", question="음료Z HOT 물 얼마나 넣어요?",
                                answer=text)
    # 속성·규격은 R 계획기가 답할 수 있는 모양(정식 속성 water_amount·HOT)으로 준다 — B3 와 같은 이유
    status = await _process(pool, w, _said(text, "f1", "water_amount", "225", "ml", "HOT"))
    check("b-1 worker 결과 PUBLISHED", status == "PUBLISHED")
    links = await db.fetch("select source_id from owner_answer_sources "
                           "where store_id=$1 and owner_answer_id=$2", w.store, first)
    src = await owner_answer_source(db, w.store, owner_answer_id=first)
    source = await db.fetchrow("select source_type, status, file_url from sources "
                               "where store_id=$1 and source_id=$2", w.store, src)
    check("b-1 owner_answer_sources 1행·OWNER_TEXT 자료 DONE·파일 없음",
          len(links) == 1 and source["source_type"] == "OWNER_TEXT"
          and source["status"] == "DONE" and source["file_url"] is None)
    (card,) = await answer_cards(db, w.store, source_id=src)
    snap = (await read_current_index(db, store_id=w.store))[0]
    published = snap.card(str(card.card_id))
    check("b-1 공개판에 사실 블록 카드(초안 = 공개판)",
          published is not None and published.card_version_id == str(card.draft_version_id)
          and card.published_version_id == card.draft_version_id
          and await _block_predicates(db, w.store, card.draft_version_id) == ["water_amount"])
    (fact,) = snap.fact_revisions
    check("b-1 사실 판 근거 = 그 OWNER_TEXT 자료 occurrence",
          fact.provenance and all(p.source_id == str(src) for p in fact.provenance))
    state = await db.fetchval("select status from r_owner_knowledge_states "
                              "where store_id=$1 and owner_answer_id=$2", w.store, first)
    check("b-1 R r_owner_knowledge_states PUBLISHED", state == "PUBLISHED")
    proposal = await _proposal(db, w.store, first)
    check("b-1 제안 NEW·PUBLISHED",
          (proposal["relation_type"], proposal["status"]) == ("NEW", "PUBLISHED"))

    question = "음료Z HOT 물 얼마나?"
    found = await hybrid_search(pool, store_id=w.store, question=question,
                                query_vector=[1.0] + [0.0] * 1535)
    session = await db.fetchval(
        "insert into chat_sessions (store_id, member_id, contract_version) "
        "values ($1,$2,'v2') returning session_id", w.store, w.member)
    decision = decide(found, store_id=w.store, question=question)
    saved = await save_answer(
        pool, store_id=w.store, member_id=w.member, session_id=session,
        request_id="wa-b-answer-question", question=question, snapshot=found.snapshot,
        plan=decision.plan, resolved=decision.resolved,
        confirmed_slots=decision.confirmed_slots, semantic_context=decision.semantic_context)
    response = saved.response
    ok = bool(response.action == "ANSWER" and response.citations
              and response.citations[0].fact_revision_id == fact.fact_revision_id
              and response.citations[0].source_id == str(src))
    if not ok:
        print(f"FAIL WA b R 답변 (action={response.action}, "
              f"reason={decision.plan.escalation_reason})")
    check("b-1 R 답변 ANSWER·인용 사실·자료 == 공개판", ok)

    # b-2 같은 대상에 새 사실 → 검수(SUPPLEMENT) → 나중 승인
    text2 = "음료Z 시럽은 30ml"
    second = await _owner_answer(pool, db, w, key="second", question="음료Z 시럽은요?",
                                 answer=text2)
    status = await _process(pool, w, _said(text2, "f1", "시럽", "30", "ml"))
    proposal = await _proposal(db, w.store, second)
    row = await _card(db, w.store, card.card_id)
    check("b-2 worker 결과 REVIEW·제안 SUPPLEMENT·PENDING_REVIEW·대상 = 그 카드",
          status == "REVIEW" and proposal["relation_type"] == "SUPPLEMENT"
          and proposal["status"] == "PENDING_REVIEW"
          and proposal["target_card_id"] == card.card_id)
    check("b-2 카드 새 초안·공개판 그대로·사유 OWNER_ANSWER_SUPPLEMENT",
          row["draft_version_id"] != card.draft_version_id
          and row["published_version_id"] == card.draft_version_id
          and row["needs_review_reason"] == "OWNER_ANSWER_SUPPLEMENT"
          and await _published_card_version(pool, w.store, card.card_id)
          == str(card.draft_version_id))
    check("b-2 새 초안 블록 사실 = 물·시럽",
          sorted(await _block_predicates(db, w.store, row["draft_version_id"]))
          == sorted(["water_amount", "시럽"]))
    result = await _approve(pool, w, proposal["proposal_id"])
    after = await _card(db, w.store, card.card_id)
    check("b-2 승인 PUBLISHED·공개판 카드 판 = 새 초안",
          result.status == "PUBLISHED"
          and after["published_version_id"] == row["draft_version_id"]
          and await _published_card_version(pool, w.store, card.card_id)
          == str(row["draft_version_id"]))
    closed = await _proposal(db, w.store, second)
    check("b-2 제안 PUBLISHED·결과 카드 = 그 카드",
          closed["status"] == "PUBLISHED" and closed["result_card_id"] == card.card_id)

    # b-3 사실 0개 답변 → 검수(NO_FACTS), 카드 없음, 승인은 거절
    cards_before = await db.fetchval("select count(*) from knowledge_cards where store_id=$1",
                                     w.store)
    third = await _owner_answer(pool, db, w, key="third", question="오늘 기분 어때요?",
                                answer="좋아요")
    status = await _process(pool, w)
    proposal = await _proposal(db, w.store, third)
    check("b-3 worker 결과 REVIEW·제안 reason NO_FACTS·PENDING_REVIEW",
          status == "REVIEW" and proposal["reason"] == "NO_FACTS"
          and proposal["status"] == "PENDING_REVIEW")
    check("b-3 카드 수 불변",
          await db.fetchval("select count(*) from knowledge_cards where store_id=$1",
                            w.store) == cards_before)
    try:
        await _approve(pool, w, proposal["proposal_id"])
        refused = False
    except ValueError as exc:
        refused = str(exc) == NO_DRAFT_MESSAGE
    check("b-3 승인은 NO_DRAFT_MESSAGE 로 거절", refused)

    # b-4 같은 글("좋아요")의 답변이 같은 매장에 또 온다 — 자료를 따로 만든다(I1)
    fourth = await _owner_answer(pool, db, w, key="fourth", question="오늘 날씨 어때요?",
                                 answer="좋아요")
    status = await _process(pool, w)
    src3 = await owner_answer_source(db, w.store, owner_answer_id=third)
    src4 = await owner_answer_source(db, w.store, owner_answer_id=fourth)
    hashes = await db.fetch("select content_hash from sources where store_id=$1 "
                            "and source_id = any($2::bigint[])", w.store, [src3, src4])
    check("b-4 같은 글 둘째 답변도 REVIEW(FAILED 아님)·자료 따로·content_hash null",
          status == "REVIEW" and src3 is not None and src4 is not None and src3 != src4
          and len(hashes) == 2 and all(h["content_hash"] is None for h in hashes))

    # b-5 SUPPLEMENT 초안을 카드 화면에서 먼저 공개한 뒤 제안을 승인한다(I4)
    text5 = "음료Z 얼음은 150g"
    fifth = await _owner_answer(pool, db, w, key="fifth", question="음료Z 얼음은요?",
                                answer=text5)
    status = await _process(pool, w, _said(text5, "f1", "얼음", "150", "g"))
    proposal = await _proposal(db, w.store, fifth)
    draft5 = (await _card(db, w.store, card.card_id))["draft_version_id"]
    check("b-5 worker 결과 REVIEW·SUPPLEMENT·대상 = 그 카드",
          status == "REVIEW" and proposal["relation_type"] == "SUPPLEMENT"
          and proposal["target_card_id"] == card.card_id)
    published = await publish_card(pool, store_id=w.store, member_id=w.member,
                                   actor_user_id=w.user, card_id=card.card_id)
    check("b-5 카드 화면 공개 PUBLISHED·제안은 아직 PENDING_REVIEW",
          published.status == "PUBLISHED"
          and (await _proposal(db, w.store, fifth))["status"] == "PENDING_REVIEW")
    result = await _approve(pool, w, proposal["proposal_id"], with_r=True)
    closed = await _proposal(db, w.store, fifth)
    result_version = await db.fetchval(
        "select result_version_id from knowledge_change_proposals "
        "where store_id=$1 and proposal_id=$2", w.store, proposal["proposal_id"])
    state = await db.fetchval("select status from r_owner_knowledge_states "
                              "where store_id=$1 and owner_answer_id=$2", w.store, fifth)
    check("b-5 제안 승인 ALREADY_APPLIED·제안 PUBLISHED(그 카드·공개 판)",
          result.status == "ALREADY_APPLIED" and closed["status"] == "PUBLISHED"
          and closed["result_card_id"] == card.card_id and result_version == draft5)
    check("b-5 R r_owner_knowledge_states PUBLISHED", state == "PUBLISHED")
    again = await _approve(pool, w, proposal["proposal_id"], with_r=True)
    check("b-5 재승인도 ALREADY_APPLIED", again.status == "ALREADY_APPLIED")
    return w, card.card_id, card.draft_version_id


async def _version(db, store, version_id):
    return await db.fetchrow(
        "select card_id, version_no, change_source, created_by, owner_answer_id "
        "from card_versions where store_id=$1 and version_id=$2", store, version_id)


async def _scenario_d(pool, db, answer_card: tuple[NS, int, int]) -> None:
    check = _checker("d")
    w = await _store(db)

    # d-1 업로드 경로 — 원장 → 사실 조립 → insert_card
    upload_card, upload_draft = await seed_fact_card(
        pool, store_id=w.store, owner_user_id=w.user,
        assertions=[assertion("f1", Z, "물", "225", unit="ml")], title="합성 d 자료")
    row = await _card(db, w.store, upload_card)
    version = await _version(db, w.store, row["draft_version_id"])
    check("d-1 업로드 카드 초안 판 1(EXTRACTION)",
          row["draft_version_id"] == upload_draft and version is not None
          and version["card_id"] == upload_card and version["version_no"] == 1
          and version["change_source"] == "EXTRACTION")

    # 점주 답변 경로 — 시나리오 b 의 b-1 카드(첫 초안 = 첫 공개판)
    bw, b_card, b_first = answer_card
    version = await _version(db, bw.store, b_first)
    check("d-1 점주 답변 경로 카드의 첫 판 version_no 1",
          version is not None and version["card_id"] == b_card and version["version_no"] == 1
          and await db.fetchval("select min(version_no) from card_versions "
                                "where store_id=$1 and card_id=$2", bw.store, b_card) == 1)

    # d-2 카드 행 직접 INSERT 는 판을 만들지 않는다
    bare = await db.fetchval(
        "insert into knowledge_cards (store_id, title, content) values ($1,'합성 d 맨 카드','본문') "
        "returning card_id", w.store)
    await db.execute("update knowledge_cards set title='합성 d 맨 카드 2', content='본문 2' "
                     "where store_id=$1 and card_id=$2", w.store, bare)
    row = await _card(db, w.store, bare)
    check("d-2 직접 INSERT·제목 UPDATE 는 판을 만들지 않는다(draft_version_id null)",
          row["draft_version_id"] is None and await db.fetchval(
              "select count(*) from card_versions where store_id=$1 and card_id=$2",
              w.store, bare) == 0)

    # d-3 트리거·함수가 없다
    check("d-3 trg_knowledge_cards_version_legacy_write 없음",
          not await db.fetchval("select exists(select 1 from pg_trigger "
                                "where tgname = 'trg_knowledge_cards_version_legacy_write')")
          and not await db.fetchval("select exists(select 1 from pg_proc "
                                    "where proname = 'askbuddy_version_legacy_card_write')"))


WIPE_SQL = (Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261010110000_w_wipe_knowledge_once.sql")

# 남길 표(A-U6) — 행 수가 그대로여야 한다. knowledge_publications 는 행을 남기고 포인터만 비운다
KEEP_TABLES = (
    "stores", "users", "store_members", "task_categories", "store_shifts", "member_shifts",
    "pending_questions", "pending_question_occurrences", "owner_answers",
    "r_owner_answer_revisions", "chat_sessions", "chat_messages", "ai_usage_attempts",
    "extraction_raw_responses", "notification_events", "roadmap_stages", "roadmap_items",
    "learning_progress", "checklist_submissions", "outbox_events", "knowledge_publications",
    "quality_evaluations")

# migration 이 다시 켜야 하는 불변 트리거 (표, 트리거)
IMMUTABLE_TRIGGERS = (
    ("r_answer_citations", "r_answer_citation_immutable"),
    ("r_answer_receipts", "r_answer_receipt_immutable"),
    ("knowledge_snapshots", "trg_snapshot_immutable"),
    ("r_index_documents", "r_index_documents_immutable"),
    ("r_index_preparations", "r_index_content_immutable"),
    ("fact_revisions", "trg_fact_revision_immutable"),
    ("fact_revision_meta", "trg_fact_revision_meta_immutable"),
    ("knowledge_entity_events", "trg_entity_event_immutable"),
    ("card_version_fact_provenance", "trg_card_version_fact_provenance_immutable"),
)


def _wipe_tables(sql: str) -> list[str]:
    """migration 의 `delete from <표>;` 대상(조건 없는 전체 삭제)."""
    return re.findall(r"^delete from (\w+);", sql, flags=re.M)


async def _counts(db, tables) -> dict[str, int]:
    # 표 이름은 이 파일의 상수·migration 파일에서만 온다(외부 입력 아님)
    return {t: int(await db.fetchval(f"select count(*) from {t}")) for t in tables}


async def _wipe_fixture(db, w: NS, card_id: int, version_id: int) -> None:
    """migration 이 다룰 연결을 채운다 — 로드맵 항목·학습 기록·점주 답변 카드·체크리스트."""
    category = await db.fetchval(
        "select category_id from task_categories where store_id=$1 and category_name='기타'",
        w.store)
    stage = await db.fetchval(
        "insert into roadmap_stages (store_id, stage_name, stage_order, category_id) "
        "values ($1,'합성 a 단계',(select coalesce(max(stage_order),0)+1 from roadmap_stages "
        "where store_id=$1),$2) returning stage_id", w.store, category)
    item = await db.fetchval(
        "insert into roadmap_items (stage_id, card_id, item_name, category_id, "
        "published_version_id) values ($1,$2,'합성 a 항목',$3,$4) returning item_id",
        stage, card_id, category, version_id)
    await db.execute(
        "insert into learning_progress (member_id, item_id, status, completed_at, "
        "completed_version_id) values ($1,$2,'DONE',now(),$3)", w.member, item, version_id)
    await db.execute(
        "update owner_answers set card_id=$1 where answer_id = (select a.answer_id "
        "from owner_answers a join pending_questions q on q.question_id=a.question_id "
        "where q.store_id=$2 order by a.answer_id limit 1)", card_id, w.store)
    await db.execute(
        "insert into checklist_checks (store_id, business_date, card_version_id, line_no, "
        "checked, updated_by) values ($1, current_date, $2, 1, true, $3)",
        w.store, version_id, w.user)
    await db.execute(
        "insert into checklist_check_events (store_id, business_date, card_version_id, "
        "line_no, checked, user_id) values ($1, current_date, $2, 1, true, $3)",
        w.store, version_id, w.user)
    await db.execute(
        "insert into checklist_submissions (store_id, business_date, user_id, total_lines, "
        "done_lines) values ($1, current_date, $2, 1, 1) on conflict do nothing",
        w.store, w.user)


async def _run_wipe(db, sql: str) -> None:
    """migration 파일을 그대로 실행한다. 실패하면 열린 트랜잭션을 되돌리고 예외를 올린다."""
    try:
        await db.execute(sql)
    except Exception:
        if db.is_in_transaction():
            await db.execute("rollback")
        raise


async def _scenario_a(pool, db, answer_card: tuple[NS, int, int]) -> None:
    check = _checker("a")
    sql = WIPE_SQL.read_text(encoding="utf-8")
    wipe_tables = _wipe_tables(sql)
    w, card_id, version_id = answer_card
    await _wipe_fixture(db, w, card_id, version_id)

    before_keep = await _counts(db, KEEP_TABLES)
    before_wipe = await _counts(db, wipe_tables)
    filled = ("r_answer_citations", "r_answer_receipts", "knowledge_snapshots",
              "snapshot_card_versions", "r_index_documents", "r_index_publications",
              "fact_revisions", "knowledge_cards", "card_versions", "card_version_blocks",
              "sources", "source_facts", "ingest_jobs", "owner_answer_sources",
              "checklist_checks", "checklist_check_events")
    check("a 리허설 전 지울 표에 데이터가 있다",
          all(before_wipe[t] > 0 for t in filled)
          and await db.fetchval("select count(*) from operations where operation='PUBLISH'") > 0
          and await db.fetchval("select count(*) from stores "
                                "where guide_completed_at is not null") > 0)

    # a-0 평가 기록이 있으면 멈추고 아무것도 지우지 않는다
    job = await db.fetchrow("select store_id, job_id from ingest_jobs order by job_id limit 1")
    evaluation = await db.fetchval(
        "insert into quality_evaluations (store_id, job_id, evaluator_id, prompt_version) "
        "values ($1,$2,$3,'synthetic-wa-a') returning evaluation_id",
        job["store_id"], job["job_id"], w.user)
    try:
        await _run_wipe(db, sql)
        stopped = False
    except Exception as exc:  # asyncpg RaiseError
        stopped = "quality_evaluations" in str(exc) and "1회 삭제를 멈춘다" in str(exc)
    check("a-0 평가 기록 행이 있으면 migration 이 예외로 멈춘다", stopped)
    check("a-0 롤백 — 남길 표·지울 표 행 수 그대로",
          await _counts(db, KEEP_TABLES) == {**before_keep,
                                              "quality_evaluations":
                                                  before_keep["quality_evaluations"] + 1}
          and await _counts(db, wipe_tables) == before_wipe
          and not db.is_in_transaction())
    await db.execute("delete from quality_evaluations where evaluation_id=$1", evaluation)

    # a-1 실제 리허설
    await _run_wipe(db, sql)
    check("a-1 남길 표 행 수 불변", await _counts(db, KEEP_TABLES) == before_keep)
    after_wipe = await _counts(db, wipe_tables)
    check("a-1 지울 표 전부 0행", all(n == 0 for n in after_wipe.values())
          and len(after_wipe) >= 50)
    check("a-1 공개 멱등 기록(PUBLISH·r-initial-empty) 없음",
          await db.fetchval("select count(*) from operations where operation='PUBLISH'") == 0)
    check("a-1 공개 포인터 행은 남고 current_snapshot_id 는 모두 null",
          await db.fetchval("select count(*) from knowledge_publications "
                            "where current_snapshot_id is not null") == 0)
    check("a-1 roadmap_items·owner_answers·learning_progress 의 카드 연결 null",
          await db.fetchval("select count(*) from roadmap_items "
                            "where card_id is not null or published_version_id is not null") == 0
          and await db.fetchval("select count(*) from owner_answers "
                                "where card_id is not null") == 0
          and await db.fetchval("select count(*) from learning_progress "
                                "where completed_version_id is not null") == 0
          and await db.fetchval("select count(*) from access_logs "
                                "where card_id is not null") == 0)
    check("a-1 stores.guide_completed_at 모두 null",
          await db.fetchval("select count(*) from stores "
                            "where guide_completed_at is not null") == 0)
    enabled = {(r["tbl"], r["tgname"]): r["tgenabled"] for r in await db.fetch(
        "select tgrelid::regclass::text as tbl, tgname, tgenabled::text as tgenabled from pg_trigger "
        "where not tgisinternal")}
    check("a-1 불변 트리거 9개 다시 켜짐(tgenabled O)",
          all(enabled.get(key) == "O" for key in IMMUTABLE_TRIGGERS))

    # a-2 지운 뒤 첫 직원 질문 — 빈 공개판 → 근거 없음 이관
    with patch("app.reg.index_preparation.recorded_embeddings", _vectors):
        await ensure_initial_publication(pool, store_id=w.store, member_id=w.member,
                                         user_id=w.user)
    snapshot_id = await db.fetchval(
        "select current_snapshot_id from knowledge_publications where store_id=$1", w.store)
    check("a-2 빈 공개판 생성(current_snapshot_id 있음·카드 0)",
          snapshot_id is not None and await db.fetchval(
              "select count(*) from snapshot_card_versions where store_id=$1 and snapshot_id=$2",
              w.store, snapshot_id) == 0)
    question = "음료Z HOT 물 얼마나?"
    found = await hybrid_search(pool, store_id=w.store, question=question,
                                query_vector=[1.0] + [0.0] * 1535)
    decision = decide(found, store_id=w.store, question=question)
    check("a-2 근거 없음 → ESCALATE",
          found.snapshot.snapshot_id == str(snapshot_id) and not found.snapshot.cards
          and decision.plan.action == "ESCALATE")

    # a-3 지울 것이 거의 없는 DB 에서 한 번 더 — 오류 없음
    await _run_wipe(db, sql)
    check("a-3 재실행 무해(오류 없음·지울 표 0행)",
          all(n == 0 for n in (await _counts(db, wipe_tables)).values()))


async def verify(pool, db) -> None:
    answer_card = await _scenario_b(pool, db)
    await _scenario_c(pool, db)
    await _scenario_c6(pool, db)
    await _scenario_c7(pool, db)
    await _scenario_d(pool, db, answer_card)
    # (a) 는 DB 전체를 지우므로 맨 마지막이다
    await _scenario_a(pool, db, answer_card)
    print("PASS WA all scenarios")
