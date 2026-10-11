"""실제 DB: 모델 원래 응답 기록(W1-1)을 검증한다. 모델 호출은 전부 합성이다.

verify_r_schema_rebuild 가 만든 새 UUID DB(모든 migration 적용)의 연결과 DSN 만 받는다.
  1. 파싱 실패 응답도 행이 남고 parsed_ok=false·사유가 적힌다
  2. 성공 응답은 parsed_ok=true, finish_reason 이 문자열로 남는다
  3. 다른 매장 행은 조회·표시 갱신 모두에서 보이지 않는다
  4. 원문은 불변이고, 파싱 결과는 한 번만 적힌다
  5. 자료를 지워도(물리 삭제 포함) 기록은 남는다
  6. mock 모드 process_source 가 구간마다·조립마다 같은 기록을 남긴다 (run_tag 포함)
  7. 끝내 잘리는 구간(W1-2)은 원래 응답이 parsed_ok=false 로 남고 자료는 PARTIAL(실패 구간 seg1)
  8. 재사용(W1-3): 같은 자료를 두 번 처리 → 모델 호출은 첫 번째만, 사실 중복 없음, 원장에 REUSED·비용 0
  9. 재사용은 다른 매장으로 새지 않는다 (키에도, 조회 WHERE 에도 매장)
 10. 잘린 응답은 재사용 후보가 아니다. PARTIAL 재시도는 잃은 구간만 새로 부르고 사실을 겹치지 않는다
"""
import json
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import asyncpg

import app.config
from app.config import Settings
from app.contracts.usage import UsageContext
from app.ingest import extract, pipeline, raw_responses
from app.ingest import repository as repo
from app.ingest.extract import gemini
from app.ingest import fact_assembly
from app.ingest.extract import mock
from app.ingest.schemas import FactExtractionResult
from verify_w_partial_extraction import _new_source, _seed

GOOD = ('{"assertions": [{"local_ref": "f1", "original_assertion": "음료Z 물 10ml", '
        '"subject": "음료Z", "attribute": "물", "value": "10", "unit": "ml", "confidence": 0.9}]}')


def _plan_reply(prompt, category):
    """사실 조립 프롬프트의 대상 목록을 규칙대로 배치한 합성 계획 응답."""
    payload = json.loads(prompt.split(fact_assembly.PLAN_INPUT_MARKER, 1)[1])
    return gemini.CallResult(mock._planned(payload, [category]).model_dump_json(), {}, "STOP")


def _ctx(store, source, job, segment=None, stage="EXTRACT"):
    return UsageContext(store_id=str(store), cost_phase="REGISTRATION", cost_purpose="EVALUATION",
                        stage=stage, logical_call_id=f"job{job}:src{source}:{stage.lower()}",
                        job_id=str(job), source_id=str(source), segment_id=segment)


async def verify(db, dsn):
    passed = []

    def check(name, ok):
        assert ok, name
        passed.append(name)
        print("PASS W raw response", name)

    user, store, job = await _seed(db)
    _, other_store, other_job = await _seed(db)
    source = await _new_source(db, store, user, "VOICE")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    real = NS(gemini_api_key="synthetic", gemini_model="gemini-synthetic",
              ingest_mode="real", extract_temperature=0.0)
    try:
        sink = raw_responses.DbRawResponseSink(pool, run_tag=42)

        # 1. 파싱 실패 — 잘린 JSON. max_size=1 에서 돈다: 모델 호출 중 연결을 쥐었다면 교착한다
        async def truncated(prompt, media, schema, max_output_tokens=None):
            async with pool.acquire() as c:
                assert await c.fetchval("select 1") == 1
            return gemini.CallResult('{"assertions": [{"local_ref": "f1"', {}, "MAX_TOKENS")

        with patch.object(gemini, "get_settings", return_value=real), \
             patch.object(gemini, "_call", truncated):
            try:
                await gemini.extract_facts(source_id=source, source_type="VOICE", text="t",
                                           glossary=[], usage_context=_ctx(store, source, job, "seg1"),
                                           raw_sink=sink)
            except RuntimeError:
                pass
            else:
                raise AssertionError("잘린 응답이 파싱됐다")
        rows = await raw_responses.list_raw_responses(db, store, source_id=source)
        check("파싱 실패 응답도 행이 남는다",
              len(rows) == 1 and rows[0]["parsed_ok"] is False and rows[0]["error"]
              and rows[0]["response_text"].startswith('{"assertions": [')
              and rows[0]["finish_reason"] == "MAX_TOKENS" and rows[0]["run_tag"] == 42
              and rows[0]["segment_id"] == "seg1" and rows[0]["stage"] == "EXTRACT"
              and rows[0]["job_id"] == job and rows[0]["mode"] == "real")

        # 2. 성공
        with patch.object(gemini, "get_settings", return_value=real), \
             patch.object(gemini, "_call", AsyncMock(return_value=gemini.CallResult(GOOD, {"prompt_tokens": 5}, "STOP"))):
            result = await gemini.extract_facts(source_id=source, source_type="VOICE", text="t",
                                                glossary=[], usage_context=_ctx(store, source, job, "seg2"),
                                                raw_sink=sink)
        ok_row = await db.fetchrow(
            "select * from extraction_raw_responses where store_id=$1 and raw_response_id=$2",
            store, result.raw_response_id)
        check("성공 응답은 parsed_ok=true 로 표시된다",
              ok_row["parsed_ok"] is True and ok_row["error"] is None
              and ok_row["finish_reason"] == "STOP" and ok_row["schema_version"].startswith("FactExtractionResult/"))

        # 3. 매장 격리
        check("다른 매장에서 조회되지 않는다",
              await raw_responses.list_raw_responses(db, other_store) == []
              and await raw_responses.list_raw_responses(db, other_store, source_id=source) == [])
        fresh_id = await raw_responses.insert_raw_response(
            pool, store, source_id=source, job_id=job, extraction_run_id=None, run_tag=None,
            segment_id=None, logical_call_id="verify:mark", response=raw_responses.RawResponse(
                stage="ASSEMBLE", model="m", mode="real", prompt_hash=None, schema_version=None,
                finish_reason=None, response_text="{}", usage={}))
        await raw_responses.mark_parse_result(pool, other_store, fresh_id, parsed_ok=True, error=None)
        check("다른 매장 ID 로는 파싱 결과를 적지 못한다",
              await db.fetchval("select parsed_ok from extraction_raw_responses where store_id=$1 and raw_response_id=$2",
                                store, fresh_id) is None)

        # 4. 불변
        try:
            await db.execute("update extraction_raw_responses set response_text='변조' "
                             "where store_id=$1 and raw_response_id=$2", store, fresh_id)
        except asyncpg.RaiseError:
            check("원문은 바꿀 수 없다", True)
        else:
            raise AssertionError("원문이 바뀌었다")
        await raw_responses.mark_parse_result(pool, store, fresh_id, parsed_ok=True, error=None)
        try:
            await db.execute("update extraction_raw_responses set parsed_ok=false, error='x' "
                             "where store_id=$1 and raw_response_id=$2", store, fresh_id)
        except asyncpg.RaiseError:
            check("파싱 결과는 한 번만 적힌다", True)
        else:
            raise AssertionError("파싱 결과가 덮였다")
        try:
            await db.execute(
                "insert into extraction_raw_responses(store_id,stage,model,mode,response_text,parsed_ok) "
                "values($1,'EXTRACT','m','real','x',false)", store)
        except asyncpg.CheckViolationError:
            check("실패 표시에는 사유가 필요하다", True)
        else:
            raise AssertionError("사유 없는 실패가 들어갔다")

        # 5. 자료 삭제로 지워지지 않는다 (tombstone·물리 삭제 모두)
        before = await db.fetchval("select count(*) from extraction_raw_responses where store_id=$1 and source_id=$2",
                                   store, source)
        # 자료 등록 시 따라 생긴 작업 연결을 먼저 치운다 — 원래 응답 표에는 자료 FK 가 없다
        await db.execute("delete from ingest_job_sources where store_id=$1 and source_id=$2", store, source)
        await db.execute("delete from sources where store_id=$1 and source_id=$2", store, source)
        check("자료를 지워도 원래 응답은 남는다",
              before == 3 and await db.fetchval(
                  "select count(*) from extraction_raw_responses where store_id=$1 and source_id=$2",
                  store, source) == 3)

        # 6. mock 모드 전체 경로
        mock_source = await _new_source(db, store, user, "VOICE")
        await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                         store, mock_source)
        await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                         "values($1,$2,$3,'QUEUED')", store, job, mock_source)
        with ExitStack() as stack:
            for obj, name, replacement in [
                (pipeline, "get_pool", lambda: pool),
                (pipeline, "_preprocess", AsyncMock(return_value=("t", [], [("a", []), ("b", [])]))),
                (pipeline.shutil, "rmtree", lambda *a, **kw: None),
                (extract, "get_settings", lambda: NS(ingest_mode="mock")),
            ]:
                stack.enter_context(patch.object(obj, name, replacement))
            await pipeline.process_source(store, mock_source, job_id=job, run_tag=77)
        rows = await raw_responses.list_raw_responses(db, store, source_id=mock_source)
        check("mock 경로도 구간·조립마다 같은 기록을 남긴다",
              [(r["stage"], r["segment_id"]) for r in rows]
              == [("EXTRACT", "seg1"), ("EXTRACT", "seg2"), ("ASSEMBLE", "plan0")]
              and all(r["mode"] == "mock" and r["parsed_ok"] is True and r["run_tag"] == 77
                      and r["job_id"] == job for r in rows)
              and await db.fetchval("select status from sources where store_id=$1 and source_id=$2",
                                    store, mock_source) == "DONE")
        check("다른 매장에는 mock 기록도 보이지 않는다",
              await raw_responses.list_raw_responses(db, other_store) == [])

        # 7. 잘린 출력 (W1-2) — seg1 은 반으로 나눠도 계속 잘린다, seg2 는 정상
        cut_source = await _new_source(db, store, user, "VOICE")
        await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                         store, cut_source)
        await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                         "values($1,$2,$3,'QUEUED')", store, job, cut_source)
        category = next(iter(await repo.enabled_categories(db, store)))

        async def cutting(prompt, media, schema=None, max_output_tokens=None):
            async with pool.acquire() as c:   # 모델 호출 중 연결을 쥐지 않는다 (max_size=1)
                assert await c.fetchval("select 1") == 1
            if schema is FactExtractionResult:
                if "줄A" in prompt:
                    return gemini.CallResult('{"assertions": [{"local_ref": "f1"', {}, "MAX_TOKENS")
                return gemini.CallResult(GOOD, {}, "STOP")
            return _plan_reply(prompt, category)

        split_on = Settings(_env_file=None, extract_truncation_split_max_depth=1)
        with ExitStack() as stack:
            for obj, name, replacement in [
                (pipeline, "get_pool", lambda: pool),
                (pipeline, "_preprocess", AsyncMock(return_value=(
                    "t", [], [("줄A 첫째\n줄A 둘째", []), ("줄B", [])]))),
                (pipeline.shutil, "rmtree", lambda *a, **kw: None),
                (app.config, "get_settings", lambda: split_on),
                (extract, "get_settings", lambda: NS(ingest_mode="real")),
                (gemini, "get_settings", lambda: real),
                (gemini, "_call", cutting),
            ]:
                stack.enter_context(patch.object(obj, name, replacement))
            await pipeline.process_source(store, cut_source, job_id=job, run_tag=78)
        rows = await raw_responses.list_raw_responses(db, store, source_id=cut_source)
        check("잘린 응답도 원래 응답으로 남고 실패로 표시된다",
              [(r["stage"], r["segment_id"], r["finish_reason"], r["parsed_ok"]) for r in rows]
              == [("EXTRACT", "seg1", "MAX_TOKENS", False), ("EXTRACT", "seg1.1", "MAX_TOKENS", False),
                  ("EXTRACT", "seg2", "STOP", True), ("ASSEMBLE", "plan0", "STOP", True)]
              and all("MAX_TOKENS" in r["error"] for r in rows if r["parsed_ok"] is False))
        seg = await db.fetchrow(
            "select segments_total, segments_failed, failed_segment_ids from ingest_job_sources "
            "where store_id=$1 and job_id=$2 and source_id=$3", store, job, cut_source)
        facts = await db.fetch("select local_ref, segment_id from source_facts "
                               "where store_id=$1 and source_id=$2", store, cut_source)
        check("끝내 잘린 구간은 부모 구간 ID 로 실패 기록된다 (PARTIAL)",
              seg["segments_total"] == 2 and seg["segments_failed"] == 1
              and list(seg["failed_segment_ids"]) == ["seg1"]
              and [(f["local_ref"], f["segment_id"]) for f in facts] == [("seg2:f1", "seg2")]
              and await db.fetchval("select status from sources where store_id=$1 and source_id=$2",
                                    store, cut_source) == "DONE")

        # ── 재사용 (W1-3) ────────────────────────────────────────────────
        reuse_on = NS(**vars(real), extract_reuse_enabled=True)
        base_settings = Settings(_env_file=None)
        calls = []

        def counting(tag):
            async def _call(prompt, media, schema=None, max_output_tokens=None):
                async with pool.acquire() as c:   # 모델 호출 중 연결을 쥐지 않는다 (max_size=1)
                    assert await c.fetchval("select 1") == 1
                calls.append((tag, "EXTRACT" if schema is FactExtractionResult else "ASSEMBLE"))
                if schema is FactExtractionResult:
                    return gemini.CallResult(GOOD, {"prompt_tokens": 5, "completion_tokens": 7}, "STOP")
                return _plan_reply(prompt, category)
            return _call

        async def run(target_store, source, job_id, run_tag, tag, settings=base_settings,
                      segments=(("줄C", []), ("줄D", []))):
            with ExitStack() as stack:
                for obj, name, replacement in [
                    (pipeline, "get_pool", lambda: pool),
                    (pipeline, "_preprocess", AsyncMock(return_value=("t", [], list(segments)))),
                    (pipeline.shutil, "rmtree", lambda *a, **kw: None),
                    (app.config, "get_settings", lambda: settings),
                    (extract, "get_settings", lambda: NS(ingest_mode="real")),
                    (gemini, "get_settings", lambda: reuse_on),
                    (gemini, "_call", counting(tag)),
                ]:
                    stack.enter_context(patch.object(obj, name, replacement))
                return await pipeline.process_source(target_store, source, job_id=job_id,
                                                     run_tag=run_tag)

        async def new_job(target_store, source):
            job_id = await db.fetchval(
                "insert into ingest_jobs (store_id, created_by, title, status, category_version, "
                "prompt_version) values ($1,$2,'재사용 검증','EXTRACTING',1,'v1') returning job_id",
                target_store, user)
            await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                             target_store, source)
            await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                             "values($1,$2,$3,'QUEUED')", target_store, job_id, source)
            return job_id

        async def fact_rows(target_store, source):
            return [tuple(r) for r in await db.fetch(
                "select fact_id, content_hash from source_facts where store_id=$1 and source_id=$2 "
                "order by fact_id", target_store, source)]

        # 8. 같은 자료 두 번 처리 — 두 번째 작업은 모델을 부르지 않는다
        twice = await _new_source(db, store, user, "VOICE")
        first_job = await new_job(store, twice)
        await run(store, twice, first_job, 81, "first")
        raw_after_first = await raw_responses.list_raw_responses(db, store, source_id=twice)
        facts_after_first = await fact_rows(store, twice)
        second_job = await new_job(store, twice)
        await run(store, twice, second_job, 82, "second")
        raw_after_second = await raw_responses.list_raw_responses(db, store, source_id=twice)
        facts_after_second = await fact_rows(store, twice)
        check("같은 자료 두 번 처리 → 모델 호출은 첫 번째 처리에서만",
              [c for c in calls if c[0] == "first"] == [
                  ("first", "EXTRACT"), ("first", "EXTRACT"), ("first", "ASSEMBLE")]
              and [c for c in calls if c[0] == "second"] == [])
        check("재사용 키가 원래 응답 행에 남고, 재사용은 새 원래 응답 행을 만들지 않는다",
              len(raw_after_first) == 3 and len(raw_after_second) == 3
              and all(r["reuse_key"] and r["reuse_key"].startswith("rk1:") for r in raw_after_first)
              and len({r["reuse_key"] for r in raw_after_first}) == 3)
        check("같은 자료 두 번 처리 → source_facts 중복 없음",
              facts_after_first == facts_after_second and len(facts_after_first) == 1
              and await db.fetchval("select status from sources where store_id=$1 and source_id=$2",
                                    store, twice) == "DONE")
        reused = await db.fetch(
            "select stage, status, cache_state, usage_status, cost_usd, missing_reason "
            "from ai_usage_attempts where store_id=$1 and job_id=$2 order by usage_attempt_id",
            store, second_job)
        paid = await db.fetch(
            "select cache_state, usage_status from ai_usage_attempts "
            "where store_id=$1 and job_id=$2", store, first_job)
        raw_ids = {r["raw_response_id"] for r in raw_after_first}
        check("재사용은 원장에 REUSED·비용 0 으로 남고 원래 응답 행을 가리킨다",
              [r["stage"] for r in reused] == ["EXTRACT", "EXTRACT", "ASSEMBLE"]
              and all(r["status"] == "SUCCEEDED" and r["cache_state"] == "REUSED"
                      and r["usage_status"] == "NOT_BILLABLE" and r["cost_usd"] == 0
                      and int(r["missing_reason"].rsplit("=", 1)[1]) in raw_ids for r in reused)
              and len(paid) == 3 and all(r["cache_state"] is None for r in paid))

        # 프롬프트(용어집)가 바뀌면 키가 바뀌어 새로 부른다
        await db.execute("insert into store_glossary (store_id, term) values ($1, '재사용검증용어')", store)
        third_job = await new_job(store, twice)
        await run(store, twice, third_job, 83, "third")
        check("용어집이 바뀌면 새 호출로 남는다",
              [c for c in calls if c[0] == "third"] == [
                  ("third", "EXTRACT"), ("third", "EXTRACT"), ("third", "ASSEMBLE")]
              and await fact_rows(store, twice) == facts_after_first)

        # 9. 다른 매장 — 같은 입력이어도 재사용하지 않는다
        other_user = await db.fetchval("select owner_id from stores where store_id=$1", other_store)
        other_source = await _new_source(db, other_store, other_user, "VOICE")
        other_job_id = await db.fetchval(
            "insert into ingest_jobs (store_id, created_by, title, status, category_version, "
            "prompt_version) values ($1,$2,'재사용 격리','EXTRACTING',1,'v1') returning job_id",
            other_store, other_user)
        await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                         other_store, other_source)
        await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                         "values($1,$2,$3,'QUEUED')", other_store, other_job_id, other_source)
        await run(other_store, other_source, other_job_id, 84, "other")
        a_key = raw_after_first[0]["reuse_key"]
        check("다른 매장은 같은 입력이어도 모델을 새로 부른다",
              [c for c in calls if c[0] == "other"] == [
                  ("other", "EXTRACT"), ("other", "EXTRACT"), ("other", "ASSEMBLE")])
        check("다른 매장 ID 로는 그 매장의 키를 조회하지 못한다 (WHERE store_id)",
              await raw_responses.find_reusable_response(pool, store, a_key) is not None
              and await raw_responses.find_reusable_response(pool, other_store, a_key) is None)

        # 10. 잘린 응답은 재사용하지 않는다 — 7번의 seg1 행 (parsed_ok=false, MAX_TOKENS)
        cut_rows = await raw_responses.list_raw_responses(db, store, source_id=cut_source)
        cut_seg1 = next(r for r in cut_rows if r["segment_id"] == "seg1")
        check("잘린 응답 행에도 키는 남지만 재사용 후보가 아니다",
              cut_seg1["reuse_key"] is not None
              and await raw_responses.find_reusable_response(pool, store, cut_seg1["reuse_key"]) is None)
        forced = await raw_responses.insert_raw_response(
            pool, store, source_id=cut_source, job_id=job, extraction_run_id=None, run_tag=None,
            segment_id="seg9", logical_call_id="verify:forced", response=raw_responses.RawResponse(
                stage="EXTRACT", model="m", mode="real", prompt_hash=None, schema_version=None,
                finish_reason="MAX_TOKENS", response_text=GOOD, usage={}, reuse_key="rk1:forced"))
        await raw_responses.mark_parse_result(pool, store, forced, parsed_ok=True, error=None)
        check("종료 사유가 MAX_TOKENS 인 행은 파싱 성공 표시가 있어도 재사용하지 않는다",
              await raw_responses.find_reusable_response(pool, store, "rk1:forced") is None)

        # PARTIAL 재시도 — 7번 자료를 재사용을 켠 채 다시 돌린다. 잃은 seg1 만 새로 부른다
        await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                         store, cut_source)
        before = await fact_rows(store, cut_source)
        await run(store, cut_source, job, 85, "partial", settings=split_on,
                  segments=(("줄A 첫째\n줄A 둘째", []), ("줄B", [])))
        seg = await db.fetchrow(
            "select segments_failed, failed_segment_ids from ingest_job_sources "
            "where store_id=$1 and job_id=$2 and source_id=$3", store, job, cut_source)
        check("PARTIAL 재시도는 잃은 구간만 새로 부르고 사실을 겹치지 않는다",
              [c for c in calls if c[0] == "partial"] == [("partial", "EXTRACT"), ("partial", "ASSEMBLE")]
              and seg["segments_failed"] == 0 and seg["failed_segment_ids"] is None
              # seg1 이 뽑은 사실은 seg2 와 내용이 같다 — 새 행 없이 기존 행에 잇는다
              and await fact_rows(store, cut_source) == before and len(before) == 1)
    finally:
        await pool.close()
    print(f"PASS W raw responses: {len(passed)} checks")
