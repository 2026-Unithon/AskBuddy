"""W2-1 대상 이름 정규화 — 순수 함수, DB 없음.

대상(entity)은 서버가 이름 규칙으로만 정한다. 규칙은 일부러 보수적이다.
  - 공백·대소문자·문장부호 차이만 같은 이름으로 본다
  - 규격 낱말(HOT/ICE·사이즈)이 **통째 토큰**일 때만 이름에서 떼어 hint 로 돌려준다.
    대상 이름·별칭에는 규격을 넣지 않는다(D19 — 규격은 사실의 variant 다)
  - 조사·어미 제거, 동의어 사전, 로마자 변환은 하지 않는다
  - 비슷한 이름(한 글자 차이·포함)은 candidate_reason 으로 **후보만** 판정한다. 합치지 않는다
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

TEMPERATURE_TOKENS = {"hot": "HOT", "핫": "HOT", "ice": "ICE", "iced": "ICE", "아이스": "ICE"}
SIZE_TOKENS = {"s": "S", "small": "S", "스몰": "S", "m": "M", "medium": "M", "미디엄": "M",
               "r": "R", "regular": "R", "레귤러": "R", "l": "L", "large": "L", "라지": "L",
               "tall": "TALL", "톨": "TALL", "grande": "GRANDE", "그란데": "GRANDE"}
# 규격 칸(parse_variant)에서만 온도로 보는 서술어. 이름에서는 떼지 않는다
_VARIANT_ONLY_TEMPERATURE = {"뜨거운": "HOT", "따뜻한": "HOT", "차가운": "ICE"}
# 열쇠 규칙이 바뀌면 올린다 (fact_keys 의 slot/identity 열쇠에도 들어간다)
KEY_VERSION = "w2k1"

_SEPARATORS = re.compile(r"[\s/(),\[\]{}·•|:+\-_.]+")
# 한글·라틴·숫자(\w 중 _ 제외)가 아닌 문자
_NON_WORD = re.compile(r"[\W_]+")


@dataclass(frozen=True)
class NameParts:
    name_norm: str                  # 조회·유일성 열쇠. 빈 문자열이면 대상 결정 불가
    display_name: str               # canonical_name 후보 (규격 낱말만 뺀 원문, 공백 1칸)
    temperature_hint: str | None    # 이름에서 떼어낸 HOT/ICE
    size_hint: str | None           # 이름에서 떼어낸 사이즈


@dataclass(frozen=True)
class VariantParts:
    temperature: str | None         # "HOT" | "ICE" | None
    size: str | None                # SIZE_TOKENS 값 | None
    other: str | None               # 알 수 없는 규격 낱말(정규화). 슬롯 열쇠에만 쓴다
    multi_temperature: bool         # "HOT/ICE" 처럼 둘 다


def _tokens(text: str) -> list[str]:
    return [t for t in _SEPARATORS.split(text) if t]


def _single(values: set[str]) -> str | None:
    """떼어낸 값이 한 종류일 때만 hint 로 쓴다. 서로 다른 값이 둘 이상이면 모른다."""
    return next(iter(values)) if len(values) == 1 else None


def normalize_subject(raw: str) -> NameParts:
    """사실의 subject 를 대상 열쇠로 바꾼다. 규칙 순서는 고정이다 (w2-common A-1)."""
    text = unicodedata.normalize("NFKC", raw or "")
    tokens = _tokens(text)
    kept: list[str] = []
    temperatures: set[str] = set()
    sizes: set[str] = set()
    for token in tokens:
        key = token.casefold()
        # 통째 토큰만 뗀다 — 핫초코·아이스티·아이스크림은 그대로 남는다
        if key in TEMPERATURE_TOKENS:
            temperatures.add(TEMPERATURE_TOKENS[key])
        elif key in SIZE_TOKENS:
            sizes.add(SIZE_TOKENS[key])
        else:
            kept.append(token)
    if not kept:
        # 이름 전체가 규격 낱말(예: 아이스) — 떼면 이름이 사라지므로 떼지 않는다
        kept, temperatures, sizes = tokens, set(), set()
    name_norm = _NON_WORD.sub("", "".join(kept).casefold())
    return NameParts(name_norm=name_norm, display_name=" ".join(kept),
                     temperature_hint=_single(temperatures), size_hint=_single(sizes))


def normalize_alias(raw: str) -> str:
    return normalize_subject(raw).name_norm


def parse_variant(raw: str | None) -> VariantParts:
    """원장 variant 문자열 하나(HOT/ICE·사이즈·기타가 섞임)를 칸별로 나눈다."""
    tokens = _tokens(unicodedata.normalize("NFKC", raw or "").casefold())
    temperatures: set[str] = set()
    size_tokens: list[str] = []
    other: list[str] = []
    for token in tokens:
        temperature = TEMPERATURE_TOKENS.get(token) or _VARIANT_ONLY_TEMPERATURE.get(token)
        if temperature:
            temperatures.add(temperature)
        elif token in SIZE_TOKENS:
            size_tokens.append(token)
        else:
            other.append(token)
    sizes = {SIZE_TOKENS[t] for t in size_tokens}
    size = _single(sizes)
    if len(sizes) > 1:
        # 사이즈가 둘 이상이면 한 칸에 담지 못한다. 규격 없음(null)과 섞이지 않도록 기타로 남긴다
        other.extend(size_tokens)
    return VariantParts(temperature=_single(temperatures), size=size,
                        other=" ".join(sorted(other)) or None,
                        multi_temperature=len(temperatures) > 1)


def strip_temperature(raw: str | None) -> str:
    """규격 문자열에서 온도 낱말(HOT/ICE 와 규격 칸 서술어)만 뺀 나머지. 원래 표기, 공백 1칸.

    W3-0 HOT/ICE 나누기가 쓴다 — 'HOT/ICE L' 을 'HOT L'·'ICE L' 로 나눌 때 사이즈 등
    나머지 규격 낱말을 그대로 남긴다.
    """
    tokens = _tokens(unicodedata.normalize("NFKC", raw or ""))
    kept = [t for t in tokens
            if t.casefold() not in TEMPERATURE_TOKENS
            and t.casefold() not in _VARIANT_ONLY_TEMPERATURE]
    return " ".join(kept)


def _edit_distance_is_one(a: str, b: str) -> bool:
    """코드포인트 Levenshtein 거리가 정확히 1 인가."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:]      # 한 글자 바뀜
    return a[i:] == b[i + 1:]               # 한 글자 더함


def candidate_reason(new_norm: str, existing_norm: str) -> str | None:
    """두 대상이 같을 수도 있는 이유. 판정일 뿐이며 이 결과로 대상을 합치지 않는다."""
    if new_norm == existing_norm:
        return None
    if min(len(new_norm), len(existing_norm)) >= 3 and _edit_distance_is_one(new_norm, existing_norm):
        return "EDIT1"
    short, long_ = sorted((new_norm, existing_norm), key=len)
    if len(short) >= 2 and short in long_:
        return "CONTAINS"
    return None
