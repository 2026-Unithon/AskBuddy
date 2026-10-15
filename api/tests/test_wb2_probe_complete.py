"""Phase B 추가 S2 — '작은 자료'는 용량이 아니라 훑기가 내용 전체를 담았는지로 정한다."""
import asyncio
from types import SimpleNamespace as NS

from PIL import Image

from app.config import Settings
from app.ingest.intake import grouping, probe_media, probe_text, route
from app.ingest.intake.ir import Candidate, Locator, ProbeResult


def _groups(*texts):
    return grouping.group_pdf_pages([(i, f"[{i}쪽]\n{t}") for i, t in enumerate(texts, 1)],
                                    max_sections=12)


def test_short_text_is_complete():
    probe = probe_text.probe_groups("DOC_TEXT", _groups("음료Z 샷 2", "마감 청소"),
                                    budget_chars=3000)
    assert probe.complete is True
    assert probe.summary()["complete"] is True


def test_text_over_budget_is_not_complete():
    probe = probe_text.probe_groups("DOC_TEXT", _groups("가" * 2000, "나" * 2000),
                                    budget_chars=3000)
    assert probe.complete is False


def test_owner_text_is_complete():
    assert probe_text.probe_owner_text("시럽 어디?", "창고 2번 선반").complete is True


def test_single_image_complete_multi_page_not(tmp_path):
    img = tmp_path / "p.jpg"
    Image.new("RGB", (100, 100)).save(img)
    one = asyncio.run(probe_media.probe_doc_image(img, tmp_path, max_images=6, px=512,
                                                  max_sections=12, page_count=1))
    many = asyncio.run(probe_media.probe_doc_image(
        tmp_path / "s.pdf", tmp_path, max_images=6, px=512, max_sections=12, page_count=3,
        render=lambda path, index, dpi: Image.new("RGB", (100, 100))))
    assert one.complete is True and many.complete is False


def test_default_is_not_complete():
    assert ProbeResult("AUDIO", (Candidate("c1", Locator("TIME", "0", "20"), "말"),)).complete is False


def _settings(**kw):
    return Settings(_env_file=None).model_copy(update=kw)


def test_eligible_needs_switch_complete_and_normalizer():
    small = ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "글"),),
                        complete=True)
    assert route.single_call_eligible(small, _settings(intake_single_call_small=False)) is False
    assert route.single_call_eligible(small, _settings(intake_single_call_small=True)) is True
    big = ProbeResult("DOC_TEXT", small.candidates, complete=False)
    assert route.single_call_eligible(big, _settings(intake_single_call_small=True)) is False
    audio = ProbeResult("AUDIO", small.candidates, complete=True)
    assert route.single_call_eligible(audio, _settings(intake_single_call_small=True)) is False


def test_layout_scan_is_never_single_call():
    img = ProbeResult("DOC_IMAGE", (Candidate("c1", Locator("PAGE", "1", "1"), ""),),
                      complete=True)
    s = _settings(intake_single_call_small=True, scan_extract_mode="LAYOUT")
    assert route.single_call_eligible(img, s) is False


def test_config_defaults():
    s = Settings(_env_file=None)
    assert (s.intake_bundle_enabled, s.intake_bundle_max_sources, s.intake_bundle_max_chars,
            s.intake_bundle_max_images, s.intake_bundle_max_candidates,
            s.intake_single_call_small) == (True, 8, 12000, 12, 24, False)
