"""추출 품질 채점 — 사실 정답지 대비 카드가 무엇을 담았는가.

순수 함수만 둔다. DB·LLM 을 부르지 않는다.

설계 원칙: **과소평가하는 방향으로 판정한다.**
경계가 애매하면 COVERED 로 세지 않고 PARTIAL 로 내린다.
품질 지표는 부풀려지는 것보다 낮게 잡히는 쪽이 안전하다 — 높게 나온 수치를 믿고
검색을 고치러 가면 엉뚱한 데를 파게 된다.
"""
from __future__ import annotations

from collections import Counter

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

Verdict = Literal["COVERED", "PARTIAL", "MISSING", "UNDETERMINED"]

SCORER_VERSION = "w_fact_score/v3"

# 후보의 속성과 값을 같은 문장 안에서 확인한다. dev 사실 ID와 무관한 업무 표현이다.
_CARD_ATTRIBUTE_MARKERS = {
    "스팀우유량": ("스팀우유",), "우유량": ("우유",),
    "온수량": ("뜨거운물", "온수"), "침지시간": ("담가", "담근", "침지"),
    "샷 수": ("샷",), "소분 단위": ("소분", "나눠", "나누어"),
    "보관위치": ("보관", "위치", "냉장고"),
    "종료시각": ("영업 종료", "마감 시간", "마감 시각"),
    "약품 투입량": ("약품",), "처리주체": ("직원", "아르바이트", "알바", "점주"),
    "세척제": ("세제", "세척제"), "제조순서": ("순서", "추출"),
}


def _attribute_markers(fact):
    attribute = fact.get("attribute") or ""
    return _CARD_ATTRIBUTE_MARKERS.get(attribute, (attribute,))


def _has_attribute(fact, text):
    return any(normalize(marker) in normalize(text) for marker in _attribute_markers(fact) if marker)


def _card_context(fact, card):
    title, content = card.get("title") or "", card.get("content") or ""
    # 소수점은 문장 경계로 자르지 않는다.
    clauses = re.split(r"[.!?](?!\d)|[;\n]|이며|하며", content)
    relevant = [c for c in clauses if _has_attribute(fact, c)]
    if fact.get("attribute") == "종료시각":
        # '영업 종료 전까지 20:00부터 주문'은 종료시각의 값 지정이 아니다.
        assigned = [c for c in relevant if re.search(
            r"(?:영업\s*종료(?:\s*(?:시각|시간))?|마감\s*(?:시각|시간))\s*(?:은|는|이|:)?\s*\d", c)]
        if assigned:
            relevant = assigned
    subject_clauses = [c for c in relevant if _subject_in(fact.get("subject") or "", c)]
    if subject_clauses:
        relevant = subject_clauses
    # 제목은 대상 연결에만 사용한다. 제목의 숫자는 본문 값을 대신하지 않는다.
    return title + " " + " ".join(relevant or clauses)


def requires_ice_label(fact):
    if (fact.get("variant") or "").upper() == "ICE" or fact.get("recipe_uses_ice") is True:
        return True
    if fact.get("category_hint") != "음료제작" and fact.get("kind") != "RECIPE":
        return False
    assertion = fact.get("original_assertion") or ""
    return bool(re.search(r"얼음.{0,12}(넣|투입|갈아|갈고|믹싱)", assertion)
                and not re.search(r"얼음.{0,12}(않|말|금지|제외|없)", assertion))


def apply_evaluation_policy(truth, overrides):
    """별도 승인 라벨을 적용하며 원래 입력 snapshot은 변경하지 않는다."""
    ids = {f["fact_id"] for f in truth}
    if set(overrides) - ids:
        raise ValueError("정답지 밖 정책 ID")
    allowed = {"expectation", "superseded_by", "recipe_uses_ice"}
    for update in overrides.values():
        if set(update) - allowed:
            raise ValueError("정책은 원본 대상·속성·값을 바꿀 수 없다")
        if update.get("expectation", "PRESENT") not in {"PRESENT", "ABSENT"}:
            raise ValueError("invalid fact expectation")
        if "recipe_uses_ice" in update and type(update["recipe_uses_ice"]) is not bool:
            raise ValueError("recipe_uses_ice must be boolean")
    return [{**f, **overrides.get(f["fact_id"], {})} for f in truth]

_ATTRIBUTE_ALIASES = {
    "우유량": ("우유량", "우유 용량", "스팀우유량"),
    "사용기한": ("사용기한", "사용 기한"),
    "발주주기": ("발주주기", "발주 주기"),
}


def _attribute_key(text):
    normalized = normalize(text or "")
    for key, aliases in _ATTRIBUTE_ALIASES.items():
        if normalized in [normalize(a) for a in aliases]:
            return key
    return normalized


def applicability(fact, has_variant_axis):
    scope = fact.get("applicability", "UNKNOWN" if has_variant_axis else "NOT_APPLICABLE")
    if scope not in {"SPECIFIC", "COMMON", "NOT_APPLICABLE", "UNKNOWN"}:
        raise ValueError("invalid fact applicability")
    return scope

_WORD = re.compile(r"[0-9A-Za-z가-힣]+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

# 조사·어미. 긴 것부터 떼어낸다.
# reg/retrieve.py 에 같은 성격의 목록이 따로 있다. 14.4 에서 하나로 합친다 —
# 지금 합치면 검색 동작이 함께 바뀌어 기준선과 비교가 끊긴다.
_TAIL = (
    "합니다", "입니다", "됩니다", "습니다", "해주세요", "하세요", "한다", "된다",
    "이다", "이며", "하며", "하고", "해서", "에서", "으로", "한테", "에게",
    "까지", "부터", "이랑", "보다", "처럼", "이라", "라고",
    "은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "로", "과", "와", "랑",
)
# 한 글자여도 근거가 되는 말이 있다 — 물·샷·컵·잔.
# 아래 글자들만 근거가 못 된다고 본다 (reg/retrieve.py 의 _STOP1 과 같은 취지)
_STOP1 = set("것거때곳수개몇왜뭐등안잘좀더또그이저첫한두세네위밑앞뒤옆말일분초년월를을은는가에의도만로와과")

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


def stem(word: str) -> str:
    """낱말 끝의 조사·어미를 뗀다. "스푼을" → "스푼", "처리합니다" → "처리"."""
    for tail in _TAIL:
        if word.endswith(tail) and len(word) - len(tail) >= 1:
            return word[: -len(tail)]
    return word


def _tokens(text: str) -> set[str]:
    """비교에 쓸 낱말. 한 글자라도 근거가 되면 살린다 (물·샷·컵)."""
    out: set[str] = set()
    for raw in normalize(text).split():
        if raw in _VALUE_STOP:
            continue
        for form in {raw, stem(raw)}:
            if not form or form in _VALUE_STOP:
                continue
            if len(form) == 1 and form in _STOP1:
                continue
            out.add(form)
    return out


def _near(a: str, b: str) -> bool:
    """한 음절만 다른 같은 말인가. "포터필터" ↔ "포타필터".

    현장 표기가 흔들리는 경우가 잦다. 길이가 같고 한 자리만 다를 때만 인정한다 —
    더 느슨하게 잡으면 다른 메뉴끼리 붙는다.
    """
    if len(a) != len(b) or len(a) < 4:
        return False
    return sum(1 for x, y in zip(a, b) if x != y) == 1


def _subject_in(subject: str, card_text: str) -> bool:
    """대상이 카드에 나오는가. 표기 흔들림을 한 음절까지 허용한다."""
    if not subject:
        return False
    want = normalize(subject)
    hay = normalize(card_text)
    if want in hay:
        return True
    return any(_near(want, w) or _near(want, stem(w)) for w in hay.split())


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


def variant_axis(truth_facts: list[dict[str, Any]]) -> dict[str, bool]:
    """대상마다 **규격이라는 축이 있는가**. {대상: True/False}

    D19 가 막으려는 위험은 "같은 메뉴의 다른 규격이 섞이는 것" 이다. 그 위험은
    규격이 둘 이상 있을 때만 존재한다. 아이스만 파는 음료라면 카드에 ICE 라고
    안 써도 헷갈릴 대상이 없다.

    그래서 정답지에 서로 다른 규격이 둘 이상 나오는 대상만 축이 있다고 본다.
    정답지가 이 측정의 기준이므로 그 안에 없는 규격은 이 측정에서 존재하지 않는다.

    자동 판정이지만 숨기지 않는다 — `scripts/audit_truth.py` 가 어느 대상을
    어떻게 분류했는지 내보내고, 정답지에 `variant_axis` 를 직접 적으면 그 값이 이긴다.
    """
    seen: dict[str, set[str]] = {}
    override: dict[str, bool] = {}
    for fact in truth_facts:
        subject = normalize(fact.get("subject") or "")
        if not subject:
            continue
        if "variant_axis" in fact:
            # 사람이 직접 적은 값은 추론을 이긴다
            if type(fact["variant_axis"]) is not bool:
                raise ValueError("variant_axis must be an explicit boolean")
            override[subject] = fact["variant_axis"]
        variant = fact.get("variant")
        seen.setdefault(subject, set())
        if variant:
            seen[subject].add(variant.upper())
    return {subject: override.get(subject, len(variants) > 1)
            for subject, variants in seen.items()}


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


def _score_one(fact: dict[str, Any], card_text: str,
               require_variant: bool = True) -> FactMatch:
    subject = fact.get("subject") or ""
    value = fact.get("value") or ""
    variant = fact.get("variant")

    subject_hit = _subject_in(subject, card_text)
    # 규격 축이 없는 대상은 규격을 안 적어도 헷갈릴 것이 없다.
    # 축이 없는데 감점하면 자가 틀린 것이지 카드가 틀린 것이 아니다
    variant_hit = variant_present(variant, card_text) if require_variant else True
    if requires_ice_label(fact):
        variant_hit = bool(re.search(r"(?<![A-Za-z])ICE(?![A-Za-z])", card_text, re.I))
    if variant and fact.get("applicability") != "COMMON":
        opposite = "ICE" if variant.upper() == "HOT" else "HOT" if variant.upper() == "ICE" else None
        if opposite and variant_present(opposite, card_text) and not variant_present(variant, card_text):
            return FactMatch("PARTIAL", None, 0.0, "명시적인 반대 규격", subject_hit, False, False)

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
        # 같은 카드에 있다는 이유로 관계·단위·부정을 확정하지 않는다.
        uncertainty = None
        attribute = fact.get("attribute") or ""
        # 자유 문장에서는 속성의 생략/별칭을 확정할 수 없으면 보류한다.
        if attribute and not _has_attribute(fact, card_text):
            return FactMatch("PARTIAL", None, ratio, "대상·값은 있으나 속성 관계 미확인", True, False, variant_hit, ratio)
        if re.search(r"잘못|틀린|아니라|대신|넣지|않|금지|제외|not\b|never\b", card_text, re.I):
            uncertainty = "부정·정정·예외 문맥은 사람 확인 필요"
        quantities = re.findall(r"(\d+(?:\.\d+)?)\s*(ml|㎖|g|kg|일|분|초|days?|minutes?)", value, re.I)
        for number, unit in quantities:
            if not re.search(rf"(?<!\d){re.escape(number)}\s*{re.escape(unit)}(?![A-Za-z])", card_text, re.I):
                uncertainty = "숫자는 있으나 값·단위 결합이 다름"
            others = re.findall(rf"(\d+(?:\.\d+)?)\s*{re.escape(unit)}", card_text, re.I)
            if any(n not in numbers_in(value) for n in others):
                uncertainty = "같은 단위의 다른 값 혼재"
        if variant and sum(variant_present(v, card_text) for v in ("HOT", "ICE")) > 1:
            uncertainty = "복수 규격의 값 결합은 사람 확인 필요"
        if fact.get("applicability") == "UNKNOWN":
            uncertainty = "사실 적용 범위 미확인"
        if any(normalize(c) not in normalize(card_text) for c in fact.get("conditions", [])):
            uncertainty = "필수 조건 미확인"
        if not want_numbers and not _tokens(value).issubset(_tokens(card_text)):
            uncertainty = "일부 값 토큰만 일치: 전체 의미 확인 필요"
        if uncertainty:
            return FactMatch("UNDETERMINED", None, ratio, uncertainty,
                             True, True, True, ratio)
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


_RANK = {"COVERED": 3, "UNDETERMINED": 2, "PARTIAL": 1, "MISSING": 0}


def match_fact(fact: dict[str, Any], cards: list[dict[str, Any]],
               require_variant: bool = True) -> FactMatch:
    """사실 하나를 카드 전체와 대조해 가장 좋은 판정을 돌려준다.

    카드를 가로질러 합치지 않는다. **한 카드 안에** 대상과 값이 같이 있어야 한다.
    여러 카드를 이어붙여 인정하면, 신입이 카드 하나만 읽고는 답을 못 얻는데도
    담았다고 세게 된다.
    """
    scope = fact.get("applicability")
    if scope in {"COMMON", "NOT_APPLICABLE"}:
        require_variant = False
    if scope == "SPECIFIC":
        require_variant = True
        if not fact.get("variant"):
            return FactMatch("UNDETERMINED", None, 0.0, "SPECIFIC 규격 누락")
    best = FactMatch("MISSING", None, 0.0, "대조할 카드가 없음")
    best_attribute = False
    for card in cards:
        text = _card_context(fact, card)
        subject = fact.get("subject") or ""
        subject_matches = _subject_in(subject, text)
        if subject == "영업" and fact.get("attribute") == "종료시각" and _has_attribute(fact, text):
            subject_matches = _subject_in("매장", text)
            if subject_matches:
                text = "영업 " + text
        if not subject_matches:
            full_text = f"{card.get('title') or ''} {card.get('content') or ''}"
            if _subject_in(subject, full_text) and _has_attribute(fact, text):
                candidate = FactMatch("UNDETERMINED", int(card["card_id"]), 0.0,
                                      "대상과 속성이 서로 다른 문장: 관계 미확인", True, False, False)
                if _RANK[candidate.verdict] > _RANK[best.verdict]:
                    best = candidate
                    best_attribute = True
            continue
        m = _score_one(fact, text, require_variant)
        full_text = f"{card.get('title') or ''} {card.get('content') or ''}"
        if m.verdict == "COVERED" and re.search(r"잘못|틀린|아니라|대신|넣지|않|금지|제외|not\b|never\b", full_text, re.I):
            m = FactMatch("UNDETERMINED", None, m.score, "다른 문장의 부정·정정·예외 확인 필요",
                          m.subject_hit, m.value_hit, m.variant_hit, m.number_ratio)
        # 같은 판정 안에서는 값이 든 카드를 먼저 집는다.
        # 대상 이름만 겹치는 카드가 값을 담은 카드를 밀어내면 진단이 뒤집힌다
        attribute_hit = _has_attribute(fact, text)
        if (_RANK[m.verdict], attribute_hit, m.value_hit, m.score) > (
            _RANK[best.verdict], best_attribute, best.value_hit, best.score
        ):
            best_attribute = attribute_hit
            best = FactMatch(
                m.verdict, int(card["card_id"]), m.score, m.reason,
                m.subject_hit, m.value_hit, m.variant_hit, m.number_ratio,
            )
    return best


def score_expected_fact(fact, cards, truth, require_variant=True):
    """명시적 ABSENT 라벨만 최종 카드 제외 검사로 처리한다. 원장 이력은 삭제하지 않는다."""
    if fact.get("expectation", "PRESENT") == "PRESENT":
        return match_fact(fact, cards, require_variant)
    if fact.get("expectation") != "ABSENT":
        raise ValueError("invalid fact expectation")
    successors = [f for f in truth if f.get("fact_id") == fact.get("superseded_by")]
    if len(successors) != 1 or successors[0].get("expectation", "PRESENT") != "PRESENT":
        return FactMatch("UNDETERMINED", None, 0.0, "최신 정정 사실 연결 미확인")
    successor = successors[0]
    if normalize(successor.get("subject")) != normalize(fact.get("subject")):
        return FactMatch("UNDETERMINED", None, 0.0, "정정 대상 불일치")
    old = {**fact, "attribute": (fact.get("attribute") or "").replace("(이전)", "")}
    if _attribute_key(old["attribute"]) != _attribute_key(successor.get("attribute")):
        return FactMatch("UNDETERMINED", None, 0.0, "정정 속성 불일치")
    old_match = match_fact(old, cards, require_variant=False)
    if old_match.verdict in {"COVERED", "UNDETERMINED"}:
        return FactMatch("PARTIAL" if old_match.verdict == "COVERED" else "UNDETERMINED",
                         old_match.card_id, 0.0, "이전 지시의 잔존 또는 정정 문맥 확인 필요")
    latest = match_fact(successor, cards, require_variant=False)
    if latest.verdict != "COVERED":
        return FactMatch(latest.verdict, latest.card_id, latest.score, "최신 정정 지시 미확인")
    return FactMatch("COVERED", latest.card_id, 1.0, "이전 지시 제외·최신 지시 확인")


def match_fact_in_ledger(
    fact: dict[str, Any], ledger: list[dict[str, Any]]
) -> tuple[bool, int | None]:
    """정답지 사실이 원장(source_facts)에 뽑혀 있는가.

    카드 본문 대조와 달리 **구조끼리** 맞춘다 — 대상과 값이 각각 필드로 있으므로
    속성은 명시된 별칭만 허용하며 값은 단위까지 확인한다.

    규격(variant)은 정답지에 있을 때만 본다. 현재 추출은 규격을 채우지 않으므로
    (13.5 가 RECIPE 스키마로 채운다) 여기서 요구하면 전부 탈락한다.
    """
    subject = fact.get("subject") or ""
    value = fact.get("value") or ""
    if not subject or not value:
        return False, None

    for row in ledger:
        if not _subject_in(subject, row.get("subject") or ""):
            continue
        if fact.get("attribute") and not _same_attribute(fact["attribute"], row.get("attribute")):
            continue
        have = row.get("value") or ""
        if _value_key(value) == _value_key(have):
            return True, row.get("fact_id")
    return False, None


def loss_stage(in_ledger: bool, verdict: Verdict) -> str:
    """손실이 어느 단계에서 났는가.

    이 구분이 13.4 의 2패스가 어디를 고쳐야 하는지 정한다.
    """
    in_card = verdict == "COVERED"
    if in_ledger and in_card:
        return "OK"
    if in_ledger and not in_card:
        return "ASSEMBLY"      # 뽑았는데 카드에 안 실렸다 — 조립이 문제
    if not in_ledger and in_card:
        return "CARD_ONLY"     # 카드 본문에 녹아 있으나 사실로는 안 뽑혔다
    return "EXTRACTION"        # 애초에 못 뽑았다 — map 이 문제


@dataclass
class ExtractionReport:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self, fact: dict[str, Any], match: FactMatch, source_type: str,
        *, in_ledger: bool = False, ledger_fact_id: int | None = None,
    ) -> None:
        self.rows.append({
            "in_ledger": in_ledger,
            "ledger_fact_id": ledger_fact_id,
            "loss_stage": loss_stage(in_ledger, match.verdict),
            "fact_id": fact.get("fact_id"),
            "expectation": fact.get("expectation", "PRESENT"),
            "superseded_by": fact.get("superseded_by"),
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
    exclusions = [r for r in rows if r.get("expectation") == "ABSENT"]
    rows = [r for r in rows if r.get("expectation", "PRESENT") == "PRESENT"]
    total = len(rows)
    if total == 0:
        return {"fact_count": 0, "card_count": card_count,
                "expected_exclusions": len(exclusions),
                "expected_exclusions_failed_ids": [r["fact_id"] for r in exclusions if r["verdict"] != "COVERED"]}

    def bucket(subset: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(subset)
        if n == 0:
            return {"fact_count": 0}
        covered = sum(1 for r in subset if r["verdict"] == "COVERED")
        partial = sum(1 for r in subset if r["verdict"] == "PARTIAL")
        undetermined = sum(1 for r in subset if r["verdict"] == "UNDETERMINED")
        return {
            "fact_count": n,
            "covered": covered,
            "partial": partial,
            "missing": n - covered - partial - undetermined,
            "undetermined": undetermined,
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
        "expected_exclusions": len(exclusions),
        "expected_exclusions_failed_ids": [r["fact_id"] for r in exclusions if r["verdict"] != "COVERED"],
        "card_count": card_count,
        # 치명 누락 — must_have 사실을 놓친 것. 여기가 0 이 아니면 서비스가 성립하지 않는다
        "must_have": bucket(must),
        "must_have_missing_ids": [
            r["fact_id"] for r in must if r["verdict"] != "COVERED"
        ],
        "by_source_type": {k: bucket(v) for k, v in sorted(by_type.items())},
        # 값이 틀어진 것과 아예 없는 것을 가른다. 원인이 다르다
        "partial_reasons": _count(r["reason"] for r in rows if r["verdict"] == "PARTIAL"),
        # 손실이 어느 단계에서 났는가. 2패스가 고칠 자리를 정한다
        "loss_stage": _count(r.get("loss_stage") or "UNKNOWN" for r in rows),
        "loss_stage_by_source_type": {
            stype: _count(r.get("loss_stage") or "UNKNOWN" for r in group)
            for stype, group in sorted(by_type.items())
        },
        "ledger_recall": round(
            sum(1 for r in rows if r.get("in_ledger")) / total, 4
        ),
    }


def _count(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ── 출력 쪽 채점 (W0) ─────────────────────────────────────────────────────
# 지금까지는 정답지만 순회했다. 그러면 **재현율만 보인다** — 쓰레기 사실을
# 500건 뱉어도 점수가 같다. 뽑아낸 주장 쪽에서도 한 번 세야 한다.
#
# 다만 "정답지에 없다 = 틀렸다" 가 아니다. 정답지는 전수가 아니다. 사람이
# 라벨링한 278건 밖에도 자료에는 사실이 더 있다. 그래서 셋으로 가른다:
#   MATCHED    정답지의 어떤 사실과 맞는다
#   CONFLICT   대상·속성은 같은데 값이나 규격이 다르다 — **누락보다 위험하다**
#   UNVERIFIED 정답지에 없다. 틀렸는지 정답지가 모자란지는 사람이 봐야 한다
#
# UNVERIFIED 를 오답으로 세면 precision 이 실제보다 낮게 나오고, 정답으로 세면
# 지어낸 사실이 점수를 올린다. 둘 다 하지 않고 그대로 남겨 표본 판정으로 넘긴다.

OutputVerdict = str


def _same_variant(a: str | None, b: str | None) -> bool:
    """규격이 같은가. 한쪽이 비면 '미확정' 이지 '아무거나' 가 아니다 (MVP 31-2)."""
    if not a or not b:
        return not a and not b
    return normalize(a) == normalize(b)


def _same_attribute(a: str | None, b: str | None) -> bool:
    """같은 것을 묻고 있는가.

    이름은 갈린다 — 정답지가 "스팀우유량" 인데 모델은 "우유 용량" 이라 쓴다.
    그래서 확인한 별칭만 같은 속성으로 본다. 공통 낱말만으로 확정하지 않는다.

    **이 판단이 오연결 검출의 전제다.** 속성을 보지 않으면 "원두 발주요일" 과
    "원두 사용기한" 처럼 둘 다 참인 별개 사실이 서로 모순이라고 잡힌다.
    """
    if not a or not b:
        return False
    return _attribute_key(a) == _attribute_key(b)


def _value_key(value):
    # 소수점·부등호·부정 문구를 지우지 않는다. 숫자-단위 사이 공백만 허용한다.
    value = " ".join((value or "").lower().split())
    return re.sub(r"(?<=\d)\s+(?=ml\b|g\b|kg\b|일|분|초|days?\b|minutes?\b)", "", value)


def classify_claim(
    claim: dict[str, Any], truth_facts: list[dict[str, Any]]
) -> tuple[OutputVerdict, str | None, str]:
    """뽑아낸 주장 하나를 정답지와 대조한다. (판정, 맞은 fact_id, 사유).

    오연결(CONFLICT)은 **대상과 속성이 같은데 값이나 규격이 다를 때만** 이다.
    같은 대상의 다른 속성은 모순이 아니라 추가 정보다.
    """
    subject = normalize(claim.get("subject") or "")
    value = _value_key(claim.get("value") or "")
    if not subject:
        return "UNVERIFIED", None, "대상이 비어 있어 대조할 수 없다"

    conflict: tuple[str, str] | None = None
    same_attribute_seen = False
    for fact in truth_facts:
        t_subject = normalize(fact.get("subject") or "")
        if not (t_subject == subject or _near(t_subject, subject)):
            continue
        if not _same_attribute(claim.get("attribute"), fact.get("attribute")):
            continue
        same_attribute_seen = True
        # 공통 단어(days, 약)는 값 일치의 증거가 아니다. 숫자·단위·전체 값을 확인한다.
        value_hit = bool(value) and value == _value_key(fact.get("value") or "")
        variant_hit = _same_variant(claim.get("variant"), fact.get("variant"))
        if value_hit and variant_hit:
            if claim.get("polarity", "AFFIRM") != fact.get("polarity", "AFFIRM"):
                return "CONFLICT", fact["fact_id"], "부정 극성이 다르다"
            if any(claim.get(k, []) != fact.get(k, []) for k in ("conditions", "exceptions", "requires")):
                return "UNVERIFIED", None, "조건·예외·선행 관계 확인 필요"
            return "MATCHED", fact["fact_id"], "대상·속성·값·규격이 맞는다"
        if variant_hit and not (numbers_in(value) or numbers_in(fact.get("value") or "")):
            continue  # 다른 자유 문장은 자동으로 참/거짓 관계를 확정하지 않는다
        if conflict is None:
            conflict = (
                fact["fact_id"],
                "같은 대상·속성인데 규격이 다르다" if value_hit
                else "같은 대상·속성인데 값이 다르다",
            )
    if conflict:
        # 같은 것을 묻는데 다른 값을 실어 보내는 것이 누락보다 위험하다.
        # 신입은 그걸 읽고 그대로 따른다
        return "CONFLICT", conflict[0], conflict[1]
    if same_attribute_seen:
        return "UNVERIFIED", None, "같은 속성의 자유 문장 의미를 자동 확정할 수 없다"
    return "UNVERIFIED", None, "정답지에 같은 대상·속성이 없다"


def score_output(
    claims: list[dict[str, Any]], truth_facts: list[dict[str, Any]]
) -> dict[str, Any]:
    """출력 쪽 지표. precision 을 **단정하지 않고** 범위로 낸다.

    정답지가 전수가 아니므로 참값은 두 수 사이에 있다:
      하한 = MATCHED / 전체        (UNVERIFIED 를 전부 오답으로 볼 때)
      상한 = (MATCHED + UNVERIFIED) / 전체  (전부 정답으로 볼 때)
    표본 판정으로 좁히기 전까지 이 폭을 그대로 보고한다.
    """
    rows = []
    for claim in claims:
        verdict, fact_id, reason = classify_claim(claim, truth_facts)
        rows.append({
            "claim_id": claim.get("fact_id"),
            "subject": claim.get("subject"),
            "variant": claim.get("variant"),
            "attribute": claim.get("attribute"),
            "value": claim.get("value"),
            "verdict": verdict,
            "truth_fact_id": fact_id,
            "reason": reason,
        })

    total = len(rows)
    counts = {v: sum(1 for r in rows if r["verdict"] == v)
              for v in ("MATCHED", "CONFLICT", "UNVERIFIED")}
    if total == 0:
        return {"claim_count": 0, **counts, "rows": rows}
    return {
        "claim_count": total,
        **counts,
        "precision_lower": round(counts["MATCHED"] / total, 4),
        "precision_upper": round(
            (counts["MATCHED"] + counts["UNVERIFIED"]) / total, 4),
        # 판정이 갈리는 폭. 넓으면 표본 판정이 더 필요하다는 뜻이다
        "undetermined_rate": round(counts["UNVERIFIED"] / total, 4),
        # 오연결 — 같은 대상에 다른 값. 누락보다 위험하다
        "conflict_rate": round(counts["CONFLICT"] / total, 4),
        "conflict_ids": [r["claim_id"] for r in rows if r["verdict"] == "CONFLICT"],
        "rows": rows,
    }


# ── 실행 건강도 (W0) ──────────────────────────────────────────────────────
# 아무것도 못 뽑은 실행이 SUCCEEDED 로 기록되면, 그 빈 실행 둘을 비교해
# "차이 없음" 이라는 답이 나온다. 실제로 겪었다 — 자료 5건이 전부 실패했는데
# 손실 100% 가 측정값으로 남았다.
#
# 측정이 아닌 것을 측정으로 기록하지 않는다. 순수 함수로 빼서 검사한다.

RUN_OK = "SUCCEEDED"
RUN_PARTIAL = "PARTIAL"
RUN_DEAD = "DEAD"


def judge_run_health(
    source_states: dict[str, int], card_count: int
) -> tuple[str, str | None]:
    """실행을 어떤 상태로 닫을지. (상태, 멈출 이유).

    이유가 돌아오면 **기록하지 않고 멈춘다.** 파이프라인이 돌지 않은 것을
    "손실 100%" 라는 성능 수치로 남기면 다음 사람이 그걸 기준선으로 쓴다.
    """
    total = sum(source_states.values())
    failed = source_states.get("FAILED", 0)

    if total and failed == total:
        return RUN_DEAD, (
            f"자료 {total}건이 모두 처리에 실패했다. 이건 측정이 아니다")
    if card_count == 0:
        return RUN_DEAD, (
            "카드가 한 장도 만들어지지 않았다. 손실 100% 는 측정 결과가 아니라 "
            "파이프라인이 돌지 않았다는 뜻이다")
    if failed:
        # 일부만 실패하면 분모가 달라진 측정이다. 성공과 같은 칸에 두지 않는다
        return RUN_PARTIAL, None
    return RUN_OK, None


# ── 반복 판정 (W0) ────────────────────────────────────────────────────────
# 같은 설정을 여러 번 돌리면 사실마다 판정이 여러 개 나온다. 그걸 하나로 줄일 때
# **다수결을 쓰면 잡음이 신호가 된다.** 3회에서 2:1 과 1:2 가 맞붙으면 아무것도
# 바꾸지 않았는데 '개선 1건' 이 기록된다. 실측에서 그렇게 10건이 뒤집혔고,
# 만장일치로 세니 0건이었다.
#
# 그래서 만장일치를 기준으로 쓰되, **갈린 것을 버리지 않고 세어 보고한다.**
# 엄격한 기준은 진짜 작은 악화도 함께 가리기 때문이다.

VERDICT_RANK = {"MISSING": 0, "UNDETERMINED": 0, "PARTIAL": 1, "COVERED": 2}


def decide_majority(verdicts: list[str]) -> tuple[str, bool]:
    """다수결 판정과 안정 여부. 참고용이며 승격 판정에 쓰지 않는다."""
    if not verdicts:
        return "MISSING", False
    top, n = Counter(verdicts).most_common(1)[0]
    return top, n * 2 > len(verdicts)


def decide_unanimous(verdicts: list[str]) -> tuple[str, bool]:
    """만장일치일 때만 안정으로 본다. 하나라도 갈리면 '흔들림' 이다.

    판정이 아예 없는 경우도 안정이 아니다 — 판정하지 않은 것을 '일치' 로
    세면 실행이 빠진 사실이 조용히 '동일' 에 들어간다.
    """
    if not verdicts:
        return "MISSING", False
    top, n = Counter(verdicts).most_common(1)[0]
    return top, n == len(verdicts)
