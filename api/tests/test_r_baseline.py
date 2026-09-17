import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from app.team.baseline import record_baseline

FIXTURE = Path(__file__).parent / "fixtures/contracts/v1"


class BaselineTest(unittest.IsolatedAsyncioTestCase):
    async def test_replay_is_deterministic_without_invented_labels(self):
        a, b = await record_baseline(FIXTURE), await record_baseline(FIXTURE)
        self.assertEqual(a, b)
        self.assertEqual(a["case_count"], 37)
        self.assertEqual(a["error_count"], 0)
        self.assertTrue(all(row["semantic_correct"] is None for row in a["rows"]))
        self.assertEqual({row["expected_action"] for row in a["rows"] if row["expected_action"]},
                         {"ANSWER", "CLARIFY", "ESCALATE", "REFUSE", "SAFE_ROUTE"})

    async def test_failure_stays_in_denominator(self):
        with patch("app.team.baseline.compose_grounded_answer", AsyncMock(side_effect=TimeoutError())):
            result = await record_baseline(FIXTURE)
        self.assertEqual(result["case_count"], 37)
        self.assertGreater(result["error_count"], 0)

    async def test_snapshot_manifest_mismatch_rejected(self):
        with TemporaryDirectory() as directory:
            dest = Path(directory)
            (dest / "snapshot.json").write_bytes((FIXTURE / "snapshot.json").read_bytes())
            manifest = json.loads((FIXTURE / "manifest.json").read_text("utf-8"))
            manifest["store_id"] = "2"
            (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                await record_baseline(dest)
