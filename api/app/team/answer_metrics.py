"""실험설계 §6/§9의 v2 질문/후보 분모. legacy HIT/MISS 평가와 분리한다."""
from statistics import median
from math import ceil

ACTIONS = {"ANSWER", "CLARIFY", "ESCALATE", "REFUSE", "SAFE_ROUTE", "ERROR"}


def _ratio(n, d):
    return n / d if d else None


def question_metrics(rows):
    rows = list(rows)
    if len({r["question_id"] for r in rows}) != len(rows):
        raise ValueError("질문 분모 중복")
    if any(r["actual_action"] not in ACTIONS or r["expected_action"] not in ACTIONS-{"ERROR"} for r in rows):
        raise ValueError("지원하지 않는 action")
    answerable = [r for r in rows if r["expected_action"] == "ANSWER"]
    potential_blocks = [r for r in rows if r["actual_action"] in {"CLARIFY", "ESCALATE"}]
    # action만으로 지식/근거 부족과 업무상 사람 연결을 구별할 수 없다.
    # knowledge_block은 평가자가 제공하는 이유 분류이며 누락을 False로 간주하지 않는다.
    unclassified = sum(type(r.get("knowledge_block")) is not bool for r in potential_blocks)
    blocks = [r for r in potential_blocks if r.get("knowledge_block") is True]
    judged = not unclassified and all(type(r.get("block_correct")) is bool for r in blocks)
    return dict(schema_version="r_question_metrics/v2", question_count=len(rows),
        action_accuracy=_ratio(sum(r["actual_action"] == r["expected_action"] for r in rows),len(rows)),
        answerable_count=len(answerable),
        false_abstention_rate=_ratio(sum(r["actual_action"] != "ANSWER" for r in answerable),len(answerable)),
        block_count=len(blocks), block_precision=_ratio(sum(r.get("block_correct") is True for r in blocks),len(blocks)) if judged else None,
        unjudged_block_count=sum(type(r.get("block_correct")) is not bool for r in blocks),
        unclassified_block_count=unclassified,
        error_count=sum(r["actual_action"] == "ERROR" for r in rows))


def validator_metrics(candidates):
    candidates = list(candidates)
    if len({r["candidate_id"] for r in candidates}) != len(candidates):
        raise ValueError("후보 분모 중복")
    if any(type(r.get("correct")) is not bool or type(r.get("blocked")) is not bool for r in candidates):
        raise ValueError("후보 정답/차단 판정 필요")
    correct = [r for r in candidates if r["correct"]]
    wrong = [r for r in candidates if not r["correct"]]
    blocked = [r for r in candidates if r["blocked"]]
    return dict(candidate_count=len(candidates),
        validator_block_precision=_ratio(sum(not r["correct"] for r in blocked),len(blocked)),
        validator_false_block_rate=_ratio(sum(r["blocked"] for r in correct),len(correct)),
        validator_missed_error_rate=_ratio(sum(not r["blocked"] for r in wrong),len(wrong)))


def paired_gate(pairs, *, control_width, must_have_regressions, ledger_recall_regressed,
                cost_neutral=False, cost_gate_passed=False):
    """같은 사전 고정 질문 ID 집합의 최소 3회 짝비교. 실측 승격은 외부 인수다."""
    if len(pairs) < 3:
        raise ValueError("최소 3회 짝비교 필요")
    if control_width < 0 or must_have_regressions < 0:
        raise ValueError("음수 판정 입력")
    ids = set(pairs[0][0])
    if not ids:
        raise ValueError("빈 분모")
    deltas = []
    for baseline, candidate in pairs:
        if set(baseline) != ids or set(candidate) != ids:
            raise ValueError("실행별 질문 분모 불일치")
        if any(type(v) is not bool for v in [*baseline.values(), *candidate.values()]):
            raise ValueError("성공/실패 판정 필요")
        deltas.append(sum(candidate.values())-sum(baseline.values()))
    threshold = max(5, ceil(control_width * (1 if cost_neutral else 1.5)))
    eligible = median(deltas) >= threshold and sum(d>0 for d in deltas)*3 >= len(deltas)*2
    eligible = eligible and must_have_regressions==0 and not ledger_recall_regressed and cost_gate_passed
    return dict(deltas=deltas, median_delta=median(deltas), threshold=threshold,
                eligible=eligible, scope="ARITHMETIC_GATE_NOT_PRODUCTION_PROMOTION")
