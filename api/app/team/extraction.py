"""추출 품질 채점 — 사실 정답지 대비 카드가 무엇을 담았는가.

순수 함수만 둔다. DB·LLM 을 부르지 않는다.

설계 원칙: **과소평가하는 방향으로 판정한다.**
경계가 애매하면 COVERED 로 세지 않고 PARTIAL 로 내린다.
품질 지표는 부풀려지는 것보다 낮게 잡히는 쪽이 안전하다 — 높게 나온 수치를 믿고
검색을 고치러 가면 엉뚱한 데를 파게 된다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

Verdict = Literal["COVERED", "PARTIAL", "MISSING"]

_WORD = re.compile(r"[0-9A-Za-z가-힣]+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

# 규격 표기 흔들림. HOT 카드와 ICE 카드가 뒤섞이는 것을 막는다
_VARIANT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "HOT": ("hot", "핫", "따뜻", "뜨거", "온음료"),
    "ICE": ("ice", "아이스", "냉", "차가", "찬"),
}

# 값 비교에서 의미를 갖지 못하는 말들
_VALUE_STOP = {
    "정도", "가량", "까지", "부터", "이상", "이하", "약", "그리고", "또는",
    "넣는다", "넣고", "한다", "하고", "있다", "있음", "사용", "기준",
}


def normalize(text: str) -> str:
    """표기 흔들림만 지운다. 낱말을 자르지 않는다."""
    return " ".join(_WORD.findall((text or "").lower()))


def _tokens(text: str) -> set[str]:
    return {t for t in normalize(text).split() if t not in _VALUE_STOP and len(t) >= 2}


def numbers_in(text: str) -> list[str]:
    """숫자만 뽑는다. 단위는 표기가 흔들려도(ml/㎖/온스) 숫자는 같다."""
    out = []
    for raw in _NUMBER.findall(text or ""):
        value = raw.replace(",", "")
        # 275.0 과 275 를 같게 본다
        if value.endswith(".0"):
            value = value[:-2]
        out.append(value)
    return out


def variant_present(variant: str | None, card_text: str) -> bool:
    """규격이 카드에 드러나는가. 규격이 없는 사실은 항상 통과."""
    if not variant:
        return True
    haystack = normalize(card_text)
    for token in _VARIANT_SYNONYMS.get(variant.upper(), (variant.lower(),)):
        if token in haystack:
            return True
    return False


@dataclass(frozen=True)
class FactMatch:
    verdict: Verdict
    card_id: int | None
    score: float
    reason: str
    subject_hit: bool = False
    value_hit: bool = False
    variant_hit: bool = False
    number_ratio: float | None = None


def _score_one(fact: dict[str, Any], card_text: str) -> FactMatch:
    subject = fact.get("subject") or ""
    value = fact.get("value") or ""
    variant = fact.get("variant")

    haystack = normalize(card_text)
    subject_hit = bool(subject) and normalize(subject) in haystack
    variant_hit = variant_present(variant, card_text)

    want_numbers = numbers_in(value)
    if want_numbers:
        have = set(numbers_in(card_text))
        matched = [n for n in want_numbers if n in have]
        ratio = len(matched) / len(want_numbers)
        # 숫자가 있는 값은 숫자가 전부 맞아야 값이 담긴 것으로 본다.
        # 하나라도 빠지면 '275ml 를 27ml 로 적은' 왜곡을 통과시키게 된다
        value_hit = ratio == 1.0
    else:
        want = _tokens(value)
        ratio = (len(want & _tokens(card_text)) / len(want)) if want else 0.0
        value_hit = ratio >= 0.6

    if subject_hit and value_hit and variant_hit:
        return FactMatch("COVERED", None, ratio, "subject·value·variant 일치",
                         True, True, True, ratio)
    if subject_hit and value_hit and not variant_hit:
        # 값은 맞지만 규격 표기가 없다. HOT/ICE 가 섞였을 수 있으므로 COVERED 로 올리지 않는다
        return FactMatch("PARTIAL", None, ratio, "규격(variant) 표기 없음",
                         True, True, False, ratio)
    if subject_hit and not value_hit:
        return FactMatch("PARTIAL", None, ratio, "대상은 있으나 값이 다르거나 없음",
                         True, False, variant_hit, ratio)
    if value_hit and not subject_hit:
        return FactMatch("PARTIAL", None, ratio, "값은 있으나 대상이 다름",
                         False, True, variant_hit, ratio)
    return FactMatch("MISSING", None, ratio, "대상·값 모두 없음",
                     False, False, variant_hit, ratio)


_RANK = {"COVERED": 2, "PARTIAL": 1, "MISSING": 0}


def match_fact(fact: dict[str, Any], cards: list[dict[str, Any]]) -> FactMatch:
    """사실 하나를 카드 전체와 대조해 가장 좋은 판정을 돌려준다.

    카드를 가로질러 합치지 않는다. **한 카드 안에** 대상과 값이 같이 있어야 한다.
    여러 카드를 이어붙여 인정하면, 신입이 카드 하나만 읽고는 답을 못 얻는데도
    담았다고 세게 된다.
    """
    best = FactMatch("MISSING", None, 0.0, "대조할 카드가 없음")
    for card in cards:
        text = f"{card.get('title') or ''} {card.get('content') or ''}"
        m = _score_one(fact, text)
        if (_RANK[m.verdict], m.score) > (_RANK[best.verdict], best.score):
            best = FactMatch(
                m.verdict, int(card["card_id"]), m.score, m.reason,
                m.subject_hit, m.value_hit, m.variant_hit, m.number_ratio,
            )
    return best


@dataclass
class ExtractionReport:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def add(self, fact: dict[str, Any], match: FactMatch, source_type: str) -> None:
        self.rows.append({
            "fact_id": fact.get("fact_id"),
            "subject": fact.get("subject"),
            "variant": fact.get("variant"),
            "attribute": fact.get("attribute"),
            "value": fact.get("value"),
            "must_have": bool(fact.get("must_have")),
            "source_key": fact.get("source_key"),
            "source_type": source_type,
            "verdict": match.verdict,
            "card_id": match.card_id,
            "score": round(match.score, 4),
            "reason": match.reason,
            "subject_hit": match.subject_hit,
            "value_hit": match.value_hit,
            "variant_hit": match.variant_hit,
        })


def aggregate(rows: list[dict[str, Any]], card_count: int = 0) -> dict[str, Any]:
    """E-O0 추출 손실과 부속 지표. source type 별로 갈라 낸다.

    전체 손실률만으로는 어느 프롬프트를 먼저 고칠지 정할 수 없다 (13.1).
    """
    total = len(rows)
    if total == 0:
        return {"fact_count": 0, "card_count": card_count}

    def bucket(subset: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(subset)
        if n == 0:
            return {"fact_count": 0}
        covered = sum(1 for r in subset if r["verdict"] == "COVERED")
        partial = sum(1 for r in subset if r["verdict"] == "PARTIAL")
        return {
            "fact_count": n,
            "covered": covered,
            "partial": partial,
            "missing": n - covered - partial,
            "recall": round(covered / n, 4),
            # E-O0 — 원본에 있는데 카드에 없는 비율. 시스템 정확도의 천장
            "loss": round(1 - covered / n, 4),
        }

    by_type: dict[str, Any] = {}
    for r in rows:
        by_type.setdefault(r["source_type"] or "UNKNOWN", []).append(r)

    must = [r for r in rows if r["must_have"]]
    overall = bucket(rows)
    return {
        **overall,
        "card_count": card_count,
        # 치명 누락 — must_have 사실을 놓친 것. 여기가 0 이 아니면 서비스가 성립하지 않는다
        "must_have": bucket(must),
        "must_have_missing_ids": [
            r["fact_id"] for r in must if r["verdict"] != "COVERED"
        ],
        "by_source_type": {k: bucket(v) for k, v in sorted(by_type.items())},
        # 값이 틀어진 것과 아예 없는 것을 가른다. 원인이 다르다
        "partial_reasons": _count(r["reason"] for r in rows if r["verdict"] == "PARTIAL"),
    }


def _count(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
