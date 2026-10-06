from pathlib import Path

import pytest
from PIL import Image

from app.ingest.layout import pages


def _img(tmp_path: Path, name: str, size=(300, 200)) -> Path:
    p = tmp_path / name
    Image.new("RGB", size, "white").save(p)
    return p


def test_png_is_one_page(tmp_path):
    src = _img(tmp_path, "a.png")
    out = pages.page_images(src, tmp_path / "w", render_dpi=200, max_pages=None)
    assert [(p.number, p.width, p.height) for p in out] == [(1, 300, 200)]
    assert out[0].path.exists() and out[0].path.suffix == ".png"


def test_scanned_pdf_uses_embedded_image_at_native_size(tmp_path):
    pdf = tmp_path / "s.pdf"
    Image.new("RGB", (640, 480), "white").save(pdf, "PDF", resolution=144)
    out = pages.page_images(pdf, tmp_path / "w", render_dpi=200, max_pages=None)
    assert len(out) == 1 and (out[0].width, out[0].height) == (640, 480)


def test_pdf_render_fallback(tmp_path, monkeypatch):
    pdf = tmp_path / "s.pdf"
    Image.new("RGB", (144, 72), "white").save(pdf, "PDF", resolution=72)
    monkeypatch.setattr(pages, "_embedded_image", lambda page: None)
    out = pages.page_images(pdf, tmp_path / "w", render_dpi=144, max_pages=None)
    assert (out[0].width, out[0].height) == (288, 144)


def test_max_pages(tmp_path):
    pdf = tmp_path / "m.pdf"
    a, b = Image.new("RGB", (50, 50), "white"), Image.new("RGB", (50, 50), "white")
    a.save(pdf, "PDF", save_all=True, append_images=[b])
    with pytest.raises(ValueError, match="쪽 수"):
        pages.page_images(pdf, tmp_path / "w", render_dpi=72, max_pages=1)


def test_blank_page(tmp_path):
    p = pages.blank_page(tmp_path)
    assert p.number == 1 and p.path.exists()


def test_undecodable_embedded_image_falls_back_to_render(tmp_path, monkeypatch):
    """스캔 PDF의 박힌 이미지가 PIL로 디코딩할 수 없는 형식(CCITT/JBIG2/JPX)이면 렌더링으로 폴백한다."""
    pdf = tmp_path / "bad.pdf"
    Image.new("RGB", (100, 100), "white").save(pdf, "PDF", resolution=72)

    # Image.open을 monkeypatch해서 UnidentifiedImageError를 일으킨다
    original_open = Image.open
    def mock_open(fp, *args, **kwargs):
        # io.BytesIO인 경우만 예외를 던진다 (파일 열기는 정상 동작)
        if hasattr(fp, 'read') and hasattr(fp, 'seek'):
            raise Image.UnidentifiedImageError("Cannot identify image format")
        return original_open(fp, *args, **kwargs)

    monkeypatch.setattr(Image, "open", mock_open)
    out = pages.page_images(pdf, tmp_path / "w", render_dpi=144, max_pages=None)
    # 렌더링으로 폴백했으므로 144 DPI로 렌더된 크기
    assert len(out) == 1 and (out[0].width, out[0].height) == (200, 200)


def test_embedded_image_respects_page_rotation(tmp_path):
    """스캔 PDF의 박힌 이미지가 페이지 회전을 반영한다."""
    pdf = tmp_path / "rotated.pdf"
    # 비정사각형 이미지 (400x300)
    Image.new("RGB", (400, 300), "white").save(pdf, "PDF", resolution=72)

    # pypdf로 페이지를 읽고 90도 회전시킨다
    import pypdf
    reader = pypdf.PdfReader(str(pdf))
    page = reader.pages[0]
    page.rotate(90)
    writer = pypdf.PdfWriter()
    writer.add_page(page)

    # 회전된 PDF를 파일에 저장한다
    with open(pdf, "wb") as f:
        writer.write(f)

    out = pages.page_images(pdf, tmp_path / "w", render_dpi=72, max_pages=None)
    # 90도 회전했으므로 가로세로가 바뀐다 (400, 300) → (300, 400)
    assert len(out) == 1 and (out[0].width, out[0].height) == (300, 400)
