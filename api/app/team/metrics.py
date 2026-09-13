"""평가 채점과 집계. 순수 함수만 둔다 — DB·LLM 을 부르지 않는다.

채점 규칙을 여기에 모아두는 이유는 두 가지다.
  1. 임계값·프롬프트를 바꿔도 '무엇을 정답으로 봤는가' 는 그대로여야 비교가 된다.
  2. 테스트가 DB 없이 이 규칙만 검증할 수 있어야 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from math import log2
from typing import Any, Iterable, Literal

ExpectedKind = Literal["HIT", "MISS", "REFUSE", "SAFE_ROUTE"]
ActualKind = Literal["HIT", "MISS", "ERROR"]

# 답하면 안 되는 문항. 검색이 miss 로 떨어져 점주에게 넘어가는 것이 정답이다
_MUST_NOT_ANSWER: frozenset[str] = frozenset({"MISS", "REFUSE", "SAFE_ROUTE"})

_WORD = re.compile(r"[0-9A-Za-z가-힣]+")


@dataclass(frozen=True)
class CaseOutcome:
    """한 문항을 실제로 실행한 결과. 채점 전의 날것."""

    actual_kind: ActualKind
    miss_reason: str | None = None
    retrieved_card_ids: list[int] = field(default_factory=list)
    citation_card_ids: list[int] = field(default_factory=list)
    answer_text: str | None = None
    answer_source: str | None = None
    grounding_status: str | None = None
    retrieve_latency_ms: int | None = None
    answer_latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class CaseScore:
    kind_correct: bool
    passed: bool
    failure_kind: str | None
    expected_hit_rank: int | None
    reciprocal_rank: float | None
    ndcg: float | None
    top_card_id: int | None
    wrong_card: bool
    citation_count: int
    citation_precision: float | None
    fact_coverage: float | None
    ungrounded: bool
    total_latency_ms: int | None


def _normalize(text: str) -> str:
    """표기 흔들림만 지운다. 낱말을 자르지는 않는다."""
    return " ".join(_WORD.findall(text.lower()))


def fact_coverage(expected_facts: Iterable[str], answer_text: str | None) -> float | None:
    """기대한 핵심 사실이 답변에 실제로 들어있는 비율. 기대가 없으면 채점하지 않는다."""
    facts = [f for f in (fact.strip() for fact in expected_facts) if f]
    if not facts:
        return None
    if not answer_text:
        return 0.0
    haystack = _normalize(answer_text)
    hit = sum(1 for fact in facts if _normalize(fact) in haystack)
    return round(hit / len(facts), 4)


def expected_rank(expected_card_ids: Iterable[int], retrieved_card_ids: list[int]) -> int | None:
    """기대 카드가 검색 후보에서 몇 번째로 처음 나오는가. 없으면 None."""
    expected = {int(cid) for cid in expected_card_ids}
    if not expected:
        return None
    for index, card_id in enumerate(retrieved_card_ids, start=1):
        if int(card_id) in expected:
            return index
    return None


# 순위 품질은 "1위인가" 만으로 보면 저하가 안 잡힌다. 기대 카드가 1위에서 3위로
# 밀려도 통과율은 그대로다. nDCG 와 MRR 이 그 구멍을 메운다.
# 검색 깊이(top_k)보다 큰 k 를 줘도 의미가 없으므로 실제 사용한 k 를 함께 기록한다.
NDCG_K = 10


def reciprocal_rank(expected_card_ids: Iterable[int], retrieved_card_ids: list[int]) -> float | None:
    """기대 카드가 처음 나온 순위의 역수. 후보에 없으면 0.0 이다 (채점 제외가 아니다)."""
    expected = {int(cid) for cid in expected_card_ids}
    if not expected:
        return None
    rank = expected_rank(expected, retrieved_card_ids)
    return round(1 / rank, 4) if rank else 0.0


def ndcg(
    expected_card_ids: Iterable[int],
    retrieved_card_ids: list[int],
    k: int = NDCG_K,
) -> float | None:
    """이진 관련도 nDCG@k.

    기대 카드가 여러 장일 때 '몇 위에 있나' 하나로는 표현이 안 된다.
    상위에 몰려 있을수록 높다. 기대가 없으면 채점하지 않는다.
    """
    expected = {int(cid) for cid in expected_card_ids}
    if not expected:
        return None
    gains = [
        1 / log2(position + 1)
        for position, card_id in enumerate(retrieved_card_ids[:k], start=1)
        if int(card_id) in expected
    ]
    # 이상적인 순서: 기대 카드가 1위부터 연속으로 놓인 경우
    ideal_count = min(len(expected), k)
    ideal = sum(1 / log2(position + 1) for position in range(1, ideal_count + 1))
    if ideal == 0:
        return None
    return round(sum(gains) / ideal, 4)


def citation_precision(
    expected_card_ids: Iterable[int],
    citation_card_ids: list[int],
) -> float | None:
    """인용한 카드 중 기대 카드의 비율. 인용이나 기대가 없으면 채점하지 않는다."""
    expected = {int(cid) for cid in expected_card_ids}
    if not expected or not citation_card_ids:
        return None
    hit = sum(1 for cid in citation_card_ids if int(cid) in expected)
    return round(hit / len(citation_card_ids), 4)


def score_case(
    *,
    expected_kind: ExpectedKind,
    expected_card_ids: Iterable[int],
    expected_facts: Iterable[str],
    expected_miss_reason: str | None,
    outcome: CaseOutcome,
) -> CaseScore:
    """한 문항의 합격 여부와 실패 사유를 결정한다.

    순위가 1위가 아닌 것은 실패로 세지 않는다. 대신 평균 순위 지표로 본다.
    근거 없는 답변(HIT 인데 citation 0)은 언제나 실패다 (불변식 3).
    """
    expected_ids = [int(cid) for cid in expected_card_ids]
    retrieved = [int(cid) for cid in outcome.retrieved_card_ids]
    citations = [int(cid) for cid in outcome.citation_card_ids]

    rank = expected_rank(expected_ids, retrieved)
    # 순위 품질은 HIT 를 기대한 문항에서만 뜻이 있다. miss 기대 문항은 채점하지 않는다
    rr = reciprocal_rank(expected_ids, retrieved) if expected_kind == "HIT" else None
    gain = ndcg(expected_ids, retrieved) if expected_kind == "HIT" else None
    top_card_id = retrieved[0] if retrieved else None
    wrong_card = bool(
        expected_ids and top_card_id is not None and top_card_id not in set(expected_ids)
    )
    precision = citation_precision(expected_ids, citations)
    coverage = fact_coverage(expected_facts, outcome.answer_text)
    ungrounded = outcome.actual_kind == "HIT" and not citations

    total_latency = None
    parts = [p for p in (outcome.retrieve_latency_ms, outcome.answer_latency_ms) if p is not None]
    if parts:
        total_latency = sum(parts)

    if expected_kind == "HIT":
        kind_correct = outcome.actual_kind == "HIT"
    else:
        kind_correct = outcome.actual_kind == "MISS"

    failure_kind = _failure_kind(
        expected_kind=expected_kind,
        expected_miss_reason=expected_miss_reason,
        outcome=outcome,
        rank=rank,
        citations=citations,
        precision=precision,
        coverage=coverage,
    )

    return CaseScore(
        kind_correct=kind_correct,
        passed=failure_kind is None,
        failure_kind=failure_kind,
        expected_hit_rank=rank,
        reciprocal_rank=rr,
        ndcg=gain,
        top_card_id=top_card_id,
        wrong_card=wrong_card,
        citation_count=len(citations),
        citation_precision=precision,
        fact_coverage=coverage,
        ungrounded=ungrounded,
        total_latency_ms=total_latency,
    )


def _failure_kind(
    *,
    expected_kind: ExpectedKind,
    expected_miss_reason: str | None,
    outcome: CaseOutcome,
    rank: int | None,
    citations: list[int],
    precision: float | None,
    coverage: float | None,
) -> str | None:
    if outcome.actual_kind == "ERROR":
        return "RUN_ERROR"

    if expected_kind in _MUST_NOT_ANSWER:
        if outcome.actual_kind == "HIT":
            return "SHOULD_NOT_ANSWER"
        if (
            expected_kind == "MISS"
            and expected_miss_reason
            and outcome.miss_reason != expected_miss_reason
        ):
            return "MISS_REASON_MISMATCH"
        return None

    # expected_kind == "HIT"
    if outcome.actual_kind == "MISS":
        return "FALSE_MISS"
    if not citations:
        return "NO_CITATION"
    if rank is None:
        return "EXPECTED_CARD_ABSENT"
    if precision == 0:
        return "WRONG_CITATION"
    if coverage is not None and coverage < 1:
        return "MISSING_FACT"
    return None


def percentile(values: list[int | float], ratio: float) -> float | None:
    """최근접 순위 방식. 표본이 적은 평가에서 보간은 의미가 없다."""
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    index = max(0, min(len(clean) - 1, round(ratio * len(clean) + 0.5) - 1))
    return round(float(clean[index]), 2)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """실행 단위 지표. DEV_TODO 13.1 측정 지표 목록과 1:1 로 맞춘다."""
    total = len(rows)
    if total == 0:
        return {"case_count": 0}

    def _rate(count: int, denom: int) -> float | None:
        return round(count / denom, 4) if denom else None

    hit_cases = [r for r in rows if r["expected_kind"] == "HIT"]
    answerable_actual_hit = [r for r in rows if r["actual_kind"] == "HIT"]
    ranks = [r["expected_hit_rank"] for r in hit_cases if r["expected_hit_rank"] is not None]
    # MRR·nDCG 는 후보에 못 든 문항을 0 으로 포함해야 한다. 빼면 점수가 부풀려진다
    rr_values = [
        float(r["reciprocal_rank"]) for r in hit_cases if r.get("reciprocal_rank") is not None
    ]
    ndcg_values = [float(r["ndcg"]) for r in hit_cases if r.get("ndcg") is not None]
    precisions = [
        float(r["citation_precision"])
        for r in rows
        if r.get("citation_precision") is not None
    ]
    coverages = [
        float(r["fact_coverage"]) for r in rows if r.get("fact_coverage") is not None
    ]

    miss_reasons: dict[str, int] = {}
    for row in rows:
        if row["actual_kind"] == "MISS":
            miss_reasons[row.get("miss_reason") or "unknown"] = (
                miss_reasons.get(row.get("miss_reason") or "unknown", 0) + 1
            )

    failures: dict[str, int] = {}
    for row in rows:
        if row.get("failure_kind"):
            failures[row["failure_kind"]] = failures.get(row["failure_kind"], 0) + 1

    latencies = [r["total_latency_ms"] for r in rows if r.get("total_latency_ms") is not None]
    hit_latencies = [
        r["total_latency_ms"]
        for r in answerable_actual_hit
        if r.get("total_latency_ms") is not None
    ]
    miss_latencies = [
        r["total_latency_ms"]
        for r in rows
        if r["actual_kind"] == "MISS" and r.get("total_latency_ms") is not None
    ]

    prompt_tokens = sum(r.get("prompt_tokens") or 0 for r in rows)
    completion_tokens = sum(r.get("completion_tokens") or 0 for r in rows)
    cost_values = [float(r["cost_usd"]) for r in rows if r.get("cost_usd") is not None]
    cost_total = round(sum(cost_values), 6) if cost_values else None

    return {
        "case_count": total,
        "passed_count": sum(1 for r in rows if r["passed"]),
        "pass_rate": _rate(sum(1 for r in rows if r["passed"]), total),
        # hit/miss 판정 정확도
        "kind_accuracy": _rate(sum(1 for r in rows if r["kind_correct"]), total),
        # 기대 카드 hit율과 순위
        "expected_card_hit_rate": _rate(len(ranks), len(hit_cases)),
        "expected_card_top1_rate": _rate(sum(1 for r in ranks if r == 1), len(hit_cases)),
        "expected_card_mean_rank": (
            round(sum(ranks) / len(ranks), 3) if ranks else None
        ),
        # 순위 품질 — 1위율만 보면 잡히지 않는 저하를 잡는다
        "mrr": round(sum(rr_values) / len(rr_values), 4) if rr_values else None,
        f"ndcg_at_{NDCG_K}": (
            round(sum(ndcg_values) / len(ndcg_values), 4) if ndcg_values else None
        ),
        "ndcg_k": NDCG_K,
        # 잘못된 카드 선택률
        "wrong_card_rate": _rate(
            sum(1 for r in hit_cases if r.get("wrong_card")), len(hit_cases)
        ),
        # 근거 없는 답변률 — 목표 0
        "ungrounded_count": sum(1 for r in rows if r.get("ungrounded")),
        "ungrounded_rate": _rate(sum(1 for r in rows if r.get("ungrounded")), total),
        "should_not_answer_count": failures.get("SHOULD_NOT_ANSWER", 0),
        # citation 정확도
        "citation_precision_mean": (
            round(sum(precisions) / len(precisions), 4) if precisions else None
        ),
        "fact_coverage_mean": (
            round(sum(coverages) / len(coverages), 4) if coverages else None
        ),
        "miss_reason_distribution": miss_reasons,
        "failure_distribution": failures,
        # p50/p95 지연
        "latency_p50_ms": percentile(latencies, 0.5),
        "latency_p95_ms": percentile(latencies, 0.95),
        "hit_latency_p50_ms": percentile(hit_latencies, 0.5),
        "hit_latency_p95_ms": percentile(hit_latencies, 0.95),
        "miss_latency_p50_ms": percentile(miss_latencies, 0.5),
        "miss_latency_p95_ms": percentile(miss_latencies, 0.95),
        # 입력·질문당 모델 비용
        "prompt_tokens_total": prompt_tokens,
        "completion_tokens_total": completion_tokens,
        "cost_usd_total": cost_total,
        "cost_usd_per_question": (
            round(cost_total / total, 6) if cost_total is not None else None
        ),
        "error_count": sum(1 for r in rows if r["actual_kind"] == "ERROR"),
    }
