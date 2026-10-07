"""W3-0 §3-5 처리량 측정 스크립트의 순수 함수. DB·모델은 부르지 않는다."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import probe_w3_flag_throughput as probe  # noqa: E402


def test_synthetic_segments_shape():
    segments = probe.synthetic_segments(facts_total=300, entities_total=60, segments_total=10)
    flat = [f for seg in segments for f in seg]
    assert len(segments) == 10 and all(len(seg) == 30 for seg in segments)
    assert len(flat) == 300 and len({f["subject"] for f in flat}) == 60
    assert all(seg[i]["local_ref"] == f"f{i + 1}" for seg in segments for i in range(30))
    # 사실은 서로 다르다(원장 content_hash 로 합쳐지지 않는다)
    assert len({(f["subject"], f["attribute"], f["value"]) for f in flat}) == 300
    assert all(f["evidence"]["timestamp_sec"] > 0 for f in flat)
    assert all(f["subject"].startswith("측정메뉴") for f in flat)


def test_summary_reports_ms_percentiles():
    assert probe.summary([0.001, 0.002, 0.003, 0.004]) == {
        "n": 4, "sum_ms": 10.0, "p50_ms": 2.5, "p95_ms": 4.0, "max_ms": 4.0}
    assert probe.summary([]) == {"n": 0}
