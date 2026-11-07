"""PDF 입력 방식의 분기를 검증한다 — 2026-11-07 부터 HYBRID 하나로 고정했다(S11, 스위치 삭제).

HYBRID — 글 + 그림 페이지가 남아 있을 때만 원본을 붙인다(비용 절충).
글이 아예 없는 스캔본은 늘 원본을 보낸다. 안 보내면 빈손이다.
(예전 TEXT·FILE·BOTH 실험 arm 은 없앴다 — 한 번 호출 측정 SINGLE_CALL_EXTRACT_3RUNS_20261106)
"""
import pytest

from app.ingest import pipeline
from app.ingest.preprocess.document import PdfRead


async def _scan(mode, read_result, monkeypatch, tmp_path):
    pdf = tmp_path / "문서.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    async def noop(*a, **kw):
        return None

    monkeypatch.setattr(pipeline.repo, "get_scan",
                        lambda conn, sid: _async({"scan_id": 1}))
    monkeypatch.setattr(pipeline.repo, "update_scan_result", noop)
    monkeypatch.setattr(pipeline, "_download",
                        lambda pool, store, src: _async(pdf))
    monkeypatch.setattr(pipeline.document, "read_pdf", lambda _p: read_result)
    import app.config
    monkeypatch.setattr(app.config, "get_settings", lambda: _Settings(mode))
    result = await pipeline._preprocess_scan(
        _NullPool(), 1, {"source_id": 7, "file_url": "x"})
    return result, pdf


async def _async(value):
    return value


class _Settings:
    def __init__(self, mode):
        self.pdf_input_mode = mode
        self.ingest_mode = "real"


READ = PdfRead("[1쪽]\n에스프레소는 원두 18g 으로 내린다.", 3, [3])


@pytest.mark.asyncio
async def test_hybrid_attaches_only_when_an_image_page_remains(monkeypatch, tmp_path):
    assert pipeline.PDF_INPUT_MODE == "HYBRID"
    (text, media, _), pdf = await _scan("HYBRID", READ, monkeypatch, tmp_path)
    assert media == [pdf] and "3쪽" in text and "18g" in text

    clean = PdfRead("[1쪽]\n에스프레소는 원두 18g 으로 내린다.", 2, [])
    (text, media, _), _ = await _scan("HYBRID", clean, monkeypatch, tmp_path)
    assert media == []


@pytest.mark.asyncio
async def test_a_scan_without_text_layer_always_sends_the_document(monkeypatch, tmp_path):
    blank = PdfRead("", 2, [1, 2])
    (text, media, _), pdf = await _scan("HYBRID", blank, monkeypatch, tmp_path)
    assert media == [pdf]


class _NullPool:
    """전처리는 풀을 받아 DB 호출마다 짧게 빌린다. 연결은 대역 repo 가 쓰지 않는다."""

    def acquire(self):
        return _NullLease()


class _NullLease:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False
