"""Phase B — 공통 중간 형식(IR)과 등록표(B-D5)."""
import pytest

from app.ingest.intake import ir, registry


def test_logics_and_normalizers():
    assert registry.LOGICS == ("RECIPE", "PROCEDURE", "POLICY", "REFERENCE", "NOTICE", "NONE")
    assert registry.CARD_LOGICS == ("RECIPE", "PROCEDURE", "POLICY", "REFERENCE")
    assert set(registry.NORMALIZERS) == {"DOC_TEXT", "DOC_IMAGE", "AUDIO", "VIDEO", "CHAT", "OWNER_TEXT"}
    # 2026-10-11 사용자 확정: 글 자료만 구간별로 추출한다
    assert registry.SECTIONED_NORMALIZERS == frozenset({"DOC_TEXT", "CHAT", "OWNER_TEXT"})


def test_only_recipe_registered_now():
    assert registry.registered_logics() == ("RECIPE",)


@pytest.mark.parametrize("source_type, ext, has_text, expected", [
    ("VOICE", "m4a", False, "AUDIO"),
    ("VIDEO", "mp4", False, "VIDEO"),
    ("KAKAO", "txt", False, "CHAT"),
    ("KAKAO", "png", False, "CHAT"),
    ("SCAN", "pdf", True, "DOC_TEXT"),
    ("SCAN", "pdf", False, "DOC_IMAGE"),
    ("SCAN", "jpg", False, "DOC_IMAGE"),
    ("SCAN", "docx", False, "DOC_TEXT"),
    ("OWNER_TEXT", "", False, "OWNER_TEXT"),
])
def test_normalizer_for(source_type, ext, has_text, expected):
    assert registry.normalizer_for(source_type, ext, pdf_has_text=has_text) == expected


def test_unknown_extension_raises():
    with pytest.raises(ValueError):
        registry.normalizer_for("SCAN", "hwp", pdf_has_text=False)


def test_probe_summary_and_hash_ignore_unsampled_text():
    loc = ir.Locator("PAGE", "1", "1")
    a = ir.ProbeResult("DOC_TEXT", (ir.Candidate("c1", loc, "가나다"),
                                    ir.Candidate("c2", ir.Locator("PAGE", "2", "2"), "", sampled=False)))
    assert a.summary() == {"normalizer": "DOC_TEXT", "candidates": 2, "sampled": ["c1"],
                           "chars": 3, "images": 0}
    b = ir.ProbeResult("DOC_TEXT", (ir.Candidate("c1", loc, "가나다"),))
    assert len(a.sample_hash()) == 64
    assert a.sample_hash() != b.sample_hash()  # 후보 구성이 다르면 다르다
