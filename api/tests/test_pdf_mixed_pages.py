"""혼합 PDF 에서 그림·표 페이지를 버리지 않는지 검증한다 (W1 결함3).

지금까지는 문서 전체 텍스트를 한 덩어리로 합쳐 판독률을 쟀다. 앞 몇 장만
글이 제대로 있으면 문서 전체가 '읽혔다'가 되고, 뒤의 표·사진 페이지는
모델에 아예 전달되지 않았다.
"""
from app.ingest.preprocess.document import PageProbe, needs_visual_read


def test_page_with_image_and_no_text_needs_visual_read():
    # 사진 한 장만 있는 페이지 — 텍스트 추출은 빈손이다
    assert needs_visual_read(PageProbe(text="", has_images=True))


def test_page_with_image_and_garbled_text_needs_visual_read():
    # 커스텀 인코딩 폰트라 추출이 깨진 페이지
    assert needs_visual_read(PageProbe(text="஠ಕ ѐ ஠ಕ ѐ ஠ಕ ѐ ஠ಕ ѐ ஠ಕ ѐ ஠ಕ",
                                       has_images=True))


def test_page_with_image_but_enough_readable_text_is_left_alone():
    # 로고만 박힌 본문 페이지까지 그림으로 보내면 비용만 늘어난다
    assert not needs_visual_read(PageProbe(
        text="에스프레소는 원두 18g 으로 25초 동안 내린다. 우유는 60도까지만 데운다.",
        has_images=True))


def test_blank_page_is_not_sent_for_visual_read():
    # 그림도 글도 없으면 볼 것이 없다
    assert not needs_visual_read(PageProbe(text="", has_images=False))


def test_text_only_page_is_not_sent_for_visual_read():
    assert not needs_visual_read(PageProbe(
        text="영업 시작 전 매장 청소를 마친다.", has_images=False))


def test_short_text_without_image_is_not_sent_for_visual_read():
    # 글이 짧아도 그림이 없으면 추출된 글이 그 페이지의 전부다
    assert not needs_visual_read(PageProbe(text="3층", has_images=False))


class _FakePage:
    """pypdf 페이지 흉내. 텍스트와 이미지 유무만 있으면 판단에 충분하다."""

    def __init__(self, text: str, images: int = 0):
        self._text = text
        self.images = [object()] * images

    def extract_text(self) -> str:
        return self._text


def _read(pages, monkeypatch):
    """read_pdf 를 가짜 PDF 로 돌린다."""
    import pypdf

    from app.ingest.preprocess import document

    monkeypatch.setattr(pypdf, "PdfReader",
                        lambda _p: type("R", (), {"pages": pages})())
    return document.read_pdf("가짜.pdf")


BODY = "에스프레소는 원두 18g 으로 25초 동안 내린다. 우유는 60도까지만 데운다."


def test_image_page_is_named_even_when_the_document_reads_well(monkeypatch):
    # 본문 2장 + 표 사진 1장 — 지금까지는 뒤 1장이 통째로 사라졌다
    result = _read([_FakePage(BODY), _FakePage(BODY),
                    _FakePage("", images=1)], monkeypatch)
    assert result.visual_pages == [3]
    assert result.page_count == 3


def test_a_fully_readable_document_names_no_visual_page(monkeypatch):
    result = _read([_FakePage(BODY), _FakePage(BODY)], monkeypatch)
    assert result.visual_pages == []
    assert result.text


def test_readable_page_text_is_kept_with_its_page_number(monkeypatch):
    # 어느 페이지에서 나온 사실인지 알아야 근거를 댈 수 있다
    result = _read([_FakePage(BODY), _FakePage("", images=1)], monkeypatch)
    assert "1" in result.text and BODY in result.text


def test_scanned_document_with_no_text_layer_reports_every_page(monkeypatch):
    result = _read([_FakePage("", images=1), _FakePage("", images=1)],
                   monkeypatch)
    assert result.text == "" and result.visual_pages == [1, 2]


# ── _preprocess_scan 분기 ───────────────────────────────────────────────

import pytest

from app.ingest import pipeline
from app.ingest.preprocess.document import PdfRead


async def _scan(read_result, monkeypatch, tmp_path):
    """_preprocess_scan 을 주어진 read_pdf 결과로 돌린다."""
    pdf = tmp_path / "문서.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    async def fake_get_scan(conn, source_id):
        return {"scan_id": 1}

    async def fake_update(conn, source_id, **kw):
        return None

    async def fake_download(conn, store_id, src):
        return pdf

    monkeypatch.setattr(pipeline.repo, "get_scan", fake_get_scan)
    monkeypatch.setattr(pipeline.repo, "update_scan_result", fake_update)
    monkeypatch.setattr(pipeline, "_download", fake_download)
    monkeypatch.setattr(pipeline.document, "read_pdf", lambda _p: read_result)
    return await pipeline._preprocess_scan(
        None, 1, {"source_id": 7, "file_url": "x"}), pdf


@pytest.mark.asyncio
async def test_mixed_pdf_sends_the_document_so_image_pages_are_read(
        monkeypatch, tmp_path):
    """기본 설정에서 혼합 PDF 의 그림 페이지가 모델에 전달되는지 본다.

    기본값이 대조군(TEXT)으로 바뀌면 이 결함이 조용히 되살아난다.
    """
    # 글은 읽혔지만 3쪽이 그림이다 — 문서를 첨부하지 않으면 3쪽이 사라진다
    (text, media, segments), pdf = await _scan(
        PdfRead("[1쪽]\n본문", 3, [3]), monkeypatch, tmp_path)
    assert media == [pdf]
    assert "3" in text


@pytest.mark.asyncio
async def test_fully_readable_pdf_sends_no_image(monkeypatch, tmp_path):
    # 그림으로 읽을 페이지가 없으면 굳이 파일을 올리지 않는다 (비용)
    (text, media, segments), _ = await _scan(
        PdfRead("[1쪽]\n본문", 2, []), monkeypatch, tmp_path)
    assert media == [] and text == "[1쪽]\n본문"


@pytest.mark.asyncio
async def test_scanned_pdf_without_text_still_goes_to_the_model(
        monkeypatch, tmp_path):
    (text, media, segments), pdf = await _scan(
        PdfRead("", 2, [1, 2]), monkeypatch, tmp_path)
    assert media == [pdf] and text


def test_real_pypdf_page_images_api_is_usable(tmp_path):
    """가짜 페이지가 아니라 실제 pypdf 로도 도는지 본다.

    `page.images` 는 pypdf 버전에 따라 동작이 달라질 수 있다. 여기서 깨지면
    위의 판단 로직이 전부 헛돈다.
    """
    from pypdf import PdfWriter

    from app.ingest.preprocess.document import read_pdf

    path = tmp_path / "빈문서.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=595, height=842)
    with path.open("wb") as handle:
        writer.write(handle)

    result = read_pdf(path)
    # 글도 그림도 없는 문서는 스캔본으로 보고 전체를 모델에 넘긴다
    assert result.page_count == 3
    assert result.text == ""
    assert result.visual_pages == [1, 2, 3]
