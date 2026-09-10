from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from app.ingest.capabilities import get_capabilities
from app.ingest.job_worker import final_job_status
from app.ingest.schemas import CreateIngestJobRequest, CreateSourceRequest


class IngestJobsTest(unittest.TestCase):
    def test_capabilities_use_configured_limits(self):
        settings = SimpleNamespace(
            ingest_voice_max_bytes=100,
            ingest_voice_max_duration_sec=20,
            ingest_video_max_bytes=None,
            ingest_video_max_duration_sec=None,
            ingest_kakao_max_bytes=None,
            ingest_scan_max_bytes=None,
            ingest_scan_max_pages=5,
        )
        with patch("app.ingest.capabilities.get_settings", return_value=settings):
            result = get_capabilities()
        self.assertEqual(result["VOICE"]["max_bytes"], 100)
        self.assertEqual(result["SCAN"]["max_pages"], 5)
        self.assertNotIn("zip", result["KAKAO"]["extensions"])

    def test_source_ids_must_be_unique(self):
        with self.assertRaises(ValidationError):
            CreateIngestJobRequest(source_ids=[1, 1])

    def test_content_hash_must_be_sha256(self):
        with self.assertRaises(ValidationError):
            CreateSourceRequest(
                source_type="KAKAO",
                file_url="sources/1/kakao/test.txt",
                content_hash="not-a-sha256",
            )

    def test_final_status(self):
        self.assertEqual(final_job_status(total=2, failed=2, cards=0), "FAILED")
        self.assertEqual(final_job_status(total=2, failed=1, cards=3), "PARTIAL")
        self.assertEqual(final_job_status(total=2, failed=0, cards=0), "NO_RESULT")
        self.assertEqual(final_job_status(total=2, failed=0, cards=3), "SUCCEEDED")


if __name__ == "__main__":
    unittest.main()
