"""PDF 입력 방식 3-arm 실험의 분기를 검증한다.

A(TEXT)    pypdf 텍스트만 — 기존 동작이자 대조군. 표 구조가 깨질 수 있다
B(FILE)    PDF 원본만 — Gemini 가 페이지를 직접 읽는다
C(BOTH)    둘 다 — 잃는 것이 없는 대신 비용이 든다
D(HYBRID)  텍스트 + 그림 페이지가 있을 때만 원본 — 비용 절충

arm 이 섞이면 비교가 성립하지 않는다. TEXT 가 그림 페이지에서 원본을 붙이면
그것은 TEXT 가 아니라 HYBRID 다.

어느 쪽이 정확한지는 측정 전까지 모른다. 그래서 고르게 만든다.
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
async def test_text_arm_never_attaches_even_with_image_pages(monkeypatch, tmp_path):
    # 대조군은 순수해야 한다. 그림 페이지가 있어도 붙이지 않는다
    (text, media, _), _ = await _scan("TEXT", READ, monkeypatch, tmp_path)
    assert media == [] and "18g" in text


@pytest.mark.asyncio
async def test_hybrid_arm_attaches_only_when_an_image_page_remains(
        monkeypatch, tmp_path):
    (text, media, _), pdf = await _scan("HYBRID", READ, monkeypatch, tmp_path)
    assert media == [pdf] and "3쪽" in text

    clean = PdfRead("[1쪽]\n에스프레소는 원두 18g 으로 내린다.", 2, [])
    (text, media, _), _ = await _scan("HYBRID", clean, monkeypatch, tmp_path)
    assert media == []


@pytest.mark.asyncio
async def test_file_arm_sends_only_the_document(monkeypatch, tmp_path):
    (text, media, _), pdf = await _scan("FILE", READ, monkeypatch, tmp_path)
    assert media == [pdf]
    # 텍스트 레이어를 쓰지 않는 arm 이므로 추출한 본문을 붙이지 않는다
    assert "18g" not in text


@pytest.mark.asyncio
async def test_both_arm_sends_text_and_the_document(monkeypatch, tmp_path):
    (text, media, _), pdf = await _scan("BOTH", READ, monkeypatch, tmp_path)
    assert media == [pdf] and "18g" in text


@pytest.mark.asyncio
async def test_a_scan_without_text_layer_always_sends_the_document(
        monkeypatch, tmp_path):
    # 글이 아예 없으면 어느 arm 이든 문서를 보내야 한다. 안 보내면 빈손이다
    blank = PdfRead("", 2, [1, 2])
    for mode in ("TEXT", "FILE", "BOTH", "HYBRID"):
        (text, media, _), pdf = await _scan(mode, blank, monkeypatch, tmp_path)
        assert media == [pdf], f"{mode} arm 이 스캔본을 버렸다"


class _NullPool:
    """전처리는 풀을 받아 DB 호출마다 짧게 빌린다. 연결은 대역 repo 가 쓰지 않는다."""

    def acquire(self):
        return _NullLease()


class _NullLease:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False
