"""격리된 순수 진단: 후보 회수와 planner/validator 문제를 나눠 관찰한다."""
from app.contracts.answer import AnswerPlan
from app.contracts.hashing import digest
from app.learn.answer_validation import validate_answer_for_question, AnswerReferenceError
from app.learn.planner import decide
from app.reg.hybrid import Candidate, SearchResult
from app.team.evidence_truth import resolve_evidence, evidence_recall


def diagnose_oracle(pool, truth, ranked_references, *, k=10):
    snapshot,truth,needed,blocks=resolve_evidence(pool,truth)
    retrieval=evidence_recall(pool,truth.model_dump(),ranked_references,k=k)
    raw_needed={item.reference() for item in truth.required_raw}
    oracle=sorted(ref for ref,fids in blocks.items() if fids&needed or ref in raw_needed)
    def decision(refs):
        search=SearchResult(snapshot,0,tuple(Candidate(*ref,None,None,0) for ref in refs),'')
        result=decide(search,store_id=int(snapshot.store_id),question=pool['question'])
        return dict(plan=result.plan.model_dump(mode='json'),
            semantic_correct=None,action=result.plan.action)
    result=dict(schema_version='r_oracle_diagnostics/v1',pool_hash=pool['pool_hash'],
        truth_hash=digest(truth.model_dump(mode='json')),
        retrieval_only=retrieval,retrieved=decision([tuple(r) for r in ranked_references[:k]]),
        oracle_injected=decision(oracle),oracle_references=[list(r) for r in oracle],
        scope='PURE_ISOLATED_PLANNER',production_promotion=False)
    return dict(result,diagnostic_hash=digest(result))


def diagnose_validator(plan, snapshot, resolved, *, store_id: int):
    """후보를 저장하거나 사용자에게 표시하지 않고 검증 통과/거절을 기록한다."""
    plan=AnswerPlan.model_validate(plan.model_dump())
    before=plan.model_dump(mode='json')
    try:
        validate_answer_for_question(plan,snapshot,resolved,store_id=store_id)
    except AnswerReferenceError as exc:
        return dict(candidate=before,validator_passed=False,rejection_code=exc.code,
            semantic_correct=None,production_promotion=False)
    return dict(candidate=before,validator_passed=True,rejection_code=None,
        semantic_correct=None,production_promotion=False)
