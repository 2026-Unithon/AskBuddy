"""채점 규칙 묶음 — 공통 규칙 + 업종별 추가 규칙.

공통 규칙은 어느 업종에나 항상 적용한다. 업종 규칙은 그 위에 덧붙인다(공통 + 알파).
지금 평가 자료는 전부 카페라 카페 규칙만 있다. 외식업 등 업종을 늘리면 그 업종의
추가 규칙 묶음을 `DOMAIN_EXTRAS` 에 더한다. 업종 규칙이 공통 규칙을 끄지는 못한다.

여기에는 **표현 목록과 업종 판단만** 둔다. 판정 절차는 `app.team.extraction` 에 있다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

# 카드에 반드시 드러나야 하는 규격 표기를 돌려준다(없으면 None)
LabelRule = Callable[[dict[str, Any]], "str | None"]


@dataclass(frozen=True)
class ScoringRules:
    domain: str
    # 속성 → 카드 문장에서 그 속성을 가리키는 표현. 표현이 정해진 속성은 엄격히 본다
    attribute_markers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # 정정 전후 속성이 같은 속성인지 볼 때의 별칭
    attribute_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # 규격 표기 흔들림(HOT ↔ 따뜻한 등)
    variant_synonyms: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # 카드에 꼭 있어야 하는 규격 표기 규칙
    label_rules: tuple[LabelRule, ...] = ()


# ---------------------------------------------------------------------------
# 공통 규칙 — 업종과 무관한 업무 표현
# ---------------------------------------------------------------------------

COMMON = ScoringRules(
    domain="COMMON",
    attribute_markers={
        "침지시간": ("담가", "담근", "침지"),
        "소분 단위": ("소분", "나눠", "나누어"),
        "보관위치": ("보관", "위치", "냉장고"),
        "종료시각": ("영업 종료", "마감 시간", "마감 시각"),
        "약품 투입량": ("약품",),
        "처리주체": ("직원", "아르바이트", "알바", "점주"),
        "세척제": ("세제", "세척제"),
        "제조순서": ("순서", "추출"),
    },
    attribute_aliases={
        "사용기한": ("사용기한", "사용 기한"),
        "발주주기": ("발주주기", "발주 주기"),
    },
)


# ---------------------------------------------------------------------------
# 카페 추가 규칙
# ---------------------------------------------------------------------------

def _cafe_ice_label(fact: dict[str, Any]) -> str | None:
    """얼음을 넣거나 가는 음료는 카드에 ICE 를 적는다 (2026-09-16 사용자 확정)."""
    if (fact.get("variant") or "").upper() == "ICE" or fact.get("recipe_uses_ice") is True:
        return "ICE"
    if fact.get("category_hint") != "음료제작" and fact.get("kind") != "RECIPE":
        return None
    assertion = fact.get("original_assertion") or ""
    if (re.search(r"얼음.{0,12}(넣|투입|갈아|갈고|믹싱)", assertion)
            and not re.search(r"얼음.{0,12}(않|말|금지|제외|없)", assertion)):
        return "ICE"
    return None


CAFE = ScoringRules(
    domain="CAFE",
    attribute_markers={
        "스팀우유량": ("스팀우유",), "우유량": ("우유",),
        "온수량": ("뜨거운물", "온수"), "샷 수": ("샷",),
    },
    attribute_aliases={
        "우유량": ("우유량", "우유 용량", "스팀우유량"),
    },
    variant_synonyms={
        "HOT": ("hot", "핫", "따뜻", "뜨거", "온음료"),
        "ICE": ("ice", "아이스", "냉", "차가", "찬"),
    },
    label_rules=(_cafe_ice_label,),
)

# 업종 → 추가 규칙. 업종을 늘리면 여기에 더한다
DOMAIN_EXTRAS: dict[str, ScoringRules] = {"CAFE": CAFE}


def rules_for(domain: str | None) -> ScoringRules:
    """공통 규칙에 업종 규칙을 덧붙인다. 업종이 없으면 공통 규칙만."""
    if not domain or domain == "COMMON":
        return COMMON
    extra = DOMAIN_EXTRAS.get(domain)
    if extra is None:
        raise ValueError(f"채점 규칙이 없는 업종: {domain}")
    for key in extra.attribute_markers:
        if key in COMMON.attribute_markers:
            raise ValueError(f"업종 규칙이 공통 속성 표현을 덮을 수 없다: {key}")
    return ScoringRules(
        domain=f"COMMON+{extra.domain}",
        attribute_markers={**COMMON.attribute_markers, **extra.attribute_markers},
        attribute_aliases={**COMMON.attribute_aliases, **extra.attribute_aliases},
        variant_synonyms={**COMMON.variant_synonyms, **extra.variant_synonyms},
        label_rules=COMMON.label_rules + extra.label_rules,
    )


# 평가 자료(eval-a·eval-b)가 전부 카페라 기본은 공통 + 카페다.
# 다른 업종 자료를 채점할 때는 호출부가 rules_for(업종) 을 넘긴다
DEFAULT_RULES = rules_for("CAFE")
