"""W3-0 §3-5 — 두 W2 플래그를 켠 수집의 처리량을 잰다. 합성 데이터만, 모델 호출 없음, 비용 0.

일회용 DB 서버(verify_r_answer_usage.DSN, 127.0.0.1:55439)에 새 UUID DB 를 만들고 migration 을
모두 올린 뒤 process_source 를 합성 모델 대역으로 돌린다. 끝나면 그 DB 를 지운다.

재는 것 (합격선 없음 — D21 카드 생성 지연 상한 보류):
  - total: 자료 처리 전체 시간(process_source 벽시계)
  - link: 구간 checkpoint 마다 원장→판 연결 시간(link_source_facts, 안의 잠금 대기 포함)
  - lock_wait: 매장 advisory lock 대기(트랜잭션에서 처음 잡을 때만)
  - lock_hold: 매장 lock 을 쥔 시간(처음 잡은 때 → 그 트랜잭션 함수가 끝날 때, commit 제외)
  - candidates_per_new_entity: 새 대상 하나의 같은 대상 후보 계산 시간
조건: 사실 300건·대상 60개·구간 10개, 구간 동시성 1 과 2, 모델 지연 0ms 와 --model-delay-ms.

사용 (api/ 에서):
  PYTHONPATH=. PYTHONUTF8=1 <venv python> -B scripts/probe_w3_flag_throughput.py \
      --model-delay-ms 1500 --out <저장할 JSON 경로>
"""
import argparse
import asyncio
import json
import statistics
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import asyncpg

import app.config
from app.config import Settings
from app.ingest import entities, extract, fact_ledger, impact, pipeline
from app.ingest import repository as repo
from app.ingest.extract import gemini
from app.ingest.schemas import (ExtractedCard, ExtractedFact, ExtractionResult,
                                FactExtractionResult)

_MODEL_SETTINGS = NS(gemini_api_key="synthetic", gemini_model="gemini-synthetic",
                     ingest_mode="real", extract_temperature=0.0, extract_locator_hints=False)
_COUNTED = ("source_facts", "knowledge_entities", "knowledge_entity_candidates",
            "fact_revisions", "fact_occurrences", "upload_change_proposals")


def synthetic_segments(facts_total: int = 300, entities_total: int = 60,
                       segments_total: int = 10) -> list[list[dict]]:
    """구간마다 사실 목록. 대상 이름은 합성 '측정메뉴NN', 사실마다 속성·값이 다르다."""
    per_segment = facts_total // segments_total
    segments = []
    for seg in range(segments_total):
        facts = []
        for i in range(per_segment):
            n = seg * per_segment + i
            subject = f"측정메뉴{n % entities_total:02d}"
            facts.append(dict(
                local_ref=f"f{i + 1}", original_assertion=f"{subject} 속성{n} {n}ml",
                subject=subject, attribute=f"속성{n}", value=str(n), unit="ml",
                confidence=.9, evidence=dict(timestamp_sec=seg * 60 + i + 1)))
        segments.append(facts)
    return segments


def summary(values: list[float]) -> dict:
    """초 단위 측정값 → ms 요약."""
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"n": len(values), "sum_ms": round(sum(values) * 1000, 1),
            "p50_ms": round(statistics.median(values) * 1000, 1),
            "p95_ms": round(p95 * 1000, 1), "max_ms": round(max(values) * 1000, 1)}


class Probe:
    """잠금·연결·후보 계산 시간을 모은다. 태스크마다 처음 잡은 매장 잠금 시각을 기억한다."""

    def __init__(self) -> None:
        self.link: list[float] = []
        self.lock_wait: list[float] = []
        self.lock_hold: list[float] = []
        self.candidates: list[float] = []
        self._acquired: dict[int, float] = {}

    @staticmethod
    def _task() -> int:
        return id(asyncio.current_task())

    def lock(self, original):
        async def timed(conn, store_id):
            started = time.perf_counter()
            await original(conn, store_id)
            got = time.perf_counter()
            # 같은 트랜잭션 안의 재진입은 새 대기·보유로 세지 않는다
            if self._task() not in self._acquired:
                self._acquired[self._task()] = got
                self.lock_wait.append(got - started)
        return timed

    def transaction_end(self, original):
        async def timed(*args, **kwargs):
            try:
                return await original(*args, **kwargs)
            finally:
                got = self._acquired.pop(self._task(), None)
                if got is not None:
                    self.lock_hold.append(time.perf_counter() - got)
        return timed

    def timed(self, bucket: list[float], original):
        async def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return await original(*args, **kwargs)
            finally:
                bucket.append(time.perf_counter() - started)
        return wrapper


async def run_once(db, dsn: str, *, concurrency: int, delay_s: float,
                   segments: list[list[dict]]) -> dict:
    """새 합성 매장 하나에서 영상 자료 하나를 처리하며 잰다."""
    from verify_w_partial_extraction import _new_source, _seed

    user, store, _ = await _seed(db)
    source = await _new_source(db, store, user, "VIDEO")
    job_id = await db.fetchval(
        "insert into ingest_jobs (store_id, created_by, title, status, category_version, "
        "prompt_version) values ($1,$2,'W3-0 처리량','EXTRACTING',1,'v1') returning job_id",
        store, user)
    await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                     store, source)
    await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                     "values($1,$2,$3,'QUEUED')", store, job_id, source)
    category = next(iter(await repo.enabled_categories(db, store)))
    texts = [f"측정 구간 {i + 1:02d}" for i in range(len(segments))]
    by_text = dict(zip(texts, segments))

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        if delay_s:
            await asyncio.sleep(delay_s)
        if schema is not None and issubclass(schema, FactExtractionResult):
            facts = next(v for k, v in by_text.items() if k in prompt)
            body = FactExtractionResult.model_validate({"assertions": facts})
            return gemini.CallResult(body.model_dump_json(), {}, "STOP")
        cards = [ExtractedCard(
            category_name=category, title=f"측정 카드 {i:02d}", content="합성 카드",
            confidence=.9, facts=[ExtractedFact(
                object_name=f["subject"], attribute=f["attribute"], value=f["value"],
                confidence=.9, ref=f"seg{i}:{f['local_ref']}") for f in facts])
            for i, facts in enumerate(segments, start=1)]
        return gemini.CallResult(ExtractionResult(cards=cards).model_dump_json(), {}, "STOP")

    probe = Probe()
    settings = Settings(_env_file=None, w_entity_revision_enabled=True,
                        w_upload_proposals_enabled=True,
                        extract_segment_concurrency=concurrency)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        with ExitStack() as stack:
            for obj, name, replacement in [
                (pipeline, "get_pool", lambda: pool),
                (pipeline, "_preprocess", AsyncMock(return_value=(
                    "측정 본문", [], [(t, []) for t in texts]))),
                (pipeline.shutil, "rmtree", lambda *a, **kw: None),
                (app.config, "get_settings", lambda: settings),
                (extract, "get_settings", lambda: NS(ingest_mode="real")),
                (gemini, "get_settings", lambda: _MODEL_SETTINGS),
                (gemini, "_call", fake_call),
                (fact_ledger, "lock_store_knowledge",
                 probe.lock(fact_ledger.lock_store_knowledge)),
                (entities, "lock_store_knowledge", probe.lock(entities.lock_store_knowledge)),
                (impact, "lock_store_knowledge", probe.lock(impact.lock_store_knowledge)),
                (pipeline, "_persist_ledger", probe.transaction_end(pipeline._persist_ledger)),
                (pipeline, "_persist", probe.transaction_end(pipeline._persist)),
                (fact_ledger, "link_source_facts",
                 probe.timed(probe.link, fact_ledger.link_source_facts)),
                (entities, "_propose_candidates",
                 probe.timed(probe.candidates, entities._propose_candidates)),
            ]:
                stack.enter_context(patch.object(obj, name, replacement))
            started = time.perf_counter()
            await pipeline.process_source(store, source, job_id=job_id, run_tag=900 + concurrency)
            total = time.perf_counter() - started
    finally:
        await pool.close()
    state = await db.fetchval("select status from sources where store_id=$1 and source_id=$2",
                              store, source)
    assert state == "DONE", f"처리 실패: {state}"
    rows = {t: await db.fetchval(f"select count(*) from {t} where store_id=$1", store)
            for t in _COUNTED}
    return {
        "conditions": {"facts": sum(len(seg) for seg in segments),
                       "entities": len({f["subject"] for seg in segments for f in seg}),
                       "segments": len(segments), "segment_concurrency": concurrency,
                       "model_delay_ms": round(delay_s * 1000)},
        "total_ms": round(total * 1000, 1),
        "link": summary(probe.link),
        "lock_wait": summary(probe.lock_wait),
        "lock_hold": summary(probe.lock_hold),
        "candidates_per_new_entity": summary(probe.candidates),
        "lock_hold_share": round(sum(probe.lock_hold) / total, 3),
        "rows": rows,
    }


async def main(argv: list[str] | None = None) -> int:
    from verify_r_answer_usage import DSN
    from verify_w_partial_extraction import _fresh_db

    parser = argparse.ArgumentParser(description="W3-0 처리량 측정(합성, 비용 0)")
    parser.add_argument("--model-delay-ms", type=int, default=0,
                        help="합성 모델 호출마다 기다릴 ms (0 이면 지연 없음만 잰다)")
    parser.add_argument("--out", type=Path, default=None, help="결과 JSON 을 저장할 경로")
    args = parser.parse_args(argv)
    admin = await asyncpg.connect(DSN, timeout=5)
    name = db = None
    try:
        name, db = await _fresh_db(admin)
        dsn = DSN.rsplit("/", 1)[0] + "/" + name
        segments = synthetic_segments()
        results = []
        for delay_ms in sorted({0, args.model_delay_ms}):
            for concurrency in (1, 2):
                results.append(await run_once(db, dsn, concurrency=concurrency,
                                              delay_s=delay_ms / 1000, segments=segments))
        text = json.dumps(results, ensure_ascii=False, indent=2)
        print(text)
        if args.out is not None:
            args.out.write_text(text + "\n", encoding="utf-8")
    finally:
        if db is not None:
            await db.close()
        if name is not None:
            await admin.execute(f'drop database "{name}"')
        await admin.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
