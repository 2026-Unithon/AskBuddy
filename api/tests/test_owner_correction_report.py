"""사장님 수정 지표 — 순수 집계 (설계 §4-6)."""
from decimal import Decimal

from app.usage.owner_correction_report import format_of, render, summarize


def test_format_of_groups_by_normalizer_path():
    assert format_of("SCAN", "pdf") == "PDF"
    assert format_of("SCAN", "JPG") == "사진"
    assert format_of("SCAN", "docx") == "DOCX"
    assert format_of("KAKAO", "txt") == "카톡 글"
    assert format_of("KAKAO", "png") == "카톡 캡처"
    assert format_of("VOICE", "m4a") == "음성"


def test_summarize_counts_and_rates_by_format_and_logic():
    rows = [
        {"source_id": 1, "source_type": "SCAN", "ext": "pdf", "logic": "RECIPE",
         "extracted": 18, "corrected": 1, "added": 2},
        {"source_id": 2, "source_type": "SCAN", "ext": "jpg", "logic": "POLICY",
         "extracted": 10, "corrected": 0, "added": 0},
        {"source_id": 3, "source_type": "KAKAO", "ext": "txt", "logic": None,
         "extracted": 0, "corrected": 0, "added": 0},
    ]
    s = summarize(rows)
    assert s["total"]["sources"] == 3 and s["total"]["extracted"] == 28
    assert s["total"]["corrected_rate"] == Decimal("0.0357")
    assert s["total"]["added_rate"] == Decimal("0.0667")  # 2 / (28 + 2)
    assert s["by_format"]["PDF"]["added"] == 2 and s["by_format"]["사진"]["corrected_rate"] == 0
    # 뽑은 사실이 0 이면 비율은 None — 0% 로 적지 않는다
    assert s["by_format"]["카톡 글"]["corrected_rate"] is None
    assert s["by_logic"]["미판정"]["sources"] == 1


def test_render_marks_unmeasured_as_dash():
    text = render(summarize([{"source_id": 1, "source_type": "VOICE", "ext": "m4a", "logic": "MIXED",
                              "extracted": 0, "corrected": 0, "added": 0}]))
    assert "| 음성 | 1 | 0 | 0 (—) | 0 (—) |" in text
