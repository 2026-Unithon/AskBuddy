"""준혁 — 문서·이미지 전처리 (M4).

PDF 는 pypdf 로 텍스트 레이어를 먼저 읽는다. 스캔본이라 텍스트가 없으면
이미지로 넘겨 Gemini 가 읽게 한다. JPG·PNG 는 항상 이미지 경로다.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40      # 이보다 짧으면 텍스트 레이어가 없다고 본다
MIN_READABLE_RATIO = 0.7 # 읽을 수 있는 글자 비율이 이보다 낮으면 깨진 것으로 본다


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


def read_pdf(path: Path) -> tuple[str, int]:
    """(텍스트, 페이지수). 텍스트가 없거나 깨졌으면 빈 문자열을 돌려준다."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = len(reader.pages)
    text = "\n".join((p.extract_text() or "").strip() for p in reader.pages).strip()

    if len(text) < MIN_TEXT_CHARS:
        logger.info("PDF 텍스트 레이어 없음 (%d자) — 이미지로 처리한다", len(text))
        return "", pages

    ratio = _readable_ratio(text)
    if ratio < MIN_READABLE_RATIO:
        logger.info("PDF 텍스트가 깨져 있다 (읽을 수 있는 비율 %.0f%%) — 이미지로 처리한다",
                    ratio * 100)
        return "", pages

    logger.info("PDF 텍스트 %d자 / %d페이지 (판독률 %.0f%%)", len(text), pages, ratio * 100)
    return text, pages


def is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png"}
