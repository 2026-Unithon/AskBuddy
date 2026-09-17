"""실험설계 §6/§9의 v2 질문/후보 분모. legacy HIT/MISS 평가와 분리한다."""
from statistics import median
from math import ceil, isfinite
from collections import defaultdict

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
                cost_neutral=False, cost_gate_passed=False, must_have_ids=None):
    """고정 Q_A 반복 평가. True=완전 정답, False=실패, None=미판정.

    must_have_ids는 결과 확인 전에 고정한 필수 질문 집합이다. 누락과 명시적 빈
    집합을 구분한다. 외부 악화 건수는 추가 차단용이며 관측한 악화를 덮지 못한다.
    입력 동일성/사람 truth/운영 승격까지 증명하는 함수는 아니다.
    """
    if len(pairs) < 3:
        raise ValueError("최소 3회 짝비교 필요")
    if (type(control_width) not in (int, float) or not isfinite(control_width)
            or control_width < 0 or type(must_have_regressions) is not int
            or must_have_regressions < 0):
        raise ValueError("유한한 비음수 폭/정수 악화 건수 필요")
    if any(type(v) is not bool for v in (ledger_recall_regressed, cost_neutral, cost_gate_passed)):
        raise ValueError("원장/비용 게이트의 확정 bool 판정 필요")
    ids = set(pairs[0][0])
    if not ids or any(type(k) is not str or not k.strip() for k in ids):
        raise ValueError("비어 있지 않은 문자열 질문 ID 필요")
    if must_have_ids is None:
        required = set()
    else:
        if not isinstance(must_have_ids, (list, tuple, set, frozenset)):
            raise ValueError("필수 질문 ID 컬렉션 필요")
        if any(type(k) is not str for k in must_have_ids):
            raise ValueError("필수 질문 ID는 문자열")
        required = set(must_have_ids)
        if len(required) != len(must_have_ids) or not required <= ids:
            raise ValueError("필수 질문 중복/분모 밖 ID")
    deltas = []
    for baseline, candidate in pairs:
        if set(baseline) != ids or set(candidate) != ids:
            raise ValueError("실행별 질문 분모 불일치")
        values = [*baseline.values(), *candidate.values()]
        if any(v is not None and type(v) is not bool for v in values):
            raise ValueError("성공/실패/미판정은 bool 또는 None")
        deltas.append(None if any(v is None for v in values)
                      else sum(candidate.values())-sum(baseline.values()))

    def state(values):
        if any(v is None for v in values):
            return "UNJUDGED"
        if all(values):
            return "ALL_SUCCESS"
        if not any(values):
            return "ALL_FAILURE"
        return "MIXED"

    transitions = defaultdict(list)
    unjudged = []
    regressions = []
    for question_id in sorted(ids):
        before = [a[question_id] for a, _ in pairs]
        after = [b[question_id] for _, b in pairs]
        transitions[f"{state(before)}->{state(after)}"].append(question_id)
        if any(v is None for v in before + after):
            unjudged.append(question_id)
        if question_id in required and any(a is True and b is False for a, b in zip(before, after)):
            regressions.append(question_id)

    reasons = []
    if must_have_ids is None:
        reasons.append("MISSING_MUST_HAVE_MANIFEST")
    if unjudged:
        reasons.append("UNJUDGED_RESULTS")
    if regressions or must_have_regressions:
        reasons.append("MUST_HAVE_REGRESSION")
    if ledger_recall_regressed:
        reasons.append("LEDGER_RECALL_REGRESSION")
    if not cost_gate_passed:
        reasons.append("COST_GATE_NOT_PASSED")
    threshold = max(5, ceil(control_width * (1 if cost_neutral else 1.5)))
    representative = None if unjudged else median(deltas)
    if representative is not None:
        if representative < threshold:
            reasons.append("BELOW_EFFECT_THRESHOLD")
        if sum(d > 0 for d in deltas)*3 < len(deltas)*2:
            reasons.append("INSUFFICIENT_POSITIVE_PAIRS")
    required_passed = (False if regressions or must_have_regressions else
                       None if must_have_ids is None or required.intersection(unjudged) else True)
    return dict(schema_version="r_paired_gate/v2", question_count=len(ids), repeat_count=len(pairs),
                deltas=deltas, median_delta=representative, threshold=threshold,
                must_have_ids=None if must_have_ids is None else sorted(required),
                must_have_regression_ids=regressions, observed_must_have_regressions=regressions,
                must_have_passed=required_passed,
                unjudged_ids=unjudged, stability_transitions=dict(sorted(transitions.items())),
                blocking_reasons=reasons, eligible=not reasons,
                scope="ARITHMETIC_GATE_NOT_PRODUCTION_PROMOTION")
