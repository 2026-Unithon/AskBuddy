"""W3-0 §3-1 — HOT/ICE 가 함께 적힌 사실을 규격별 두 사실로 나눈다 (원장 단계). 순수 함수, DB 없음.

D19 — 사실(source_facts)은 variant 로 갈라 저장한다. 추출 모델이 'HOT/ICE' 처럼 두 온도를 한
사실로 낸 경우, 값이 공통이라는 판단은 모델이 한 사실로 냈다는 점에 기댄다(설계 §6 위험).
  - 대상: entity_names.parse_variant 가 온도를 둘 다 읽은 사실(multi_temperature)
  - 결과: HOT 사실 + ICE 사실. 값·단위·부정·조건·예외·순서·근거·원문은 같고, 사이즈 등 나머지
    규격 낱말은 남긴다
  - local_ref: '<원래 ref>~HOT', '<원래 ref>~ICE'. 원장 local_ref 는 40자로 잘리므로 원래 ref 의
    앞 36자만 쓴다 — 잘려도 두 이름표가 갈린다
  - requires: 다른 사실이 원래 ref 를 가리키면 둘 다를 가리킨다. 가리키는 쪽도 갈라진 사실이면
    같은 온도 쪽만 가리킨다(HOT 절차가 ICE 선행에 매이지 않게)
  - 나눈 표시를 check_flags 에 남긴다(근거 위치 행으로 영속) — 원래 한 문장이었음을 검수에서 안다
  - 입력 객체는 바꾸지 않는다. 조립 입력과 복구 캐시가 같은 객체를 쓴다
  - 온도 외 규격(사이즈 둘 이상 등)은 나누지 않는다
pipeline._persist_ledger 가 w_entity_revision_enabled 일 때만 부른다. 나눌 사실이 없으면 같은
객체를 그대로 돌려주므로 원장 쓰기가 꺼짐과 같다.
"""
from __future__ import annotations

from app.ingest.entity_names import parse_variant, strip_temperature

SPLIT_SEPARATOR = "~"
TEMPERATURES = ("HOT", "ICE")
VERDICT_SPLIT = "VARIANT_SPLIT"
_LOCAL_REF_MAX = 40                                    # source_facts.local_ref 저장 길이
_BASE_MAX = _LOCAL_REF_MAX - len(SPLIT_SEPARATOR) - 3  # 36 — '~HOT'·'~ICE' 자리를 남긴다


def split_ref(ref: str, temperature: str) -> str:
    """갈라진 사실의 이름표. 원장 local_ref(40자) 안에서 HOT·ICE 가 갈린다."""
    return f"{ref[:_BASE_MAX]}{SPLIT_SEPARATOR}{temperature}"


def split_refs(ref: str) -> tuple[str, str]:
    """원래 ref 하나의 갈라진 이름표 둘 (HOT, ICE 순)."""
    return split_ref(ref, "HOT"), split_ref(ref, "ICE")


def needs_split(variant: str | None) -> bool:
    """규격 칸에 HOT 과 ICE 가 함께 적혔는가."""
    return parse_variant(variant).multi_temperature


def _rewrite(requires, split: set[str], temperature: str | None) -> list[str]:
    """선행 참조를 갈라진 이름표로 바꾼다. temperature 가 있으면 그 온도 쪽만 가리킨다."""
    out: list[str] = []
    for ref in requires:
        if ref not in split:
            out.append(ref)
        elif temperature is None:
            out.extend(split_refs(ref))
        else:
            out.append(split_ref(ref, temperature))
    return out


def split_hot_ice(assertions: list) -> list:
    """HOT/ICE 동시 사실을 둘로 나눈 새 목록. 나눌 사실이 없으면 같은 객체들을 그대로 담는다."""
    split = {a.local_ref for a in assertions if needs_split(a.variant)}
    if not split:
        return list(assertions)
    out = []
    for a in assertions:
        if a.local_ref not in split:
            requires = _rewrite(a.requires, split, None)
            if requires == list(a.requires):
                out.append(a)
            else:
                out.append(a.model_copy(deep=True, update={"requires": requires}))
            continue
        rest = strip_temperature(a.variant)
        for temperature in TEMPERATURES:
            copy = a.model_copy(deep=True, update={
                "local_ref": split_ref(a.local_ref, temperature),
                "variant": " ".join(part for part in (temperature, rest) if part),
                "requires": _rewrite(a.requires, split, temperature),
            })
            # deep copy 라 _check_flags 는 사본마다 따로다. 표시는 사본에만 붙는다
            copy.check_flags.append({
                "field": "variant", "verdict": VERDICT_SPLIT, "value": a.variant,
                "variant_split": "HOT_ICE", "from_ref": a.local_ref})
            out.append(copy)
    return out
