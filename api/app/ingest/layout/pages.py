"""① 쪽 이미지. 스캔 PDF 는 박힌 원본 이미지를 그대로, 벡터 PDF 는 렌더링, 사진은 그대로."""
import io
from pathlib import Path

from PIL import Image

from app.ingest.layout.schemas import PageImage

_MIN_TEXT_CHARS = 20   # 이보다 글이 적고 이미지가 하나면 스캔 쪽으로 본다


def _embedded_image(page) -> Image.Image | None:
    """스캔 쪽이면 박힌 이미지 하나를 돌려준다. 글이 있거나 이미지가 여럿이면 None."""
    try:
        images = list(page.images)
        text = (page.extract_text() or "").strip()
        if len(images) != 1 or len(text) >= _MIN_TEXT_CHARS:
            return None
        img = Image.open(io.BytesIO(images[0].data)).convert("RGB")
        # 페이지 회전을 반영한다. 스캔 PDF는 원본 이미지에 회전을 따로 저장하기도 한다
        rotation = getattr(page, "rotation", None) or 0
        if rotation:
            img = img.rotate(-rotation, expand=True)
        return img
    except Exception:
        return None


def _render(path: Path, index: int, dpi: int) -> Image.Image:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        return pdf[index].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        pdf.close()


def _save(img: Image.Image, workdir: Path, number: int) -> PageImage:
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / f"page-{number}.png"
    img.save(out)
    return PageImage(number, out, img.width, img.height)


def page_images(path: Path, workdir: Path, *, render_dpi: int,
                max_pages: int | None) -> list[PageImage]:
    if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
        return [_save(Image.open(path).convert("RGB"), workdir, 1)]
    import pypdf

    reader = pypdf.PdfReader(str(path))
    if max_pages is not None and len(reader.pages) > max_pages:
        raise ValueError(f"쪽 수 {len(reader.pages)} 가 상한 {max_pages} 를 넘는다")
    out = []
    for i, page in enumerate(reader.pages):
        img = _embedded_image(page) or _render(path, i, render_dpi)
        out.append(_save(img, workdir, i + 1))
    return out


def blank_page(workdir: Path) -> PageImage:
    """mock 모드용 빈 쪽. 원본을 내려받지 않는 mock 에서 경로를 끝까지 돌리기 위해 쓴다."""
    return _save(Image.new("RGB", (800, 600), "white"), workdir, 1)
