"""등록표(B-D5) — 확장자→정규화기, 로직→추출기. 확장자 × 로직 곱을 만들지 않는다(B-U9)."""
from __future__ import annotations

LOGICS = ("RECIPE", "PROCEDURE", "POLICY", "REFERENCE", "NOTICE", "NONE")
CARD_LOGICS = ("RECIPE", "PROCEDURE", "POLICY", "REFERENCE")
NORMALIZERS = ("DOC_TEXT", "DOC_IMAGE", "AUDIO", "VIDEO", "CHAT", "OWNER_TEXT")
# 구간별로 골라 추출하는 정규화기(2026-10-11 사용자 확정). 나머지는 자료 전체를 1위 로직으로
SECTIONED_NORMALIZERS = frozenset({"DOC_TEXT", "CHAT", "OWNER_TEXT"})
# 구간 글을 다시 이을 때 쓰는 구분자 — 전처리 결과 글과 같은 방식이어야 한다(Task 8)
JOINER = {"DOC_TEXT": "\n\n", "CHAT": "\n", "OWNER_TEXT": "\n\n"}

# 로직 → 추출기. 값은 기록용 추출기 이름이다. 이번에는 RECIPE 만 등록한다(B-D5)
EXTRACTORS: dict[str, str] = {"RECIPE": "extract_facts.ko"}

_BY_TYPE = {
    "VOICE": {"mp3": "AUDIO", "m4a": "AUDIO", "wav": "AUDIO"},
    "VIDEO": {"mp4": "VIDEO", "mov": "VIDEO"},
    "KAKAO": {"txt": "CHAT", "jpg": "CHAT", "jpeg": "CHAT", "png": "CHAT"},
    "SCAN": {"jpg": "DOC_IMAGE", "jpeg": "DOC_IMAGE", "png": "DOC_IMAGE", "docx": "DOC_TEXT"},
}


def registered_logics() -> tuple[str, ...]:
    return tuple(l for l in CARD_LOGICS if l in EXTRACTORS)


def normalizer_for(source_type: str, ext: str, *, pdf_has_text: bool) -> str:
    """입력 종류와 파일 검사로 코드가 가른다. 모델을 부르지 않는다(설계 4-2)."""
    if source_type == "OWNER_TEXT":
        return "OWNER_TEXT"
    if source_type == "SCAN" and ext == "pdf":
        return "DOC_TEXT" if pdf_has_text else "DOC_IMAGE"
    try:
        return _BY_TYPE[source_type][ext]
    except KeyError:
        raise ValueError(f"정규화기가 없는 입력이다: {source_type} .{ext or '없음'}") from None
