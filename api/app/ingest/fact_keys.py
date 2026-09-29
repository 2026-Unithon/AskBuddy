"""W2-2 사실 열쇠 — 값 파싱·slot/identity 열쇠·FactShape 조립. 순수 함수, DB 없음.

같은 사실 ⇔ 같은 매장·같은 identity_key. 충돌 ⇔ 같은 slot_key·다른 identity_key (w2-common A-2).
  - slot 은 "어느 대상의 어느 규격·속성·단계·조건인가" 다. 값은 들어가지 않는다
  - identity 는 slot + 부정 + 값(수치면 정규화한 수와 단위, 서술이면 정규화한 글)이다
  - 규격(HOT/ICE·사이즈·미상 규격)은 slot 에 들어가므로 서로 합쳐지거나 충돌하지 않는다(D19).
    규격 없음(null)도 ICE 와 다른 slot 이다 — null 은 wildcard 가 아니다
  - step_order 가 slot 에 들어가므로 절차 단계끼리는 충돌이 아니다
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.ingest.entity_names import KEY_VERSION, VariantParts

# occurrence REVIEW_PENDING 사유 코드. 카드 블록에 붙는 것은 W3 다
REASON_UNASSEMBLED = "W2_UNASSEMBLED"
REASON_VARIANT_MISMATCH = "VARIANT_SUBJECT_MISMATCH"
REASON_VARIANT_MULTI = "VARIANT_MULTI"

# 같은 단위의 다른 표기 (occurrences._UNIT_ALIASES 와 같은 집합 — private 를 import 하지 않는다)
_UNIT_TABLE = {
    "ml": ("ml", "㎖", "밀리리터", "미리", "cc"),
    "l": ("l", "ℓ", "리터"),
    "g": ("g", "그램", "그람", "gram"),
    "kg": ("kg", "㎏", "킬로그램", "킬로"),
    "min": ("분", "min", "minute", "minutes"),
    "sec": ("초", "sec", "second", "seconds"),
    "hour": ("시간", "h", "hr", "hour", "hours"),
    "°c": ("°c", "℃", "도"),
    "%": ("%", "퍼센트", "프로"),
    "oz": ("oz", "온스"),
}
_UNIT_ALIAS = {
    unicodedata.normalize("NFKC", alias).casefold(): canonical
    for canonical, aliases in _UNIT_TABLE.items() for alias in aliases
}
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_NUMBER_WITH_TAIL = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(\S+)$")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class FactShape:
    """fact_revisions 한 판을 만들 재료."""
    subject: str | None
    predicate: str | None
    variant_temperature: str | None
    variant_size: str | None
    variant_other: str | None
    quantity_value: Decimal | None
    quantity_unit: str | None
    value_text: str | None
    polarity: str
    step_order: int | None
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    original_assertion: str
    assertion: str


def _nfkc_fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _lookup_unit(raw: str) -> str | None:
    return _UNIT_ALIAS.get(_nfkc_fold(raw).strip())


def canonical_unit(unit: str | None) -> str | None:
    """단위 표에 있으면 대표 표기, 없으면 정규화한 원문(20자). 빈 값이면 None."""
    if unit is None:
        return None
    norm = _nfkc_fold(unit).strip()
    if not norm:
        return None
    return _UNIT_ALIAS.get(norm, norm[:20])


def parse_value(value: str, unit: str | None) -> tuple[Decimal | None, str | None, str | None]:
    """(수치, 단위, 서술값). 수치와 서술값은 동시에 두지 않는다.

    범위(2~3)·분수(1/2)·낱말(반)은 서술값이다. 서술값에는 단위를 뒤에 붙인다.
    쉼표는 천 단위 구분으로만 본다 — 유럽식 소수점("1,5")은 15 가 된다(알려진 한계, 아직 고치지 않음).
    """
    raw = (value or "").strip()
    compact = raw.replace(",", "")
    unit_text = (unit or "").strip()
    try:
        if _NUMBER.match(compact):
            return Decimal(compact), canonical_unit(unit_text), None
        glued = _NUMBER_WITH_TAIL.match(compact)
        if glued and not unit_text:
            tail_unit = _lookup_unit(glued.group(2))
            if tail_unit is not None:
                return Decimal(glued.group(1)), tail_unit, None
        if glued and unit_text:
            # 값에 단위가 붙어 오고 단위 칸도 같은 단위다 ("20ml" + "ml") — "20ml ml" 서술값으로 만들지 않는다
            unit_canon = canonical_unit(unit_text)
            if canonical_unit(glued.group(2)) == unit_canon:
                return Decimal(glued.group(1)), unit_canon, None
    except InvalidOperation:
        pass
    return None, None, raw + (" " + unit_text if unit_text else "")


def _decimal_text(d: Decimal) -> str:
    # 275 와 275.0 을 같게 본다
    return format(d.normalize(), "f")


def _norm_tight(text: str | None) -> str:
    """NFKC + casefold + 공백 제거 (속성·조건·예외)."""
    return _SPACES.sub("", _nfkc_fold(text or ""))


def _norm_spaced(text: str | None) -> str:
    """NFKC + casefold + 공백 1칸 (서술값)."""
    return _SPACES.sub(" ", _nfkc_fold(text or "")).strip()


def _digest(payload: list) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def slot_key(entity_id: int, s: FactShape) -> str:
    return _digest([
        KEY_VERSION, int(entity_id), s.variant_temperature, s.variant_size, s.variant_other,
        _norm_tight(s.predicate), s.step_order,
        sorted(_norm_tight(c) for c in s.conditions),
        sorted(_norm_tight(e) for e in s.exceptions),
    ])


def identity_key(entity_id: int, s: FactShape) -> str:
    slot = slot_key(entity_id, s)
    if s.quantity_value is not None:
        return _digest([KEY_VERSION, slot, s.polarity, "Q",
                        _decimal_text(s.quantity_value), s.quantity_unit])
    return _digest([KEY_VERSION, slot, s.polarity, "T", _norm_spaced(s.value_text)])


def value_signature(polarity: str, quantity_value: Decimal | None, quantity_unit: str | None,
                    value_text: str | None) -> tuple:
    """충돌하는 값 자체(부정·수치+단위 또는 서술값). 문구·조건·예외·slot 은 들어가지 않는다.

    기각한 충돌을 다시 열지 판단할 때 쓴다(결정 I) — 값이 바뀌었을 때만 다시 연다.
    """
    if quantity_value is not None:
        return (polarity, "Q", _decimal_text(Decimal(quantity_value)), quantity_unit)
    return (polarity, "T", _norm_spaced(value_text))


def _json_list(value) -> tuple[str, ...]:
    """jsonb 목록(문자열로 올 수 있다)을 순서 그대로 튜플로."""
    if value is None:
        return ()
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else []
    return tuple(str(item) for item in value)


def _merge_spec(field: str | None, hint: str | None) -> tuple[str | None, bool]:
    """(규격 값, 필드와 이름 hint 가 어긋났는가). 어긋나면 필드 값을 지킨다."""
    if field is None:
        return hint, False
    if hint is None or hint == field:
        return field, False
    return field, True


def shape_from_ledger(row, variant: VariantParts, hint_temp: str | None,
                      hint_size: str | None) -> tuple[FactShape, str | None]:
    """원장 행(또는 같은 열을 가진 dict)으로 판 재료를 만든다.

    두 번째 값은 occurrence REVIEW_PENDING 사유다. 정상은 W2_UNASSEMBLED.
    규격: 필드가 비었으면 이름 hint 를 쓰고, 둘이 다르면 필드 값을 지키며 VARIANT_SUBJECT_MISMATCH,
    HOT/ICE 가 함께 적혀 있으면 온도를 비우고 VARIANT_MULTI.
    """
    reason = REASON_UNASSEMBLED
    if variant.multi_temperature:
        temperature = None
        reason = REASON_VARIANT_MULTI
    else:
        temperature, temp_mismatch = _merge_spec(variant.temperature, hint_temp)
        if temp_mismatch:
            reason = REASON_VARIANT_MISMATCH
    size, size_mismatch = _merge_spec(variant.size, hint_size)
    if size_mismatch and reason == REASON_UNASSEMBLED:
        reason = REASON_VARIANT_MISMATCH

    subject = row["subject"]
    attribute = (row["attribute"] or "").strip()
    value = row["value"] or ""
    unit = row["unit"]
    quantity, quantity_unit, value_text = parse_value(value, unit)
    original = row["original_assertion"]
    if not (original or "").strip():
        original = f"{subject} {attribute} {value}{unit or ''}"
    shape = FactShape(
        subject=subject, predicate=attribute,
        variant_temperature=temperature, variant_size=size, variant_other=variant.other,
        quantity_value=quantity, quantity_unit=quantity_unit, value_text=value_text,
        polarity=row["polarity"] or "AFFIRM", step_order=row["step_order"],
        conditions=_json_list(row["conditions"]), exceptions=_json_list(row["exceptions"]),
        original_assertion=original, assertion=original,
    )
    return shape, reason


def original_missing(row) -> bool:
    """원장에 원문이 비어 있어 대체 문장을 만들었는가 (meta.reason=ORIGINAL_MISSING)."""
    return not (row["original_assertion"] or "").strip()
