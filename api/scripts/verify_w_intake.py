"""실제 DB: Phase B 입구 분류 합성 종단 검증. 분류·추출·임베딩·Storage 는 대역(비용 0).

verify_r_schema_rebuild 가 부른다. 시나리오마다 새 합성 매장을 만든다.
  i-1 섞인 docx 업로드 → 판정 1행(원문 없음)·잡담 글은 추출 입력에 없음·공지 사실은 INTAKE_NOTICE·나머지 카드
  i-2 무관 자료(NONE) → 원장 0·작업 NO_RESULT + INTAKE_NONE 메시지·추출 0회
  i-3 분류 실패 → 자료 FAILED(판정 0행) → 다시 처리하면 판정 1행·DONE
  i-4 추출 실패 뒤 재처리 → 분류 다시 안 부름·판정 행 수 불변
  i-5 점주 답변 글 + 첨부 2개 → 분류 1회·판정 3행(OWNER_ANSWER)·답변 PUBLISHED·첨부 작업 1개 →
      작업 처리 때 분류 0회·첨부 카드는 공개 안 됨
  i-6 답변 처리 뒤 보충 첨부 → 작업 즉시 생성·같은 첨부 두 번이면 작업 1개
  i-7 매장 격리 — 다른 매장 질문 404·기록/첨부 표 매장 불일치 insert 는 트리거 예외
  i-8 칩 허용값 check·ext 는 원장에만(content_hash 불변)
  i-9 공개 카드 대상의 공지 사실 → 새 초안 없음·INTAKE_NOTICE
  i-10 다른 자료로 이미 공개된 사실을 공지가 다시 말함 → 그 occurrence 는 INTAKE_NOTICE(LINKED 아님)·
       공개 카드 새 판 없음(Task 9 판정: 공지 보류는 occurrence 단위)
  i-11 평가 실행(extraction_run_id 있음)은 분류·라우팅을 건너뛴다(Task 9 판정)
  i-12 공지 보류는 매장 전체 기준(최종 리뷰 I1) — 카드 없는 대상의 공지 업로드 뒤 같은 대상의
       레시피 업로드·점주 답변이 와도 공지 사실은 새 카드에 없고 공지 occurrence 는 INTAKE_NOTICE
  i-13 NONE 판정 무결과 자료(error_code INTAKE_NONE) — 작업 재시도(include_no_result)는 덮지 않고
       NONE 그대로, 자료별 그래도 추출하기(extract-anyway)는 분류 0회·덮은 판정 1행(owner-override·
       근거 REGISTERED_DEFAULT)·추출되어 카드. 다른 매장 404·직원 403·처리 중 409(후속 1)
  i-14 섞인 작업(카드 나온 파일 + 무관 파일 둘, 작업 SUCCEEDED)에서 무관 파일 하나만 그래도 추출 →
       그 파일만 다시 처리(추출 입력은 그 파일 글뿐)·다른 무관 파일은 NO_RESULT 그대로·
       덮은 로직은 NONE 다음 순위(NEXT_RANKED)·카드 나온 파일 409(후속 1)

설정은 두 겹이다. app.config·pipeline·intake_route 의 설정은 ingest_mode=real(다운로드·docx
읽기·훑기가 실제로 돈다), extract 의 설정은 mock(조립은 mock 구현)이다. 유료 호출은 0이다 —
분류(`classify.measured_generate`)·추출(`extract_facts`)·임베딩·Storage 다운로드는 대역이고,
Gemini 호출 경로(`gemini._call`)는 불리면 예외로 멈춘다.
출력 줄 머리는 `PASS WB <시나리오 id> <설명>`.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg

from _fact_card_fixture import _mock_settings, _vectors, assertion, publish_card, seed_fact_card
from app.cards import owner_answer_worker
from app.config import get_settings
from app.errors import ApiError
from app.ingest import extract, job_worker, pipeline
from app.ingest import job_repository as job_repo
from app.ingest import repository as repo
from app.ingest.extract import gemini
from app.ingest.intake import classify as intake_classify
from app.ingest.intake import route as intake_route
from app.ingest.repository import fact_content_hash
from app.ingest.router import (attach_owner_answer_file, extract_source_anyway,
                               retry_ingest_job)
from app.ingest.schemas import AttachOwnerAnswerRequest, FactExtractionResult
from app.learn.owner_delivery import submit_owner_answer
from tests.test_wb_docx import _p, _tbl, make_docx
from verify_w_fact_only import _store

FILES: dict[str, bytes] = {}
CALLS = NS(classify=0, extract_texts=[])


def _checker(scenario: str):
    def check(name: str, ok: bool) -> None:
        assert ok, f"WB {scenario} {name}"
        print(f"PASS WB {scenario} {name}")
    return check


def _docx_bytes(body: str) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        return make_docx(Path(d), body).read_bytes()


async def _download(source_id, file_url):
    """Storage 다운로드 대역 — 메모리 파일을 작업 폴더에 쓴다."""
    from app.ingest.preprocess import storage
    path = storage.workdir(source_id) / Path(file_url).name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(FILES[file_url])
    return path


def _logic_of(text: str) -> str:
    if "공지" in text:
        return "NOTICE"
    if "잡담" in text:
        return "NONE"
    if "오픈" in text:
        return "PROCEDURE"
    return "RECIPE"


def _classifier(*, fail: Exception | None = None):
    """분류 대역 — 프롬프트의 `### <후보> (` 아래 글에서 낱말을 보고 판정한다."""
    async def fake(spec, prompt, images, schema, **kw):
        if fail is not None:
            raise fail
        CALLS.classify += 1
        parts = re.split(r"^### (\S+) \(", prompt, flags=re.M)[1:]
        sections = [{"candidate_id": cid, "ranking": [{"logic": _logic_of(body), "score": 0.9}],
                     "reason": "합성"} for cid, body in zip(parts[0::2], parts[1::2])]
        return schema.model_validate({"sections": sections})
    return fake


# 입력 글에 이 열쇠 문장이 있으면 그 사실을 낸다
FACTS = {
    "의자 내리기": assertion("p1", "오픈 절차", "절차 단계", "의자 내리기"),
    "음료Z | 샷 2": assertion("r1", "음료Z", "샷", "2", unit="샷"),
    "토요일 휴무": assertion("n1", "매장", "휴무", "토요일"),
    "음료Z 할인": assertion("n2", "음료Z", "할인", "10", unit="%"),
    "음료Y 시럽": assertion("y1", "음료Y", "시럽", "1", unit="펌프"),
    "음료X | 물 200": assertion("x1", "음료X", "물", "200", unit="ml"),
    "음료W | 얼음 3": assertion("w1", "음료W", "얼음", "3", unit="개"),
    "음료Y 할인": assertion("n3", "음료Y", "할인", "20", unit="%"),
}


def _extractor(*, fail: Exception | None = None):
    async def fake(*, source_id, text, **kw):
        if fail is not None:
            raise fail
        CALLS.extract_texts.append(text)
        found = [a.model_copy(update={"evidence": a.evidence.model_copy(
                     update={"source_id": source_id})})
                 for key, a in FACTS.items() if key in text]
        return FactExtractionResult(assertions=found)
    return fake


async def _no_paid_call(*a, **kw):
    raise AssertionError("유료 모델 호출 경로에 들어왔다 — 대역이 빠졌다")


def _patches(pool, *, classify=None, extracting=None):
    real = get_settings().model_copy(update={"ingest_mode": "real", "intake_min_section_chars": 0})
    mock = _mock_settings()
    return [
        patch("app.config.get_settings", lambda: real),
        patch.object(pipeline, "get_settings", lambda: real),
        patch.object(intake_route, "get_settings", lambda: real),
        patch.object(extract, "get_settings", lambda: mock),
        patch.object(pipeline, "get_pool", lambda: pool),
        patch.object(job_worker, "get_pool", lambda: pool),
        patch.object(pipeline.storage, "download", _download),
        patch.object(intake_classify, "measured_generate", classify or _classifier()),
        patch("app.ingest.extract.extract_facts", extracting or _extractor()),
        patch.object(gemini, "_call", _no_paid_call),
        patch("app.reg.index_preparation.recorded_embeddings", _vectors),
        patch.object(job_worker, "create_ingest_completed_notification", AsyncMock()),
        patch.object(job_worker, "deliver_notification", AsyncMock()),
    ]


class _Within:
    """여러 patch 를 한 번에 연다."""

    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False


async def _docx_source(db, w, body: str, *, hints=()) -> int:
    url = f"{w.store}/scan/{uuid4().hex}.docx"
    FILES[url] = _docx_bytes(body)
    sid = int(await db.fetchval(
        "insert into sources (store_id, uploaded_by, source_type, title, file_url, status, "
        "owner_hints) values ($1,$2,'SCAN','합성 문서',$3,'UPLOADED',$4) returning source_id",
        w.store, w.user, url, list(hints) or None))
    await repo.create_scan(db, sid, doc_type="DOCX", doc_category=None, page_count=1)
    return sid


async def _decisions(db, store, source):
    return await db.fetch(
        "select entry, owner_answer_id, source_logic, sample_summary::text as summary, "
        "logical_call_id from intake_route_decisions where store_id=$1 and source_id=$2 "
        "order by decision_id", store, source)


async def _facts_by_subject(db, store, source):
    """이 자료 occurrence 의 (처분, 사유) — 사실 판의 대상 이름별."""
    rows = await db.fetch(
        "select r.subject, o.disposition, o.reason from fact_occurrences o "
        "join fact_revisions r on r.store_id = o.store_id "
        "  and r.fact_revision_id = o.fact_revision_id "
        "where o.store_id=$1 and o.source_id=$2", store, source)
    return {r["subject"]: (r["disposition"], r["reason"]) for r in rows}


async def _status(db, store, source):
    return await db.fetchval("select status from sources where store_id=$1 and source_id=$2",
                             store, source)


async def _job(db, w, sources: list[int]) -> int:
    row = await job_repo.create_job(
        db, w.store, w.user, title="합성 작업", source_ids=sources,
        category_version=int(await db.fetchval(
            "select category_version from stores where store_id=$1", w.store)),
        prompt_version="extract-cards-v1", settings={"ingest_mode": "real"},
        idempotency_key=None)
    return int(row["job_id"])


async def _card_versions(db, store, card_id) -> int:
    return int(await db.fetchval("select count(*) from card_versions where store_id=$1 "
                                 "and card_id=$2", store, card_id))


MIXED = (_p("오픈 절차", "Heading1") + _p("오픈 하면 의자 내리기")
         + _p("레시피", "Heading1") + _tbl([["음료Z", "샷 2"]])
         + _p("잡담", "Heading1") + _p("어제 회식 재밌었다")
         + _p("공지", "Heading1") + _p("이번 주 토요일 휴무"))


async def _scenario_i1(pool, db) -> None:
    check = _checker("i-1")
    w = await _store(db)
    sid = await _docx_source(db, w, MIXED)
    CALLS.classify, CALLS.extract_texts = 0, []
    with _Within(_patches(pool)):
        await pipeline.process_source(w.store, sid)
    rows = await _decisions(db, w.store, sid)
    check("판정 1행·UPLOAD·원문 없음",
          len(rows) == 1 and rows[0]["entry"] == "UPLOAD" and "회식" not in rows[0]["summary"]
          and rows[0]["logical_call_id"].endswith(":classify"))
    check("분류 1회", CALLS.classify == 1)
    check("잡담 글은 추출 입력에 없다", CALLS.extract_texts
          and not any("회식" in t for t in CALLS.extract_texts))
    facts = await _facts_by_subject(db, w.store, sid)
    check("공지 사실은 INTAKE_NOTICE 검수 대기",
          facts.get("매장") == ("REVIEW_PENDING", "INTAKE_NOTICE"))
    check("레시피·절차 사실은 카드로", facts.get("음료Z", ("",))[0] == "LINKED"
          and facts.get("오픈 절차", ("",))[0] == "LINKED")
    check("자료 DONE", await _status(db, w.store, sid) == "DONE")


async def _scenario_i2(pool, db) -> None:
    check = _checker("i-2")
    w = await _store(db)
    sid = await _docx_source(db, w, _p("잡담", "Heading1") + _p("어제 회식 재밌었다"))
    job_id = await _job(db, w, [sid])
    CALLS.extract_texts = []
    with _Within(_patches(pool)):
        await job_worker.process_ingest_job(w.store, job_id)
    row = await db.fetchrow("select status, error_message from ingest_job_sources "
                            "where store_id=$1 and job_id=$2", w.store, job_id)
    check("작업 NO_RESULT·메시지", row["status"] == "NO_RESULT"
          and row["error_message"] == job_worker.INTAKE_NONE_MESSAGE)
    check("추출 0회·원장 0", CALLS.extract_texts == [] and await db.fetchval(
        "select count(*) from source_facts where store_id=$1 and source_id=$2", w.store, sid) == 0)


async def _scenario_i3_i4(pool, db) -> None:
    check = _checker("i-3")
    w = await _store(db)
    sid = await _docx_source(db, w, _p("레시피", "Heading1") + _tbl([["음료Z", "샷 2"]]))
    with _Within(_patches(pool, classify=_classifier(fail=RuntimeError("합성 503")))):
        await pipeline.process_source(w.store, sid)
    status, message = await db.fetchrow(
        "select status, error_message from sources where store_id=$1 and source_id=$2", w.store, sid)
    check("분류 실패 → FAILED·판정 0행", status == "FAILED" and "분류" in (message or "")
          and len(await _decisions(db, w.store, sid)) == 0)
    with _Within(_patches(pool)):
        await pipeline.process_source(w.store, sid)
    check("다시 처리 → 판정 1행·DONE", len(await _decisions(db, w.store, sid)) == 1
          and await _status(db, w.store, sid) == "DONE")

    check = _checker("i-4")
    sid = await _docx_source(db, w, _p("레시피 둘", "Heading1") + _tbl([["음료Z", "샷 2"]]))
    with _Within(_patches(pool, extracting=_extractor(fail=RuntimeError("합성 추출 실패")))):
        await pipeline.process_source(w.store, sid)
    before = len(await _decisions(db, w.store, sid))
    failed = await _status(db, w.store, sid)
    with _Within(_patches(pool, classify=_classifier(fail=AssertionError("분류를 다시 부르면 안 된다")))):
        await pipeline.process_source(w.store, sid)
    check("추출 실패 → FAILED·판정 1행은 남는다", failed == "FAILED" and before == 1)
    check("재처리는 저장된 판정을 쓴다(분류 0회)·DONE",
          len(await _decisions(db, w.store, sid)) == 1
          and await _status(db, w.store, sid) == "DONE")


class _Background:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args):
        self.tasks.append((fn, args))


def _owner_claims(w):
    return {"user_id": w.user, "store_id": w.store, "role": "OWNER"}


async def _scenario_i5_i6(pool, db) -> None:
    check = _checker("i-5")
    w = await _store(db)
    qid = await db.fetchval(
        "insert into pending_questions (store_id, member_id, question_text, contract_version, "
        "semantic_key) values ($1,$2,'음료Y 시럽 몇 번?','v2','synthetic-wb-i5') "
        "returning question_id", w.store, w.member)
    a1 = await _docx_source(db, w, _tbl([["음료X", "물 200ml"]]))
    a2 = await _docx_source(db, w, _tbl([["음료W", "얼음 3개"]]))
    for sid in (a1, a2):
        out = await attach_owner_answer_file(qid, AttachOwnerAnswerRequest(source_id=sid),
                                             _Background(), db, _owner_claims(w))
        assert out.created and out.job_id is None, out
    reply = await submit_owner_answer(pool, store_id=w.store, member_id=w.member, question_id=qid,
                                      request_id="wb-i5-answer", answer="음료Y 시럽 1펌프",
                                      expected_revision=0)
    answer_id = int(reply["owner_answer_id"])
    spawned: list = []
    CALLS.classify = 0
    with _Within(_patches(pool)), patch.object(owner_answer_worker, "_spawn_job",
                                               lambda s, j: spawned.append(j)):
        status = await owner_answer_worker.process_next_owner_event(pool, store_id=w.store)
    rows = await db.fetch("select source_id, entry, owner_answer_id from intake_route_decisions "
                          "where store_id=$1 and owner_answer_id=$2", w.store, answer_id)
    check("분류 1회·판정 3행 OWNER_ANSWER", CALLS.classify == 1 and len(rows) == 3
          and {r["entry"] for r in rows} == {"OWNER_ANSWER"}
          and {a1, a2} <= {r["source_id"] for r in rows})
    check("답변 글 결과 PUBLISHED", status == "PUBLISHED")
    job = await job_repo.find_by_idempotency(db, w.store, f"owner-answer:{answer_id}:attachments")
    check("첨부 작업 1개·R 보고 뒤 시작 요청", job is not None and spawned == [int(job["job_id"])])
    with _Within(_patches(pool)):
        await job_worker.process_ingest_job(w.store, int(job["job_id"]))
    published = await db.fetchval(
        "select count(*) from fact_occurrences o join knowledge_cards k "
        "on k.store_id = o.store_id and k.card_id = o.card_id "
        "where o.store_id=$1 and o.source_id = any($2::bigint[]) "
        "and k.published_version_id is not null",
        w.store, [a1, a2])
    check("작업은 분류를 다시 안 부르고 첨부 카드는 공개 안 됨",
          CALLS.classify == 1 and published == 0
          and len(await _facts_by_subject(db, w.store, a1)) == 1
          and len(await _facts_by_subject(db, w.store, a2)) == 1)

    check = _checker("i-6")
    a3 = await _docx_source(db, w, _tbl([["음료Z", "샷 2"]]))
    bg = _Background()
    first = await attach_owner_answer_file(qid, AttachOwnerAnswerRequest(source_id=a3), bg, db,
                                           _owner_claims(w))
    again = await attach_owner_answer_file(qid, AttachOwnerAnswerRequest(source_id=a3), bg, db,
                                           _owner_claims(w))
    jobs = await db.fetchval("select count(*) from ingest_jobs where store_id=$1 "
                             "and idempotency_key=$2", w.store, f"owner-answer-attach:{a3}")
    check("보충 첨부는 바로 작업·두 번 붙여도 작업 1개",
          first.job_id is not None and first.created and not again.created and jobs == 1
          and len(bg.tasks) == 1)


async def _scenario_i7(pool, db) -> None:
    check = _checker("i-7")
    w, other = await _store(db), await _store(db)
    qid = await db.fetchval(
        "insert into pending_questions (store_id, member_id, question_text, contract_version, "
        "semantic_key) values ($1,$2,'질문','v2','synthetic-wb-i7') returning question_id",
        w.store, w.member)
    foreign = await _docx_source(db, other, _p("글"))
    try:
        await attach_owner_answer_file(qid, AttachOwnerAnswerRequest(source_id=foreign),
                                       _Background(), db, _owner_claims(other))
        rejected = False
    except ApiError as e:
        rejected = e.status_code == 404
    check("다른 매장 질문으로 첨부 → 404", rejected)
    for sql, args in [
        ("insert into owner_answer_attachments (store_id, pending_question_id, source_id) "
         "values ($1,$2,$3)", (w.store, qid, foreign)),
        ("insert into intake_route_decisions (store_id, source_id, entry, normalizer, "
         "sample_summary, sample_hash, model_sections, decisions, source_decision, source_logic) "
         "values ($1,$2,'UPLOAD','DOC_TEXT','{}',repeat('0',64),'{}','[]','{}','RECIPE')",
         (w.store, foreign)),
    ]:
        try:
            async with db.transaction():
                await db.execute(sql, *args)
            blocked = False
        except asyncpg.RaiseError:
            blocked = True
        check(f"매장 불일치 insert 차단 ({sql.split()[2]})", blocked)


async def _scenario_i8(pool, db) -> None:
    check = _checker("i-8")
    w = await _store(db)
    sid = await _docx_source(db, w, _p("글"), hints=("RECIPE", "NOTICE"))
    check("칩 저장", await db.fetchval("select owner_hints from sources where store_id=$1 "
                                     "and source_id=$2", w.store, sid) == ["RECIPE", "NOTICE"])
    try:
        async with db.transaction():
            await db.execute("update sources set owner_hints = array['NONE'] "
                             "where store_id=$1 and source_id=$2", w.store, sid)
        refused = False
    except asyncpg.CheckViolationError:
        refused = True
    check("허용 밖 칩 거절", refused)
    with_ext = assertion("e1", "오픈 절차", "절차 단계", "의자 내리기")
    with_ext.set_ext({"timing": "OPEN"})
    plain = assertion("e1", "오픈 절차", "절차 단계", "의자 내리기")
    other = await _docx_source(db, w, _p("글 둘"))
    async with db.transaction():
        await pipeline._persist_ledger(db, w.store, sid, "SCAN", [with_ext])
        await pipeline._persist_ledger(db, w.store, other, "SCAN", [plain])
    row = await db.fetchrow("select ext, content_hash from source_facts where store_id=$1 "
                            "and source_id=$2", w.store, sid)
    plain_row = await db.fetchrow("select ext, content_hash from source_facts where store_id=$1 "
                                  "and source_id=$2", w.store, other)
    ext = row["ext"] if isinstance(row["ext"], dict) else json.loads(row["ext"])
    check("ext 는 원장에 그대로", ext == {"timing": "OPEN"} and plain_row["ext"] is None)
    check("ext 는 content_hash 에 안 들어간다",
          row["content_hash"] == plain_row["content_hash"] == fact_content_hash(
              plain.subject, plain.as_variant(), plain.attribute, plain.value,
              unit=plain.unit or None, polarity=plain.polarity,
              conditions=list(plain.conditions), exceptions=list(plain.exceptions)))


async def _published_card(pool, db, w) -> tuple[int, int]:
    """음료Z 샷 2 사실 카드를 만들어 공개한다. (card_id, 판 수)."""
    card_id, _ = await seed_fact_card(pool, store_id=w.store, owner_user_id=w.user,
                                      assertions=[assertion("f1", "음료Z", "샷", "2", unit="샷")])
    result = await publish_card(pool, store_id=w.store, member_id=w.member, actor_user_id=w.user,
                                card_id=card_id)
    assert result.status == "PUBLISHED", result
    return card_id, await _card_versions(db, w.store, card_id)


async def _scenario_i9(pool, db) -> None:
    check = _checker("i-9")
    w = await _store(db)
    card_id, versions = await _published_card(pool, db, w)
    sid = await _docx_source(db, w, _p("공지", "Heading1") + _p("이번 주 음료Z 할인 10% 공지"))
    with _Within(_patches(pool)):
        await pipeline.process_source(w.store, sid)
    check("공개 카드 대상의 공지 사실 → 새 초안 없음",
          await _card_versions(db, w.store, card_id) == versions
          and await _status(db, w.store, sid) == "DONE")
    check("그 사실은 INTAKE_NOTICE",
          (await _facts_by_subject(db, w.store, sid)).get("음료Z") == ("REVIEW_PENDING",
                                                                       "INTAKE_NOTICE"))


async def _scenario_i10(pool, db) -> None:
    check = _checker("i-10")
    w = await _store(db)
    card_id, versions = await _published_card(pool, db, w)
    published = await db.fetchval("select published_version_id from knowledge_cards "
                                  "where store_id=$1 and card_id=$2", w.store, card_id)
    sid = await _docx_source(db, w, _p("공지", "Heading1") + _tbl([["음료Z", "샷 2"]]))
    with _Within(_patches(pool)):
        await pipeline.process_source(w.store, sid)
    rows = await db.fetch("select disposition, reason, card_id from fact_occurrences "
                          "where store_id=$1 and source_id=$2", w.store, sid)
    check("공개 사실을 다시 말한 공지 occurrence 는 INTAKE_NOTICE·LINKED 아님",
          len(rows) == 1 and rows[0]["disposition"] == "REVIEW_PENDING"
          and rows[0]["reason"] == "INTAKE_NOTICE")
    check("공개 카드 새 판 없음·공개판 그대로",
          await _card_versions(db, w.store, card_id) == versions
          and await db.fetchval("select published_version_id from knowledge_cards "
                                "where store_id=$1 and card_id=$2", w.store, card_id) == published)


async def _scenario_i11(pool, db) -> None:
    check = _checker("i-11")
    w = await _store(db)
    sid = await _docx_source(db, w, MIXED)
    CALLS.classify, CALLS.extract_texts = 0, []
    with _Within(_patches(pool)):
        await pipeline.process_source(w.store, sid, cost_purpose="EVALUATION")
    check("평가 실행은 분류 0회·판정 0행", CALLS.classify == 0
          and len(await _decisions(db, w.store, sid)) == 0)
    check("평가 실행은 거르지 않은 전체 글을 뽑는다",
          len(CALLS.extract_texts) == 1 and "회식" in CALLS.extract_texts[0])


async def _card_predicates(db, store) -> set[str]:
    """이 매장 모든 카드 판 블록에 담긴 사실의 속성."""
    rows = await db.fetch(
        "select distinct r.predicate from card_block_facts b "
        "join fact_revisions r on r.store_id = b.store_id "
        "  and r.fact_revision_id = b.fact_revision_id where b.store_id = $1", store)
    return {r["predicate"] for r in rows}


async def _scenario_i12(pool, db) -> None:
    check = _checker("i-12")
    # (가) 공지 업로드(카드 없음) → 같은 대상 레시피 업로드
    w = await _store(db)
    notice = await _docx_source(db, w, _p("공지", "Heading1") + _p("이번 주 음료Z 할인 10% 공지"))
    with _Within(_patches(pool)):
        await pipeline.process_source(w.store, notice)
    check("공지만 있는 대상은 카드 없음", await db.fetchval(
        "select count(*) from knowledge_cards where store_id=$1", w.store) == 0)
    recipe = await _docx_source(db, w, _p("레시피", "Heading1") + _tbl([["음료Z", "샷 2"]]))
    with _Within(_patches(pool)):
        await pipeline.process_source(w.store, recipe)
    preds = await _card_predicates(db, w.store)
    check("뒤 레시피 업로드의 새 카드에 공지 사실 없음", "샷" in preds and "할인" not in preds
          and (await _facts_by_subject(db, w.store, recipe)).get("음료Z", ("",))[0] == "LINKED")
    check("공지 occurrence 는 INTAKE_NOTICE 그대로",
          (await _facts_by_subject(db, w.store, notice)).get("음료Z")
          == ("REVIEW_PENDING", "INTAKE_NOTICE"))

    # (나) 공지 업로드(카드 없음) → 같은 대상 점주 답변
    w = await _store(db)
    notice = await _docx_source(db, w, _p("공지", "Heading1") + _p("이번 주 음료Y 할인 20% 공지"))
    with _Within(_patches(pool)):
        await pipeline.process_source(w.store, notice)
    qid = await db.fetchval(
        "insert into pending_questions (store_id, member_id, question_text, contract_version, "
        "semantic_key) values ($1,$2,'음료Y 시럽 몇 번?','v2','synthetic-wb-i12') "
        "returning question_id", w.store, w.member)
    await submit_owner_answer(pool, store_id=w.store, member_id=w.member, question_id=qid,
                              request_id="wb-i12-answer", answer="음료Y 시럽 1펌프",
                              expected_revision=0)
    with _Within(_patches(pool)), patch.object(owner_answer_worker, "_spawn_job",
                                               lambda s, j: None):
        status = await owner_answer_worker.process_next_owner_event(pool, store_id=w.store)
    preds = await _card_predicates(db, w.store)
    check(f"점주 답변 결과({status})의 카드에 공지 사실 없음", "시럽" in preds and "할인" not in preds)
    published = await db.fetchval(
        "select count(*) from card_block_facts b join knowledge_cards c "
        "on c.store_id = b.store_id and c.published_version_id = b.card_version_id "
        "join fact_revisions r on r.store_id = b.store_id "
        "  and r.fact_revision_id = b.fact_revision_id "
        "where b.store_id = $1 and r.predicate = '할인'", w.store)
    check("공지 사실은 공개되지 않음", published == 0)
    check("공지 occurrence 는 INTAKE_NOTICE 그대로",
          (await _facts_by_subject(db, w.store, notice)).get("음료Y")
          == ("REVIEW_PENDING", "INTAKE_NOTICE"))


def _fixed_classifier(logic: str):
    """모든 후보를 한 로직으로 판정하는 대역."""
    async def fake(spec, prompt, images, schema, **kw):
        CALLS.classify += 1
        ids = re.findall(r"^### (\S+) \(", prompt, flags=re.M)
        return schema.model_validate({"sections": [
            {"candidate_id": cid, "ranking": [{"logic": logic, "score": 0.9}], "reason": "합성"}
            for cid in ids]})
    return fake


async def _job_source(db, store, job_id, source_id):
    return await db.fetchrow("select status, error_code, error_message from ingest_job_sources "
                             "where store_id=$1 and job_id=$2 and source_id=$3",
                             store, job_id, source_id)


async def _override_rows(db, store, source_id):
    return await db.fetch("select entry, model, source_logic, sample_hash, "
                          "model_sections::text as marker from intake_route_decisions "
                          "where store_id=$1 and source_id=$2 order by decision_id",
                          store, source_id)


async def _api_error(coro) -> ApiError | None:
    try:
        await coro
    except ApiError as e:
        return e
    return None


async def _scenario_i13(pool, db) -> None:
    check = _checker("i-13")
    w = await _store(db)
    sid = await _docx_source(db, w, _p("메모", "Heading1") + _tbl([["음료Z", "샷 2"]]))
    job_id = await _job(db, w, [sid])
    CALLS.classify, CALLS.extract_texts = 0, []
    with _Within(_patches(pool, classify=_fixed_classifier("NONE"))):
        await job_worker.process_ingest_job(w.store, job_id)
    row = await _job_source(db, w.store, job_id, sid)
    check("첫 실행 NONE → NO_RESULT·코드 INTAKE_NONE·메시지·추출 0회",
          row["status"] == "NO_RESULT" and row["error_code"] == "INTAKE_NONE"
          and row["error_message"] == job_worker.INTAKE_NONE_MESSAGE and CALLS.extract_texts == [])

    # 작업 재시도(무결과 포함)는 판정을 덮지 않는다 — 저장된 NONE 판정을 재사용해 다시 NONE
    bg = _Background()
    await retry_ingest_job(job_id, bg, db, _owner_claims(w), include_no_result=True)
    with _Within(_patches(pool, classify=_classifier(
            fail=AssertionError("분류를 다시 부르면 안 된다")))):
        await job_worker.process_ingest_job(w.store, job_id)
    row = await _job_source(db, w.store, job_id, sid)
    check("작업 재시도는 덮지 않음(판정 1행·INTAKE_NONE·추출 0회)",
          len(await _override_rows(db, w.store, sid)) == 1 and row["error_code"] == "INTAKE_NONE"
          and CALLS.extract_texts == [])

    other = await _store(db)
    staff = {"user_id": w.user, "store_id": w.store, "role": "STAFF"}
    e404 = await _api_error(extract_source_anyway(job_id, sid, _Background(), db,
                                                  _owner_claims(other)))
    e403 = await _api_error(extract_source_anyway(job_id, sid, _Background(), db, staff))
    check("다른 매장 404·직원 403", e404 is not None and e404.status_code == 404
          and e403 is not None and e403.status_code == 403)

    bg = _Background()
    out = await extract_source_anyway(job_id, sid, bg, db, _owner_claims(w))
    rows = await _override_rows(db, w.store, sid)
    marker = json.loads(rows[-1]["marker"])
    check("덮은 판정 1행 추가(UPLOAD·owner-override·RECIPE·근거 REGISTERED_DEFAULT·표본 hash 그대로)",
          len(rows) == 2 and rows[1]["entry"] == "UPLOAD"
          and rows[1]["model"] == "owner-override" and rows[1]["source_logic"] == "RECIPE"
          and rows[1]["sample_hash"] == rows[0]["sample_hash"]
          and marker["basis"] == "REGISTERED_DEFAULT" and out.source_count == 1
          and len(bg.tasks) == 1)
    again = await _api_error(extract_source_anyway(job_id, sid, _Background(), db,
                                                   _owner_claims(w)))
    check("처리 전 두 번째 요청은 409(판정 행 불변)",
          again is not None and again.status_code == 409
          and again.code == "INGEST_JOB_IN_PROGRESS"
          and len(await _override_rows(db, w.store, sid)) == 2)
    CALLS.classify = 0
    with _Within(_patches(pool, classify=_classifier(
            fail=AssertionError("분류를 다시 부르면 안 된다")))):
        await job_worker.process_ingest_job(w.store, job_id)
    status = (await _job_source(db, w.store, job_id, sid))["status"]
    check("분류 0회로 추출해 카드", CALLS.extract_texts and status == "SUCCEEDED"
          and (await _facts_by_subject(db, w.store, sid)).get("음료Z", ("",))[0] == "LINKED")
    check("판정 행 수 불변(작업 안 재사용)", len(await _decisions(db, w.store, sid)) == 2)


def _ranked_classifier():
    """잡담 후보는 NONE .7 · PROCEDURE .2, 나머지는 _logic_of 로 판정하는 대역."""
    async def fake(spec, prompt, images, schema, **kw):
        CALLS.classify += 1
        parts = re.split(r"^### (\S+) \(", prompt, flags=re.M)[1:]
        sections = []
        for cid, body in zip(parts[0::2], parts[1::2]):
            ranking = ([{"logic": "NONE", "score": 0.7}, {"logic": "PROCEDURE", "score": 0.2}]
                       if "잡담" in body else [{"logic": _logic_of(body), "score": 0.9}])
            sections.append({"candidate_id": cid, "ranking": ranking, "reason": "합성"})
        return schema.model_validate({"sections": sections})
    return fake


async def _scenario_i14(pool, db) -> None:
    check = _checker("i-14")
    w = await _store(db)
    recipe = await _docx_source(db, w, _p("레시피", "Heading1") + _tbl([["음료X", "물 200"]]))
    chat = await _docx_source(db, w, _p("잡담", "Heading1") + _tbl([["음료W", "얼음 3"]]))
    chat2 = await _docx_source(db, w, _p("잡담", "Heading1") + _p("어제 회식 재밌었다"))
    job_id = await _job(db, w, [recipe, chat, chat2])
    CALLS.classify, CALLS.extract_texts = 0, []
    with _Within(_patches(pool, classify=_ranked_classifier())):
        await job_worker.process_ingest_job(w.store, job_id)
    job_status = await db.fetchval("select status from ingest_jobs where store_id=$1 "
                                   "and job_id=$2", w.store, job_id)
    rows = {s: await _job_source(db, w.store, job_id, s) for s in (recipe, chat, chat2)}
    check("섞인 작업 SUCCEEDED·카드 파일 SUCCEEDED·무관 파일 둘 INTAKE_NONE",
          job_status == "SUCCEEDED" and rows[recipe]["status"] == "SUCCEEDED"
          and all(rows[s]["status"] == "NO_RESULT" and rows[s]["error_code"] == "INTAKE_NONE"
                  for s in (chat, chat2)))
    e409 = await _api_error(extract_source_anyway(job_id, recipe, _Background(), db,
                                                  _owner_claims(w)))
    check("카드 나온 파일은 409(INTAKE_NONE 아님)",
          e409 is not None and e409.status_code == 409 and e409.code == "SOURCE_NOT_JUDGED_NONE")

    await extract_source_anyway(job_id, chat, _Background(), db, _owner_claims(w))
    queued = {r["source_id"]: (r["status"], r["error_code"]) for r in await db.fetch(
        "select source_id, status, error_code from ingest_job_sources where store_id=$1 "
        "and job_id=$2", w.store, job_id)}
    marker = json.loads((await _override_rows(db, w.store, chat))[-1]["marker"])
    check("그 파일만 QUEUED·다른 파일 그대로",
          queued == {recipe: ("SUCCEEDED", None), chat: ("QUEUED", None),
                     chat2: ("NO_RESULT", "INTAKE_NONE")})
    check("덮은 로직은 NONE 다음 순위(PROCEDURE·NEXT_RANKED)",
          marker["basis"] == "NEXT_RANKED" and marker["logic"] == "PROCEDURE")
    CALLS.classify, CALLS.extract_texts = 0, []
    with _Within(_patches(pool, classify=_classifier(
            fail=AssertionError("분류를 다시 부르면 안 된다")))):
        await job_worker.process_ingest_job(w.store, job_id)
    rows = {s: await _job_source(db, w.store, job_id, s) for s in (recipe, chat, chat2)}
    check("추출 입력은 그 파일 글뿐(분류 0회)",
          CALLS.classify == 0 and len(CALLS.extract_texts) == 1
          and "음료W" in CALLS.extract_texts[0] and "음료X" not in CALLS.extract_texts[0])
    check("그 파일 카드·다른 무관 파일 NO_RESULT 그대로·카드 파일 그대로",
          rows[chat]["status"] == "SUCCEEDED" and rows[chat2]["error_code"] == "INTAKE_NONE"
          and rows[recipe]["status"] == "SUCCEEDED"
          and (await _facts_by_subject(db, w.store, chat)).get("음료W", ("",))[0] == "LINKED"
          and len(await _decisions(db, w.store, chat2)) == 1)


async def verify(pool, db) -> None:
    await _scenario_i1(pool, db)
    await _scenario_i2(pool, db)
    await _scenario_i3_i4(pool, db)
    await _scenario_i5_i6(pool, db)
    await _scenario_i7(pool, db)
    await _scenario_i8(pool, db)
    await _scenario_i9(pool, db)
    await _scenario_i10(pool, db)
    await _scenario_i11(pool, db)
    await _scenario_i12(pool, db)
    await _scenario_i13(pool, db)
    await _scenario_i14(pool, db)
    print("PASS WB all scenarios")
