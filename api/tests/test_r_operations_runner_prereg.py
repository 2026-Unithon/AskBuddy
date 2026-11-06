"""유료 실행 입구에서 사전등록을 강제하는지 — 러너 배선 테스트.

`run_r_operations_http.main` 은 `--live-plan` 을 받으면 **DB 에 붙기 전에**
사전등록 파일을 요구해야 한다. 그러지 않으면 "등록은 해 두고 다른 입력으로
돌리기" 를 막을 수 없다(D17·D18).

여기서는 모델도 DB 도 쓰지 않는다. 가드가 걸리는 지점까지만 확인한다.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.contracts.hashing import digest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover - pytest 설정에 따라 이미 들어 있다
    sys.path.insert(0, str(ROOT))

from scripts import run_r_operations_http as runner  # noqa: E402
from scripts.r_fact_evaluation import FORMAT, evaluator_sources  # noqa: E402


def _challenge() -> dict:
    challenge = dict(
        schema_version="r_operations_challenge/v2", created_date="2026-10-15",
        status="FACT_FIXTURE_NOT_EVALUATED", truth_kind="SYNTHETIC", knowledge_format=FORMAT,
        facts=[], cases=[], conventions={}, grading={}, execution={}, parent_challenge_hash=None,
        representation_note="테스트용 빈 challenge")
    from scripts.r_fact_evaluation import challenge_hash
    challenge["content_sha256"] = challenge_hash(challenge)
    return challenge


def _live_plan(challenge: dict) -> dict:
    from app.learn.general_semantics import source_hash
    return dict(knowledge_format=FORMAT, evaluator_source_hash=digest(evaluator_sources()),
                challenge_hash=challenge["content_sha256"], source_hash=source_hash(),
                thinking_level="low", max_generation_calls=1, max_krw=100,
                max_input_tokens_per_call=1000, max_output_tokens_per_call=1000,
                max_prompt_bytes=10000, input_krw_per_million_ceiling=1,
                output_krw_per_million_ceiling=1, pricing_reference="테스트")


class LiveRunRequiresRegistrationTest(unittest.TestCase):
    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp())
        self.challenge = _challenge()
        self.input = self.workdir / "frozen-challenge.json"
        self.input.write_text(json.dumps(self.challenge, ensure_ascii=False), encoding="utf-8")
        self.plan = _live_plan(self.challenge)
        self.plan_path = self.workdir / "plan.json"
        self.plan_path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")

    def _args(self, **over) -> SimpleNamespace:
        args = dict(input=self.input, output=self.workdir / "out", live_plan=self.plan_path,
                    plan_hash=digest(self.plan), approved_by="테스트 승인자", registration=None)
        args.update(over)
        return SimpleNamespace(**args)

    def test_live_plan_without_registration_stops_before_the_database(self):
        with self.assertRaises(ValueError) as caught:
            asyncio.run(runner.main(self._args()))
        self.assertIn("registration", str(caught.exception))

    def test_guard_runs_before_any_connection_attempt(self):
        # DSN 이 닫힌 포트를 가리켜도 같은 ValueError 여야 한다 — 가드가 먼저다
        original = runner.DSN
        runner.DSN = "postgresql://postgres:x@127.0.0.1:1/none"
        try:
            with self.assertRaises(ValueError):
                asyncio.run(runner.main(self._args(output=self.workdir / "out2")))
        finally:
            runner.DSN = original


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
