from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ingest.preprocess.video import frame_time_sec, split_by_time


def _frames(*indexes: int) -> list[Path]:
    return [Path(f"frame_{i:04d}.jpg") for i in indexes]


def _segments(*pairs) -> list[dict]:
    return [{"start": s, "end": s + 5, "text": t} for s, t in pairs]


class FrameTimeTest(unittest.TestCase):
    def test_frame_index_maps_to_seconds(self):
        with patch("app.ingest.preprocess.video.get_settings",
                   return_value=SimpleNamespace(frame_interval_sec=3)):
            self.assertEqual(frame_time_sec(Path("frame_0001.jpg")), 0)
            self.assertEqual(frame_time_sec(Path("frame_0002.jpg")), 3)
            self.assertEqual(frame_time_sec(Path("frame_0011.jpg")), 30)

    def test_unexpected_name_is_zero_not_crash(self):
        with patch("app.ingest.preprocess.video.get_settings",
                   return_value=SimpleNamespace(frame_interval_sec=3)):
            self.assertEqual(frame_time_sec(Path("thumb.jpg")), 0)


class SplitByTimeTest(unittest.TestCase):
    def setUp(self):
        self.patcher = patch(
            "app.ingest.preprocess.video.get_settings",
            return_value=SimpleNamespace(frame_interval_sec=3,
                                         video_max_frames_to_model=20),
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_window_zero_means_no_split(self):
        self.assertEqual(split_by_time(_segments((0, "가")), _frames(1), 0), [])

    def test_splits_into_windows(self):
        segs = _segments((0, "첫 구간"), (70, "둘째 구간"), (130, "셋째 구간"))
        out = split_by_time(segs, _frames(1, 25, 45), 60)
        self.assertEqual(len(out), 3)

    def test_each_window_sees_only_its_own_time(self):
        segs = _segments((0, "오픈 절차"), (70, "마감 절차"))
        out = split_by_time(segs, [], 60)
        self.assertIn("오픈 절차", out[0][0])
        self.assertNotIn("마감 절차", out[0][0])
        self.assertIn("마감 절차", out[1][0])
        self.assertNotIn("오픈 절차", out[1][0])

    def test_frames_are_bucketed_by_time(self):
        # frame_0001=0초, frame_0021=60초, frame_0041=120초
        out = split_by_time([], _frames(1, 21, 41), 60)
        self.assertEqual(len(out), 3)
        for _, frames in out:
            self.assertEqual(len(frames), 1)

    def test_transcript_carries_timestamps(self):
        out = split_by_time(_segments((65, "우유는 2번 냉장고")), [], 60)
        self.assertIn("[01:05]", out[0][0])

    def test_empty_window_is_dropped(self):
        """말도 화면도 없는 구간에 호출을 낭비하지 않는다."""
        segs = _segments((0, "가"), (130, "나"))
        out = split_by_time(segs, [], 60)
        self.assertEqual(len(out), 2)   # 60~120 구간은 비어 있어 빠진다

    def test_silent_window_with_frames_is_kept(self):
        """말이 없어도 화면이 있으면 뽑을 게 있다.

        frame_0021 은 60초라 두 번째 창(60~120)에만 들어간다.
        첫 창(0~60)은 말도 화면도 없어 빠지므로 결과는 한 구간이다.
        """
        out = split_by_time([], _frames(21), 60)
        self.assertEqual(len(out), 1)
        self.assertIn("화면만으로 판단", out[0][0])
        self.assertEqual(len(out[0][1]), 1)

    def test_no_input_is_empty(self):
        self.assertEqual(split_by_time([], [], 60), [])


if __name__ == "__main__":
    unittest.main()


class PreprocessContractTest(unittest.TestCase):
    """전처리는 (전사문, 미디어, 구간) 3-튜플을 돌려준다.

    반환 형태를 바꾼 뒤 일부 경로를 빠뜨려 SCAN 자료 2건이 통째로 실패한 적이 있다.
    런타임에만 드러나고 그 실행의 측정값이 통째로 못 쓰게 되므로 정적으로 막는다.
    """

    def test_all_preprocess_returns_three_values(self):
        import ast
        from pathlib import Path as P

        src = P(__file__).resolve().parents[1] / "app" / "ingest" / "pipeline.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        offenders = []
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            if not fn.name.startswith("_preprocess"):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                    if len(node.value.elts) != 3:
                        offenders.append(
                            f"{fn.name}:{node.lineno} 가 {len(node.value.elts)}개를 돌려준다")
        self.assertEqual(offenders, [], "\n".join(offenders))
