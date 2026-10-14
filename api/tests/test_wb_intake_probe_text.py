# api/tests/test_wb_intake_probe_text.py
"""Phase B — 글 자료 경계 후보(코드가 만든다)와 훑기 표본. 모델 호출 없음."""
from app.ingest.intake import grouping, probe_text
from app.ingest.preprocess import docx
from app.ingest.preprocess.docx import DocxBlock, DocxRead


def test_even_indices_keeps_first_middle_last():
    assert grouping.even_indices(10, 3) == [0, 4, 9]  # 4 = round(4.5) 아래쪽
    assert grouping.even_indices(2, 5) == [0, 1]
    assert grouping.even_indices(1, 1) == [0]


def test_pdf_pages_merge_to_max_sections_and_rejoin_identically():
    blocks = [(n, f"[{n}쪽]\n쪽{n} 내용") for n in range(1, 8)]
    groups = grouping.group_pdf_pages(blocks, max_sections=3)
    assert [g.candidate_id for g in groups] == ["c1", "c2", "c3"]
    assert [(g.locator.start, g.locator.end) for g in groups] == [("1", "3"), ("4", "5"), ("6", "7")]
    assert "\n\n".join(u for g in groups for u in g.units) == "\n\n".join(b for _, b in blocks)


def test_docx_splits_on_headings_and_merges_short():
    read = DocxRead([DocxBlock("HEADING", "오픈", 1), DocxBlock("PARA", "가" * 100, 2),
                     DocxBlock("HEADING", "짧음", 3),
                     DocxBlock("HEADING", "레시피", 4), DocxBlock("TABLE_ROW", "음료Z | 2", 5),
                     DocxBlock("TABLE_ROW", "나" * 100, 6)], 0)
    groups = grouping.group_docx(read, max_sections=12, min_chars=80)
    assert [(g.locator.start, g.locator.end) for g in groups] == [("1", "3"), ("4", "6")]
    assert "\n\n".join(u for g in groups for u in g.units) == docx.to_text(read)


def test_chat_groups_by_date_keep_continuation_lines():
    text = "[08-01 09:00] 사장: 우유 2단\n이어지는 줄\n[08-01 10:00] 직원: 네\n[#3] [08-02 09:00] 사장: 마감"
    groups = grouping.group_chat(text, max_sections=12)
    assert [(g.locator.kind, g.locator.start, g.locator.end) for g in groups] == [
        ("DATE", "08-01", "08-01"), ("DATE", "08-02", "08-02")]
    assert "\n".join(u for g in groups for u in g.units) == text


def test_probe_groups_budget_and_all_sampled():
    blocks = [(n, f"[{n}쪽]\n" + "가" * 2000) for n in range(1, 4)]
    probe = probe_text.probe_groups("DOC_TEXT", grouping.group_pdf_pages(blocks, max_sections=12),
                                    budget_chars=3000)
    assert all(c.sampled for c in probe.candidates)
    assert all(len(c.text) <= 1000 for c in probe.candidates)
    assert probe.summary()["chars"] <= 3000


def test_probe_owner_text_whole():
    probe = probe_text.probe_owner_text("시럽 어디?", "창고 2번 선반")
    (c,) = probe.candidates
    assert c.candidate_id == "c1" and c.locator.kind == "WHOLE" and "창고 2번 선반" in c.text


class _FakePage:
    def __init__(self, text: str, images: int = 0):
        self._text = text
        self.images = [object()] * images

    def extract_text(self) -> str:
        return self._text


_BODY = "에스프레소는 원두 18g 으로 25초 동안 내린다. 우유는 60도까지만 데운다."


def _patch(monkeypatch, pages):
    import pypdf
    monkeypatch.setattr(pypdf, "PdfReader", lambda _p: type("R", (), {"pages": pages})())


def test_pdf_pages_matches_read_pdf(monkeypatch):
    from app.ingest.preprocess import document
    _patch(monkeypatch, [_FakePage(_BODY), _FakePage("", images=1), _FakePage(_BODY)])
    pp, rd = document.pdf_pages("가짜.pdf"), document.read_pdf("가짜.pdf")
    assert "\n\n".join(b for _, b in pp.blocks) == rd.text
    assert pp.visual_pages == rd.visual_pages == [2]
    assert pp.page_count == rd.page_count == 3 and pp.has_text
    assert [n for n, _ in pp.blocks] == [1, 3]


def test_pdf_pages_without_text_goes_all_visual(monkeypatch):
    from app.ingest.preprocess import document
    _patch(monkeypatch, [_FakePage("", images=1), _FakePage("", images=1)])
    pp, rd = document.pdf_pages("가짜.pdf"), document.read_pdf("가짜.pdf")
    assert pp.blocks == [] and not pp.has_text and rd.text == ""
    assert pp.visual_pages == rd.visual_pages == [1, 2]


def test_docx_short_first_section_merges_into_next_two_sections():
    read = DocxRead([DocxBlock("HEADING", "짧", 1), DocxBlock("PARA", "a", 2),
                     DocxBlock("HEADING", "긴", 3), DocxBlock("PARA", "가" * 100, 4)], 0)
    groups = grouping.group_docx(read, max_sections=12, min_chars=80)
    assert [(g.locator.start, g.locator.end) for g in groups] == [("1", "4")]
    assert "\n\n".join(u for g in groups for u in g.units) == docx.to_text(read)


def test_docx_short_first_section_merges_into_next_three_sections():
    read = DocxRead([DocxBlock("HEADING", "짧", 1), DocxBlock("PARA", "a", 2),
                     DocxBlock("HEADING", "둘", 3), DocxBlock("PARA", "가" * 100, 4),
                     DocxBlock("HEADING", "셋", 5), DocxBlock("PARA", "나" * 100, 6)], 0)
    groups = grouping.group_docx(read, max_sections=12, min_chars=80)
    assert [(g.locator.start, g.locator.end) for g in groups] == [("1", "4"), ("5", "6")]
    assert "\n\n".join(u for g in groups for u in g.units) == docx.to_text(read)
