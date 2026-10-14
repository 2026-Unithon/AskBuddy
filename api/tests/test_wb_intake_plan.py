# api/tests/test_wb_intake_plan.py
"""Phase B — 판정 → 추출 계획. 글 자료만 구간별(2026-10-11), 나머지는 자료 단위."""
from app.ingest.intake.decide import Ranked, SectionDecision
from app.ingest.intake.plan import plan_extraction


def _d(cid, logic, extractors=None):
    ex = extractors if extractors is not None else (() if logic == "NONE" else ("RECIPE",))
    r = (Ranked(logic, 0.9),)
    return SectionDecision(cid, logic, tuple(ex), False, False, False, None, r, r)


SECTIONS = {"c1": "[1쪽]\n가", "c2": "[2쪽]\n나", "c3": "[3쪽]\n다"}


def test_nothing_dropped_same_text():
    plan = plan_extraction(normalizer="DOC_TEXT",
                           decisions=[_d("c1", "RECIPE"), _d("c2", "PROCEDURE"), _d("c3", "RECIPE")],
                           source=_d("source", "RECIPE"), sections=SECTIONS)
    assert plan.text == "[1쪽]\n가\n\n[2쪽]\n나\n\n[3쪽]\n다" and plan.segments is None
    assert not plan.skip and not plan.hold_all_notice


def test_none_sections_dropped():
    plan = plan_extraction(normalizer="DOC_TEXT",
                           decisions=[_d("c1", "RECIPE"), _d("c2", "NONE"), _d("c3", "RECIPE")],
                           source=_d("source", "RECIPE"), sections=SECTIONS)
    assert plan.text == "[1쪽]\n가\n\n[3쪽]\n다"


def test_all_none_skips():
    plan = plan_extraction(normalizer="CHAT", decisions=[_d("c1", "NONE")],
                           source=_d("source", "NONE"), sections={"c1": "x"})
    assert plan.skip


def test_notice_gets_own_segment():
    plan = plan_extraction(normalizer="DOC_TEXT",
                           decisions=[_d("c1", "RECIPE"), _d("c2", "NOTICE"), _d("c3", "RECIPE")],
                           source=_d("source", "RECIPE"), sections=SECTIONS)
    assert plan.segments == [("[1쪽]\n가\n\n[3쪽]\n다", []), ("[2쪽]\n나", [])]
    assert plan.notice_segment_ids == frozenset({"seg2"})


def test_only_notice_holds_all():
    plan = plan_extraction(normalizer="OWNER_TEXT", decisions=[_d("c1", "NOTICE")],
                           source=_d("source", "NOTICE"), sections={"c1": "공지"})
    assert plan.hold_all_notice and plan.text == "공지" and plan.segments is None


def test_chat_joiner_is_newline():
    plan = plan_extraction(normalizer="CHAT", decisions=[_d("c1", "RECIPE"), _d("c2", "RECIPE")],
                           source=_d("source", "RECIPE"), sections={"c1": "a", "c2": "b"})
    assert plan.text == "a\nb"


def test_media_is_source_level():
    plan = plan_extraction(normalizer="VIDEO", decisions=[_d("c1", "NONE"), _d("c2", "RECIPE")],
                           source=_d("source", "RECIPE"), sections=None)
    assert plan.text is None and plan.segments is None and not plan.skip
    assert plan_extraction(normalizer="AUDIO", decisions=[_d("c1", "NONE")],
                           source=_d("source", "NONE"), sections=None).skip
    assert plan_extraction(normalizer="DOC_IMAGE", decisions=[_d("c1", "NOTICE")],
                           source=_d("source", "NOTICE"), sections=None).hold_all_notice


def test_text_normalizer_without_sections_is_source_level():
    # HYBRID 처럼 그림 쪽을 첨부하는 PDF 는 전처리가 구간 글을 주지 않는다
    plan = plan_extraction(normalizer="DOC_TEXT", decisions=[_d("c1", "NONE"), _d("c2", "RECIPE")],
                           source=_d("source", "RECIPE"), sections=None)
    assert plan.text is None and not plan.skip


def test_two_registered_extractors_two_segments():
    plan = plan_extraction(normalizer="DOC_TEXT",
                           decisions=[_d("c1", "RECIPE", ("RECIPE", "POLICY")), _d("c2", "POLICY", ("POLICY",))],
                           source=_d("source", "RECIPE"), sections=SECTIONS)
    assert plan.segments == [("[1쪽]\n가", []), ("[1쪽]\n가\n\n[2쪽]\n나", [])]
