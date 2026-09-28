"""실제 DB: 근거 위치(occurrence) 보존(W1-4)을 검증한다. 모델 호출은 전부 합성이다.

verify_r_schema_rebuild 가 만든 새 UUID DB(모든 migration 적용)의 연결과 DSN 만 받는다.
  1. PDF 두 쪽에 같은 사실 → 사실 한 행, 근거 위치 둘(PAGE 1·2), 원래 응답 행을 가리킨다
  2. 입력에 없는 쪽(9쪽)은 자료 전체로 떨어지고, 근거 없는 단위는 기본 설정에서 **값을 남기고**
     판정(check_flags UNGROUNDED_TEXT)만 위치 행에 영속한다
  3. 같은 자료를 다시 처리해도 사실·위치가 늘지 않는다 (unique(fact_id, occurrence_hash))
  4. 카톡 LINE·음성 TIMESTAMP 위치
  5. 다른 매장 — 조회되지 않고, 다른 매장 ID 로 위치를 달지 못하며, 복합 FK 가 매장 교차를 막는다
  6. 사실을 물리적으로 지우는 절차(평가 매장 초기화)에서는 위치가 함께 지워진다
  7. 플래그(extract_locator_hints) 꺼짐 — 요청 스키마는 이전 그대로, 위치 표는 여전히 남고 쪽은 무시된다
  8. 플래그(extract_clear_ungrounded_values) 켬 — 글만 있는 입력의 근거 없는 단위를 비우고 CLEARED 로 남긴다
1~6 은 위치 플래그를 켠 경로다.
"""
import json
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import asyncpg

import app.config
from app.config import Settings
from app.ingest import extract, occurrences, pipeline
from app.ingest import repository as repo
from app.ingest.extract import gemini
from app.ingest.schemas import (ExtractedCard, ExtractedFact, ExtractionResult,
                                FactExtractionResult, LocatedAssertion, LocatedEvidence,
                                LocatedFactExtractionResult)
from verify_w_partial_extraction import _new_source, _seed


PDF_TEXT = ("[1쪽]\n음료Z 는 물 10ml 를 넣는다.\n\n"
            "[2쪽]\n다시 확인: 음료Z 는 물 10ml 를 넣는다.\n음료Y 는 시럽 2 를 넣는다.")


def _facts_json() -> str:
    def fact(ref, subject, attribute, value, unit, original, page):
        return dict(local_ref=ref, original_assertion=original, subject=subject,
                    attribute=attribute, value=value, unit=unit, confidence=.9,
                    evidence=dict(page=page))
    # 모델 대역은 언제나 page 를 보낸다. 꺼짐 스키마는 그 칸을 모르므로 파싱에서 버린다
    return LocatedFactExtractionResult.model_validate({"assertions": [
        fact("f1", "음료Z", "물", "10", "ml", "음료Z 는 물 10ml 를 넣는다.", 1),
        fact("f2", "음료Z", "물", "10", "ml", "다시 확인: 음료Z 는 물 10ml 를 넣는다.", 2),
        # 입력에 없는 쪽 + 지어낸 단위 — 사실은 남는다. 단위는 기본 설정에서 기록만 한다
        fact("f3", "음료Y", "시럽", "2", "펌프", "음료Y 는 시럽 2 를 넣는다.", 9),
    ]}).model_dump_json()


async def verify(db, dsn):
    passed = []

    def check(name, ok):
        assert ok, name
        passed.append(name)
        print("PASS W occurrence", name)

    user, store, _ = await _seed(db)
    _, other_store, _ = await _seed(db)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    real = NS(gemini_api_key="synthetic", gemini_model="gemini-synthetic",
              ingest_mode="real", extract_temperature=0.0, extract_locator_hints=True)
    settings = Settings(_env_file=None, extract_locator_hints=True)
    category = next(iter(await repo.enabled_categories(db, store)))
    calls = []

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        async with pool.acquire() as c:   # 모델 호출 중 연결을 쥐지 않는다 (max_size=1)
            assert await c.fetchval("select 1") == 1
        # 켠 판은 LocatedFactExtractionResult(하위 클래스)로 부른다
        is_extract = schema is not None and issubclass(schema, FactExtractionResult)
        calls.append("EXTRACT" if is_extract else "ASSEMBLE")
        if is_extract:
            return gemini.CallResult(_facts_json(), {}, "STOP")
        card = ExtractedCard(category_name=category, title="음료Z", content="물 10ml",
                             confidence=.9, facts=[ExtractedFact(
                                 object_name="음료Z", attribute="물", value="10",
                                 confidence=.9, ref="f1")])
        return gemini.CallResult(ExtractionResult(cards=[card]).model_dump_json(), {}, "STOP")

    async def new_job(source):
        job_id = await db.fetchval(
            "insert into ingest_jobs (store_id, created_by, title, status, category_version, "
            "prompt_version) values ($1,$2,'근거 위치 검증','EXTRACTING',1,'v1') returning job_id",
            store, user)
        await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                         store, source)
        await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                         "values($1,$2,$3,'QUEUED')", store, job_id, source)
        return job_id

    async def run(source, run_tag, *, hints=True, clear=False):
        job_id = await new_job(source)
        model_settings = real if hints else NS(**(vars(real) | {"extract_locator_hints": False}))
        app_settings = settings if hints else Settings(_env_file=None)
        if clear:
            app_settings = Settings(_env_file=None, extract_locator_hints=hints,
                                    extract_clear_ungrounded_values=True)
        with ExitStack() as stack:
            for obj, name, replacement in [
                (pipeline, "get_pool", lambda: pool),
                (pipeline, "_preprocess", AsyncMock(return_value=(PDF_TEXT, [], []))),
                (pipeline.shutil, "rmtree", lambda *a, **kw: None),
                (app.config, "get_settings", lambda: app_settings),
                (extract, "get_settings", lambda: NS(ingest_mode="real")),
                (gemini, "get_settings", lambda: model_settings),
                (gemini, "_call", fake_call),
            ]:
                stack.enter_context(patch.object(obj, name, replacement))
            await pipeline.process_source(store, source, job_id=job_id, run_tag=run_tag)
        return job_id

    try:
        # 1·2. PDF 두 쪽에 같은 사실
        pdf = await _new_source(db, store, user, "SCAN")
        await run(pdf, 91)
        facts = await db.fetch(
            "select fact_id, subject, unit, locator_type, locator::text as locator "
            "from source_facts where store_id=$1 and source_id=$2 order by fact_id", store, pdf)
        occ = await occurrences.list_occurrences(db, store, source_id=pdf)
        extract_raw = await db.fetchval(
            "select raw_response_id from extraction_raw_responses "
            "where store_id=$1 and source_id=$2 and stage='EXTRACT'", store, pdf)
        state = await db.fetchrow("select status, error_message from sources "
                                  "where store_id=$1 and source_id=$2", store, pdf)
        raws = await db.fetch("select stage, parsed_ok, error, left(response_text, 300) t "
                              "from extraction_raw_responses where store_id=$1 and source_id=$2",
                              store, pdf)
        assert state["status"] == "DONE" and facts, (
            f"처리 실패: {state['status']} {state['error_message']} 사실 {len(facts)} "
            f"응답 {[tuple(r) for r in raws]}")
        z = next(f for f in facts if f["subject"] == "음료Z")
        z_occ = [o for o in occ if o["fact_id"] == z["fact_id"]]
        check("PDF 두 쪽의 같은 사실 → 사실 하나, 근거 위치 둘(PAGE 1·2)",
              len([f for f in facts if f["subject"] == "음료Z"]) == 1
              and sorted((o["locator_type"], o["locator"]) for o in z_occ)
              == [("PAGE", '{"page": 1}'), ("PAGE", '{"page": 2}')]
              and z["locator_type"] == "PAGE" and z["locator"] == '{"page": 1}'
              and all(o["raw_response_id"] == extract_raw for o in z_occ)
              and {o["local_ref"] for o in z_occ} == {"f1", "f2"})
        y = next(f for f in facts if f["subject"] == "음료Y")
        y_occ = [o for o in occ if o["fact_id"] == y["fact_id"]]
        check("입력에 없는 쪽은 자료 전체로 둔다 (사실은 남는다)",
              y["locator_type"] == "WHOLE_SOURCE"
              and [(o["locator_type"], o["locator"]) for o in y_occ] == [("WHOLE_SOURCE", "{}")])
        check("기본 설정 — 근거 없는 단위는 값을 남기고 check_flags 에 판정을 영속한다",
              Settings(_env_file=None).extract_clear_ungrounded_values is False
              and y["unit"] == "펌프"
              and json.loads(y_occ[0]["check_flags"]) == [
                  {"field": "unit", "verdict": "UNGROUNDED_TEXT", "value": "펌프"}]
              and all(json.loads(o["check_flags"]) == [] for o in z_occ))
        states = dict(await db.fetch(
            "select fact_id, assembly_state from source_facts where store_id=$1 and source_id=$2",
            store, pdf))
        check("두 이름표 중 하나만 실려도 그 사실은 LINKED 다",
              states[z["fact_id"]] == "LINKED" and states[y["fact_id"]] == "DROPPED")

        # 3. 같은 자료 재처리 — 모델은 다시 불리지만(재사용 꺼짐) 사실·위치는 늘지 않는다
        before_calls = len(calls)
        await run(pdf, 92)
        occ_again = await occurrences.list_occurrences(db, store, source_id=pdf)
        facts_again = await db.fetch("select fact_id from source_facts where store_id=$1 "
                                     "and source_id=$2 order by fact_id", store, pdf)
        check("같은 자료를 다시 처리해도 사실·위치가 늘지 않는다",
              calls[before_calls:] == ["EXTRACT", "ASSEMBLE"]
              and [r["fact_id"] for r in facts_again] == [f["fact_id"] for f in facts]
              and [o["occurrence_id"] for o in occ_again] == [o["occurrence_id"] for o in occ])

        # 4. 카톡 LINE · 음성 TIMESTAMP — 원장 쓰기 경로를 직접 부른다
        def assertion(ref, **ev):
            return LocatedAssertion(local_ref=ref, original_assertion="음료X 얼음 3개",
                                    subject="음료X", attribute="얼음", value="3",
                                    confidence=.9, evidence=LocatedEvidence(**ev))
        kakao_src = await _new_source(db, store, user, "KAKAO")
        voice_src = await _new_source(db, store, user, "VOICE")
        with patch.object(app.config, "get_settings", lambda: settings):
            async with db.transaction():
                await pipeline._persist_ledger(db, store, kakao_src, "KAKAO",
                                               [assertion("f1", line=3), assertion("f2", line=8)])
                await pipeline._persist_ledger(db, store, voice_src, "VOICE",
                                               [assertion("seg1:f1", timestamp_sec=65)])
        k_occ = await occurrences.list_occurrences(db, store, source_id=kakao_src)
        v_occ = await occurrences.list_occurrences(db, store, source_id=voice_src)
        check("카톡 메시지 번호는 LINE 위치로 남는다",
              [(o["locator_type"], o["locator"]) for o in k_occ]
              == [("LINE", '{"line": 3}'), ("LINE", '{"line": 8}')]
              and len({o["fact_id"] for o in k_occ}) == 1)
        check("음성 시각은 TIMESTAMP 위치로 남는다",
              [(o["locator_type"], o["locator"]) for o in v_occ]
              == [("TIMESTAMP", '{"timestamp_sec": 65}')])

        # 5. 매장 격리
        check("다른 매장에서는 위치가 보이지 않는다",
              await occurrences.list_occurrences(db, other_store) == []
              and await occurrences.list_occurrences(db, other_store, source_id=pdf) == []
              and await occurrences.list_occurrences(db, other_store, fact_id=z["fact_id"]) == [])
        await occurrences.insert_occurrences(db, other_store, [dict(
            fact_id=z["fact_id"], segment_id=None, local_ref="x", locator_type="PAGE",
            locator={"page": 5}, raw_response_id=None)])
        check("다른 매장 ID 로는 이 매장 사실에 위치를 달지 못한다",
              await db.fetchval("select count(*) from source_fact_occurrences where fact_id=$1",
                                z["fact_id"]) == 2)
        other_user = await db.fetchval("select owner_id from stores where store_id=$1", other_store)
        other_src = await _new_source(db, other_store, other_user, "SCAN")
        try:
            await db.execute(
                "insert into source_fact_occurrences (store_id, fact_id, source_id, locator_type, "
                "occurrence_hash) values ($1,$2,$3,'WHOLE_SOURCE','x')",
                other_store, z["fact_id"], other_src)
        except asyncpg.ForeignKeyViolationError:
            check("복합 FK 가 다른 매장 사실을 가리키는 위치를 막는다", True)
        else:
            raise AssertionError("다른 매장 사실에 위치가 달렸다")

        # 6. 평가 매장 초기화처럼 사실을 물리 삭제하면 위치도 함께 지워진다.
        # 자료는 사실이 남아 있는 동안 물리 삭제되지 않는다 (source_facts restrict)
        try:
            async with db.transaction():
                await db.execute("delete from ingest_job_sources where store_id=$1 and source_id=$2",
                                 store, kakao_src)
                await db.execute("delete from sources where store_id=$1 and source_id=$2",
                                 store, kakao_src)
        except (asyncpg.ForeignKeyViolationError, asyncpg.RestrictViolationError):
            check("사실·위치가 남은 자료는 물리 삭제되지 않는다", True)
        else:
            raise AssertionError("사실이 남은 자료가 지워졌다")
        await db.execute("delete from source_facts where store_id=$1 and source_id=$2",
                         store, kakao_src)
        check("사실을 물리 삭제하면 위치도 함께 지워진다",
              await occurrences.list_occurrences(db, store, source_id=kakao_src) == [])

        # 7. 플래그 꺼짐 — 대역이 page 를 보내도 스키마에 없어 버려지고, 위치는 자료 전체
        off_src = await _new_source(db, store, user, "SCAN")
        await run(off_src, 93, hints=False)
        off_occ = await occurrences.list_occurrences(db, store, source_id=off_src)
        off_raw = await db.fetchval(
            "select schema_version from extraction_raw_responses "
            "where store_id=$1 and source_id=$2 and stage='EXTRACT'", store, off_src)
        off_facts = await db.fetchval(
            "select count(*) from source_facts where store_id=$1 and source_id=$2", store, off_src)
        check("플래그 꺼짐 — 이전 스키마로 요청하고, 위치 표는 남기되 쪽은 보지 않는다",
              off_raw == "FactExtractionResult/286f526e798a"
              and off_facts == 2 and len(off_occ) == 2
              and all(o["locator_type"] == "WHOLE_SOURCE" for o in off_occ))

        # 8. 비우기 플래그 켬 — 같은 입력의 새 자료. 단위를 비우고 CLEARED 로 남긴다
        clear_src = await _new_source(db, store, user, "SCAN")
        await run(clear_src, 94, clear=True)
        c_y = await db.fetchrow("select fact_id, unit from source_facts where store_id=$1 "
                                "and source_id=$2 and subject='음료Y'", store, clear_src)
        c_occ = await occurrences.list_occurrences(db, store, fact_id=c_y["fact_id"])
        check("비우기 플래그 켬 — 글만 있는 입력의 근거 없는 단위를 비우고 CLEARED 로 남긴다",
              c_y["unit"] is None and [json.loads(o["check_flags"]) for o in c_occ] == [
                  [{"field": "unit", "verdict": "CLEARED", "value": "펌프"}]])
    finally:
        await pool.close()
    print(f"PASS W fact occurrences: {len(passed)} checks")
