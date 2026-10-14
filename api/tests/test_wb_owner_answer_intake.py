# api/tests/test_wb_owner_answer_intake.py
"""Phase B B-D1·B-U15 — 점주 답변 = 글 + 첨부 한 묶음 분류 1회, 첨부는 업로드 작업."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.cards import owner_answer_worker as worker
from app.ingest import owner_text, pipeline
from app.ingest.intake import route as intake_route
from app.ingest.intake.classify import ClassifyOutcome
from app.ingest.intake.decide import IntakeClassificationError, Ranked, SectionDecision
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.intake.records import StoredRoute
from app.ingest.pipeline import PreparedAssembly
from app.publish.approval import PublishCardsResult
from tests.test_w3a_pipeline_wiring import _planning
# 클래스 이름을 모듈에 들이면 pytest 가 WorkerTests 를 한 번 더 모은다. 모듈로 들인다
from tests import test_w_owner_answer_worker as base
from tests.test_w_owner_answer_worker import MOD, SOURCE

ATTACH_A, ATTACH_B = 301, 302


def _d(cid, logic):
    r = (Ranked(logic, 0.9),)
    return SectionDecision(cid, logic, () if logic == "NONE" else ("RECIPE",), False, False,
                           False, None, r, r)


def _stored(logic, normalizer="OWNER_TEXT"):
    return StoredRoute(1, normalizer, [_d("c1", logic)], _d("source", logic))


class OwnerAnswerIntakeWorkerTests(unittest.IsolatedAsyncioTestCase):
    setUp_base = base.WorkerTests.setUp
    tearDown = base.WorkerTests.tearDown
    _run = base.WorkerTests._run
    _publish_ok = base.WorkerTests._publish_ok

    def setUp(self):
        self.setUp_base()
        self.attachments: list[int] = []
        self.answer_logic = "RECIPE"
        self.routed: list = []

        async def routes(pool, store_id, **kw):
            self.routed.append(kw)
            self.log.append("route")
            out = {kw["answer_source_id"]: _stored(self.answer_logic)}
            out.update({sid: _stored("RECIPE", "DOC_TEXT") for sid in kw["attachment_source_ids"]})
            return out

        extra = [
            patch(f"{MOD}.intake_records.attachments_for_question",
                  AsyncMock(side_effect=lambda *a, **k: list(self.attachments))),
            patch.object(intake_route, "route_owner_answer", side_effect=routes),
            patch(f"{MOD}._start_attachment_job", AsyncMock(return_value=77)),
            patch(f"{MOD}._spawn_job", side_effect=lambda s, j: self.log.append(f"spawn:{j}")),
        ]
        self.patches += extra
        (self.attach_rows, self.route_mock, self.start_job, self.spawn) = [p.start() for p in extra]

    async def test_text_only_answer_routes_and_extracts_without_job(self):
        with self._publish_ok():
            self.assertEqual(await self._run(), "PUBLISHED")
        (kw,) = self.routed
        self.assertEqual((kw["answer_source_id"], kw["attachment_source_ids"]), (SOURCE, []))
        self.assertEqual(self.ingest.call_args.kwargs["route"].source.logic, "RECIPE")
        self.start_job.assert_not_awaited()
        self.assertFalse(any(x.startswith("spawn") for x in self.log if isinstance(x, str)))

    async def test_attachments_go_to_one_route_call_and_job_starts_after_report(self):
        self.attachments = [ATTACH_A, ATTACH_B]
        with self._publish_ok():
            self.assertEqual(await self._run(), "PUBLISHED")
        self.assertEqual(len(self.routed), 1)
        self.assertEqual(self.routed[0]["attachment_source_ids"], [ATTACH_A, ATTACH_B])
        self.assertEqual(self.start_job.await_args.kwargs["source_ids"], [ATTACH_A, ATTACH_B])
        self.assertEqual(self.start_job.await_args.kwargs["answer_id"], 501)
        # R 완료 보고 뒤에 작업을 시작한다
        self.assertLess(self.log.index("finish:PUBLISHED"), self.log.index("spawn:77"))

    async def test_failed_answer_does_not_start_attachment_job(self):
        self.attachments = [ATTACH_A]
        self.route_mock.side_effect = IntakeClassificationError("분류 호출 실패: JSON")
        self.assertEqual(await self._run(), "FAILED")
        result = self.finished[0][0]
        self.assertEqual((result.error.code, result.retryable), ("MODEL_UNAVAILABLE", True))
        self.ingest.assert_not_called()
        self.assertFalse(any(isinstance(x, str) and x.startswith("spawn") for x in self.log))

    # ── fix round 1: 첨부 작업은 보고 뒤에만 만들고, 실패해도 결과를 바꾸지 않는다 ──

    async def test_failed_outcome_creates_and_spawns_no_job(self):
        self.attachments = [ATTACH_A]
        bad = PublishCardsResult(status="INVALID_CONTENT")
        with patch(f"{MOD}.publish_cards", AsyncMock(return_value=bad)):
            self.assertEqual(await self._run(), "FAILED")
        self.start_job.assert_not_awaited()
        self.assertFalse(any(isinstance(x, str) and x.startswith("spawn") for x in self.log))

    async def test_job_creation_error_keeps_reported_status(self):
        self.attachments = [ATTACH_A]
        self.start_job.side_effect = RuntimeError("db down")
        with self._publish_ok(), self.assertLogs(MOD, level="WARNING") as logs:
            self.assertEqual(await self._run(), "PUBLISHED")
        self.assertEqual([r.status for r, _, _ in self.finished], ["PUBLISHED"])
        self.assertTrue(any("첨부 작업 시작 실패" in m and "answer=501" in m
                            for m in logs.output))
        self.assertFalse(any(isinstance(x, str) and x.startswith("spawn") for x in self.log))

    async def test_job_creation_error_keeps_review(self):
        self.attachments = [ATTACH_A]
        self.fact_count = 0
        self.start_job.side_effect = RuntimeError("db down")
        self.assertEqual(await self._run(), "REVIEW")

    async def test_concluded_branch_looks_up_and_spawns_existing_job(self):
        self.attachments = [ATTACH_A]
        self.load.return_value = base._context(proposal=dict(
            proposal_id=70, status="PENDING_REVIEW", relation_type="NEW",
            result_card_id=None, result_version_id=None))
        self.assertEqual(await self._run(), "REVIEW")
        self.route_mock.assert_not_called()
        self.assertEqual(self.start_job.await_args.kwargs["answer_id"], 501)
        self.assertLess(self.log.index("finish:REVIEW"), self.log.index("spawn:77"))

    async def test_analyzed_resume_spawns_job_after_publish(self):
        self.attachments = [ATTACH_A]
        self.load.return_value = base._context(proposal=dict(
            proposal_id=70, status="ANALYZED", relation_type="NEW",
            result_card_id=None, result_version_id=None))
        with self._publish_ok():
            self.assertEqual(await self._run(), "PUBLISHED")
        self.start_job.assert_awaited_once()
        self.assertLess(self.log.index("finish:PUBLISHED"), self.log.index("spawn:77"))

    async def test_none_answer_text_reports_review_no_facts(self):
        self.answer_logic = "NONE"
        self.fact_count = 0
        self.assertEqual(await self._run(), "REVIEW")
        self.assertEqual(self.ingest.call_args.kwargs["route"].source.logic, "NONE")


# ── route_owner_answer: 묶음 1회·재사용 ────────────────────────────────────

class _Tx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _Lease:
    async def __aenter__(self):
        conn = AsyncMock()
        conn.transaction = lambda: _Tx()   # 묶음 판정 행은 한 트랜잭션으로 저장한다
        return conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def acquire(self):
        return _Lease()


BASE = (7, None, "OPERATING", "PRODUCT", None, 42)


def _attachment_probe(sid):
    return ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), f"첨부{sid}"),))


class RouteOwnerAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def _route(self, *, stored: dict, hints=()):
        saves: list = []

        async def latest(conn, store_id, source_id):
            return stored.get(source_id)

        async def save(conn, store_id, **kw):
            saves.append(kw)
            return 100 + len(saves)

        async def get_source(conn, store_id, source_id):
            return {"source_id": source_id, "store_id": store_id, "source_type": "SCAN",
                    "file_url": f"b/7/scan/{source_id}.docx"}

        async def classify(probes, **kw):
            self.classify_calls.append((probes, kw))
            return ClassifyOutcome({c.candidate_id: [Ranked("RECIPE", 0.9)]
                                    for p in probes for c in p.sampled()}, {"sections": []},
                                   "gemini-3.6-flash", "abcd")

        self.classify_calls: list = []
        with patch.object(intake_route.records, "latest_decision", side_effect=latest), \
             patch.object(intake_route.records, "save_decision", side_effect=save), \
             patch.object(intake_route.records, "source_owner_hints",
                          AsyncMock(return_value=tuple(hints))), \
             patch.object(intake_route.repo, "get_source", side_effect=get_source), \
             patch.object(intake_route, "probe_source",
                          AsyncMock(side_effect=lambda pool, store_id, src, **kw:
                                    _attachment_probe(src["source_id"]))), \
             patch.object(intake_route.classify, "classify", side_effect=classify):
            routes = await intake_route.route_owner_answer(
                _Pool(), 7, owner_answer_id=501, answer_source_id=SOURCE, question="시럽 어디?",
                answer="창고 2번 선반", attachment_source_ids=[ATTACH_A, ATTACH_B],
                usage_sink=None, usage_base=BASE)
        return routes, saves

    async def test_bundle_is_one_call_with_prefixed_ids_and_three_rows(self):
        routes, saves = await self._route(stored={}, hints=("REFERENCE",))
        (probes, kw), = self.classify_calls
        ids = [c.candidate_id for p in probes for c in p.candidates]
        self.assertEqual(ids, [f"s{SOURCE}:c1", f"s{ATTACH_A}:c1", f"s{ATTACH_B}:c1"])
        self.assertEqual(kw["context"], "직원 질문: 시럽 어디?")
        self.assertEqual(kw["usage_context"].stage, "CLASSIFY")
        self.assertIn("REFERENCE", kw["hints"])
        self.assertEqual([s["entry"] for s in saves], ["OWNER_ANSWER"] * 3)
        self.assertEqual({s["owner_answer_id"] for s in saves}, {501})
        self.assertEqual(set(routes), {SOURCE, ATTACH_A, ATTACH_B})
        # 저장된 판정의 후보 id 는 접두어가 없다(첨부 작업의 구간 id 와 맞춘다)
        self.assertEqual(routes[ATTACH_A].decisions[0].candidate_id, "c1")

    async def test_all_stored_means_no_call(self):
        stored = {sid: _stored("RECIPE") for sid in (SOURCE, ATTACH_A, ATTACH_B)}
        routes, saves = await self._route(stored=stored)
        self.assertEqual(self.classify_calls, [])
        self.assertEqual(saves, [])
        self.assertIs(routes[ATTACH_B], stored[ATTACH_B])

    async def test_only_missing_sources_are_classified(self):
        routes, saves = await self._route(stored={SOURCE: _stored("RECIPE")})
        (probes, _), = self.classify_calls
        self.assertEqual([p.candidates[0].candidate_id for p in probes],
                         [f"s{ATTACH_A}:c1", f"s{ATTACH_B}:c1"])
        self.assertEqual(len(saves), 2)


# ── ingest_owner_text: NONE 건너뜀 · NOTICE 보류 ──────────────────────────

class IngestOwnerTextRouteTests(unittest.IsolatedAsyncioTestCase):
    async def _ingest(self, logic):
        conn = AsyncMock()

        async def fetchval(sql, *args):
            if "exists" in sql:
                return False
            return 3  # category_version
        conn.fetchval = AsyncMock(side_effect=fetchval)
        # pipeline._notice_holds 의 occurrence 행(지식 사실 ID·구간·다른 받침). 다른 받침이
        # 없으므로 답변 자료 사실 전부가 보류된다
        conn.fetch = AsyncMock(return_value=[
            {"fact_id": 901, "segment_id": None, "other_support": False},
            {"fact_id": 902, "segment_id": None, "other_support": False}])

        class Lease:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        conn.transaction = lambda: Lease()

        class Pool:
            def acquire(self):
                return Lease()

        prepare = AsyncMock(return_value=PreparedAssembly((), {}, {}, (), {}, _planning()))
        extract = AsyncMock()
        with patch.object(owner_text.repo, "glossary", AsyncMock(return_value=[])), \
             patch.object(owner_text.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})), \
             patch.object(owner_text.repo, "set_status", AsyncMock()), \
             patch("app.ingest.extract.extract_facts", extract), \
             patch.object(pipeline, "_persist_ledger", AsyncMock(return_value={})), \
             patch.object(pipeline, "_prepare_fact_assembly", prepare), \
             patch.object(pipeline, "_persist_fact_cards", AsyncMock(return_value=0)), \
             patch.object(owner_text, "answer_fact_count", AsyncMock(return_value=0)):
            extract.return_value = type("R", (), {"assertions": [], "unresolved": []})()
            await owner_text.ingest_owner_text(Pool(), store_id=7, source_id=SOURCE,
                                               question="q", answer="a", run_tag=1,
                                               route=_stored(logic))
        return extract, prepare

    async def test_none_skips_extraction(self):
        extract, prepare = await self._ingest("NONE")
        extract.assert_not_awaited()
        self.assertFalse(prepare.await_args.kwargs.get("held_fact_ids"))

    async def test_notice_holds_every_fact_of_the_answer(self):
        extract, prepare = await self._ingest("NOTICE")
        extract.assert_awaited_once()
        self.assertEqual(prepare.await_args.kwargs["held_fact_ids"],
                         {901: "INTAKE_NOTICE", 902: "INTAKE_NOTICE"})

    async def test_recipe_extracts_without_hold(self):
        extract, prepare = await self._ingest("RECIPE")
        extract.assert_awaited_once()
        self.assertFalse(prepare.await_args.kwargs.get("held_fact_ids"))


# ── _start_attachment_job: 멱등 키·대상 거르기 (brief 밖 보강) ─────────────

class StartAttachmentJobTests(unittest.IsolatedAsyncioTestCase):
    async def _start(self, *, existing=None, rows=(), busy=()):
        from contextlib import asynccontextmanager

        conn = AsyncMock()

        @asynccontextmanager
        async def tx():
            yield

        conn.transaction = tx
        conn.fetchval = AsyncMock(return_value=3)

        class Pool:
            @asynccontextmanager
            async def acquire(self):
                yield conn

        create = AsyncMock(return_value={"job_id": 88})
        with patch.object(worker.job_repository, "find_by_idempotency",
                          AsyncMock(return_value=existing)), \
             patch.object(worker.job_repository, "source_rows", AsyncMock(return_value=list(rows))), \
             patch.object(worker.job_repository, "source_in_progress",
                          AsyncMock(side_effect=lambda c, st, sid: sid in busy)), \
             patch.object(worker.job_repository, "create_job", create):
            job_id = await worker._start_attachment_job(
                Pool(), store_id=7, owner_user_id=20, answer_id=501, source_ids=[ATTACH_A, ATTACH_B])
        return job_id, create

    async def test_existing_job_is_reused(self):
        job_id, create = await self._start(existing={"job_id": 55})
        self.assertEqual(job_id, 55)
        create.assert_not_awaited()

    async def test_only_uploaded_or_failed_attachments_become_job(self):
        rows = [{"source_id": ATTACH_A, "status": "UPLOADED", "source_availability": "AVAILABLE"},
                {"source_id": ATTACH_B, "status": "DONE", "source_availability": "AVAILABLE"}]
        job_id, create = await self._start(rows=rows)
        self.assertEqual(job_id, 88)
        kw = create.await_args.kwargs
        self.assertEqual(kw["source_ids"], [ATTACH_A])
        self.assertEqual(kw["idempotency_key"], "owner-answer:501:attachments")
        self.assertEqual((kw["title"], kw["category_version"], kw["prompt_version"]),
                         ("점주 답변 첨부", 3, "extract-cards-v1"))

    async def test_attachment_already_in_active_job_is_skipped(self):
        # 답변 처리 중 붙은 보충 첨부가 이미 작업을 받았다(최종 리뷰 I2) — 두 번 돌리지 않는다
        rows = [{"source_id": ATTACH_A, "status": "UPLOADED", "source_availability": "AVAILABLE"},
                {"source_id": ATTACH_B, "status": "UPLOADED", "source_availability": "AVAILABLE"}]
        job_id, create = await self._start(rows=rows, busy=(ATTACH_B,))
        self.assertEqual(job_id, 88)
        self.assertEqual(create.await_args.kwargs["source_ids"], [ATTACH_A])

    async def test_no_target_returns_none(self):
        rows = [{"source_id": ATTACH_A, "status": "DONE", "source_availability": "AVAILABLE"}]
        job_id, create = await self._start(rows=rows)
        self.assertIsNone(job_id)
        create.assert_not_awaited()


# ── _spawn_job: 배경 작업 참조 보관·완료 시 제거 ──────────────────────────

class SpawnJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_kept_until_done(self):
        import asyncio
        gate = asyncio.Event()
        seen = []

        async def run(store_id, job_id):
            seen.append((store_id, job_id))
            await gate.wait()

        with patch.object(worker.job_worker, "process_ingest_job", side_effect=run):
            worker._spawn_job(7, 88)
            self.assertEqual(len(worker._BACKGROUND), 1)
            (task,) = worker._BACKGROUND
            await asyncio.sleep(0)
            gate.set()
            await task
            await asyncio.sleep(0)
        self.assertEqual(seen, [(7, 88)])
        self.assertEqual(worker._BACKGROUND, set())
