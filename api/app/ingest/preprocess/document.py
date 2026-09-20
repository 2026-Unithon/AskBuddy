"""준혁 — 문서·이미지 전처리 (M4).

PDF 는 pypdf 로 텍스트 레이어를 먼저 읽는다. 스캔본이라 텍스트가 없으면
이미지로 넘겨 Gemini 가 읽게 한다. JPG·PNG 는 항상 이미지 경로다.
"""
import logging
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40      # 이보다 짧으면 텍스트 레이어가 없다고 본다
MIN_READABLE_RATIO = 0.7 # 읽을 수 있는 글자 비율이 이보다 낮으면 깨진 것으로 본다
MIN_PAGE_TEXT_CHARS = 20 # 페이지 단위 기준. 그림이 있는데 이보다 짧으면 내용이 그림에 있다


def _readable_ratio(text: str) -> float:
    """한글·영숫자·일반 기호의 비율.

    폰트를 커스텀 인코딩으로 심은 PDF 는 텍스트 레이어가 있어도 추출하면
    '஠ಕ ѐ' 같은 쓰레기가 나온다. 길이만 보면 정상으로 통과해 모델에 그대로 들어간다.
    """
    sample = [c for c in text if not c.isspace()]
    if not sample:
        return 0.0
    good = sum(
        1 for c in sample
        if c.isascii() and (c.isprintable())
        or "\uac00" <= c <= "\ud7a3"      # 한글 완성형
        or "\u3130" <= c <= "\u318f"      # 한글 자모
        or "\u4e00" <= c <= "\u9fff"      # 한자
    )
    return good / len(sample)


class PageProbe(NamedTuple):
    """한 페이지에서 건진 것. 판단은 문서 전체가 아니라 페이지마다 한다."""

    text: str
    has_images: bool


def needs_visual_read(probe: PageProbe) -> bool:
    """이 페이지를 모델이 눈으로 읽어야 하는가.

    그림이 없으면 추출된 글이 그 페이지의 전부다. 그림이 있는데 글이 없거나
    깨졌으면 내용이 그림 안에 있다 — 표·손글씨·사진이 그렇다.

    한계: 로고만 박힌 본문 페이지는 글이 충분하므로 넘기지 않는다. 그래서
    그림 안에만 있는 보조 정보는 놓칠 수 있다. 페이지를 이미지로 굽지 않는 한
    (현재 pypdf 만 있어 래스터화 불가) 이보다 정확히 가를 수 없다.
    """
    if not probe.has_images:
        return False
    if len(probe.text.strip()) < MIN_PAGE_TEXT_CHARS:
        return True
    return _readable_ratio(probe.text) < MIN_READABLE_RATIO


class PdfRead(NamedTuple):
    """PDF 에서 건진 것과, 눈으로 읽어야 남는 페이지."""

    text: str
    page_count: int
    visual_pages: list[int]      # 1부터 세는 페이지 번호


def read_pdf(path: Path) -> PdfRead:
    """페이지마다 따로 판단한다.

    예전에는 문서 전체 텍스트를 한 덩어리로 합쳐 판독률을 쟀다. 그래서 앞 몇
    장만 글이 제대로 있으면 문서 전체가 '읽혔다'가 되고, 뒤의 표·사진 페이지는
    모델에 아예 전달되지 않았다. 이제 읽힌 페이지의 글을 모으고, 그림에 내용이
    있는 페이지는 번호로 남겨 호출부가 따로 넘기게 한다.
    """
    import pypdf

    reader = pypdf.PdfReader(str(path))
    pages = list(reader.pages)

    readable: list[str] = []
    visual: list[int] = []
    for number, page in enumerate(pages, start=1):
        text = (page.extract_text() or "").strip()
        try:
            has_images = bool(page.images)
        except Exception:
            # 이미지 목록을 못 읽는 페이지는 그림이 있다고 보고 눈으로 확인한다
            has_images = True
        if needs_visual_read(PageProbe(text=text, has_images=has_images)):
            visual.append(number)
            continue
        if text:
            readable.append(f"[{number}쪽]\n{text}")

    body = "\n\n".join(readable).strip()
    ratio = _readable_ratio(body) if body else 0.0

    # 읽힌 글이 너무 적거나 깨져 있으면 문서 전체를 그림으로 넘긴다
    if len(body) < MIN_TEXT_CHARS or ratio < MIN_READABLE_RATIO:
        logger.info("PDF 텍스트 레이어 부족 (%d자, 판독률 %.0f%%) — 전체를 이미지로 처리한다",
                    len(body), ratio * 100)
        return PdfRead("", len(pages), list(range(1, len(pages) + 1)))

    if visual:
        logger.info("PDF 텍스트 %d자 / %d페이지 (판독률 %.0f%%), 그림으로 읽을 페이지 %s",
                    len(body), len(pages), ratio * 100, visual)
    else:
        logger.info("PDF 텍스트 %d자 / %d페이지 (판독률 %.0f%%)",
                    len(body), len(pages), ratio * 100)
    return PdfRead(body, len(pages), visual)


def is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png"}
