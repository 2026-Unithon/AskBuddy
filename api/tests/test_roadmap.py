from __future__ import annotations

import unittest

from app.learn.roadmap import learning_status


class RoadmapTest(unittest.TestCase):
    def test_current_completed_version_is_done(self):
        self.assertEqual(learning_status("DONE", 12, 12), "DONE")

    def test_old_completed_version_requires_reconfirmation(self):
        self.assertEqual(
            learning_status("DONE", 11, 12), "RECONFIRM_REQUIRED"
        )

    def test_legacy_lock_states_are_not_started(self):
        self.assertEqual(learning_status("LOCKED", None, 12), "NOT_STARTED")
        self.assertEqual(learning_status("IN_PROGRESS", None, 12), "NOT_STARTED")

    def test_legacy_done_without_version_is_not_assumed_complete(self):
        self.assertEqual(learning_status("DONE", None, 12), "NOT_STARTED")


if __name__ == "__main__":
    unittest.main()
