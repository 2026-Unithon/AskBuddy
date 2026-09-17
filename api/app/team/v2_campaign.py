"""고정 manifest·arm 설정·A/A 대조를 확인한 뒤 R 반복 산술 게이트에 연결한다."""
from pathlib import Path
from app.contracts.hashing import digest
from app.team.answer_metrics import paired_gate
from app.team.v2_evaluation import build_v2_report


def run_signature(run):
    """서로 달라도 되는 A/B 설정은 arm별로 고정하고 반복 중 변경은 거절한다."""
    if run['configuration_hash']!=digest(run['configuration']):raise ValueError('configuration hash mismatch')
    if not run.get('source_hashes'):raise ValueError('source manifest required')
    return dict(configuration_hash=run['configuration_hash'],source_hashes=run['source_hashes'],
                provider_mode=run['provider_mode'],scope=run['scope'])


def campaign_input_hash(plan,baseline,candidate,control):
    return digest(dict(plan=plan,baseline=[r['run_hash'] for r in baseline],
        candidate=[r['run_hash'] for r in candidate],control=[r['run_hash'] for r in control]))


def compare_campaign(plan,*,baseline,candidate,control,judgments=None,evidence=None):
    """순서가 사전 고정된 짝을 받는다. hash는 서명/실제 사전등록 증명이 아니다.

    judgments는 run_hash → 검토 목록. evidence는 이 입력 hash에 연결된 별도 비용/원장 인수다.
    누락 evidence를 비용 통과/원장 무회귀로 바꾸지 않는다.
    """
    required={'schema_version','manifest_hash','repeat_count','control_count','baseline_signature',
              'candidate_signature','cost_neutral','registration_ref'}
    if set(plan)!=required or plan['schema_version']!='r_v2_campaign_plan/v1':raise ValueError('invalid campaign plan')
    if (type(plan['repeat_count']) is not int or type(plan['control_count']) is not int
            or plan['repeat_count']<3 or plan['control_count']<3 or type(plan['cost_neutral']) is not bool
            or not isinstance(plan['registration_ref'],str) or not plan['registration_ref'].strip()):
        raise ValueError('preregistered repetitions and reference required')
    if len(baseline)!=plan['repeat_count'] or len(candidate)!=plan['repeat_count'] or len(control)!=plan['control_count']:
        raise ValueError('missing or extra repetitions')
    runs=[*baseline,*candidate,*control]
    if len({r['run_id'] for r in runs})!=len(runs) or len({r['run_hash'] for r in runs})!=len(runs):
        raise ValueError('duplicate run reused as independent repetition')
    labels=judgments or {}
    if set(labels)-{r['run_hash'] for r in runs}:raise ValueError('foreign run judgments')
    reports={}
    for arm,signature in ((baseline,plan['baseline_signature']),(candidate,plan['candidate_signature']),
                          (control,plan['baseline_signature'])):
        for run in arm:
            report=build_v2_report(run,labels.get(run['run_hash']))
            if run['manifest_hash']!=plan['manifest_hash']:raise ValueError('question/truth/snapshot manifest mismatch')
            if run_signature(run)!=signature:raise ValueError('arm configuration/source/provider drift')
            if not report['paired_gate_input']:raise ValueError('empty answerable denominator')
            reports[run['run_hash']]=report
    # A/B가 합성/실제 또는 다른 프로토콜이면 개선량의 비교 조건이 아니다.
    if any(plan['baseline_signature'][k]!=plan['candidate_signature'][k] for k in ('provider_mode','scope')):
        raise ValueError('provider mode or protocol differs between arms')
    input_hash=campaign_input_hash(plan,baseline,candidate,control)
    reasons=[]
    required_actions={c['question_id']:c['expected_action'] for c in baseline[0]['manifest']['cases']
                      if c['must_have'] and c['expected_action']!='ANSWER'}
    # Q_A 순증 밖의 필수 정책/비답변도 조용히 안전성 분모에서 버리지 않는다.
    for run in candidate:
        for row in reports[run['run_hash']]['rows']:
            expected=required_actions.get(row['question_id'])
            if expected and row['actual_action']!=expected:reasons.append('MUST_HAVE_ACTION_FAILURE')
            elif expected in ('CLARIFY','ESCALATE'):
                if row['action_correct'] is False: reasons.append('MUST_HAVE_ACTION_FAILURE')
                elif row['action_correct'] is not True: reasons.append('MUST_HAVE_NONANSWER_REVIEW_REQUIRED')
    cost=False
    ledger=False
    if evidence is None:
        reasons.extend(('COST_UNVERIFIED','LEDGER_UNVERIFIED'))
    else:
        if set(evidence)!={'input_hash','cost_gate_passed','ledger_recall_regressed','reviewer','reference'}:
            raise ValueError('invalid external evidence')
        if evidence['input_hash']!=input_hash:raise ValueError('evidence belongs to another campaign')
        if any(not isinstance(evidence[k],str) or not evidence[k].strip() for k in ('reviewer','reference')):
            raise ValueError('evidence attribution required')
        if any(evidence[k] is not None and type(evidence[k]) is not bool for k in ('cost_gate_passed','ledger_recall_regressed')):
            raise ValueError('external gates require bool or None')
        if evidence['cost_gate_passed'] is None:reasons.append('COST_UNVERIFIED')
        if evidence['ledger_recall_regressed'] is None:reasons.append('LEDGER_UNVERIFIED')
        cost=evidence['cost_gate_passed'] is True
        ledger=evidence['ledger_recall_regressed'] is True
    controls=[reports[r['run_hash']]['paired_gate_input'] for r in control]
    counts=[None if any(v is None for v in values.values()) else sum(values.values()) for values in controls]
    width=None if None in counts else max(counts)-min(counts)
    if width is None:reasons.append('CONTROL_UNJUDGED')
    pairs=[(reports[a['run_hash']]['paired_gate_input'],reports[b['run_hash']]['paired_gate_input'])
           for a,b in zip(baseline,candidate)]
    gate=paired_gate(pairs,control_width=width if width is not None else 0,
        must_have_regressions=0,ledger_recall_regressed=ledger,cost_neutral=plan['cost_neutral'],
        cost_gate_passed=cost,must_have_ids=reports[baseline[0]['run_hash']]['must_have_answer_ids'])
    if width is None:
        # 미판정 대조군의 폭을 0으로 보고하지 않는다. 이때 산술 문턱도 미확정이다.
        gate['threshold']=None
        gate['blocking_reasons']=[r for r in gate['blocking_reasons'] if r!='BELOW_EFFECT_THRESHOLD']
    reasons=list(dict.fromkeys([*reasons,*gate['blocking_reasons']]))
    gate['blocking_reasons']=reasons
    gate['eligible']=not reasons
    evaluator_files=('v2_campaign.py','v2_evaluation.py','answer_metrics.py')
    return dict(schema_version='r_v2_campaign/v1',input_hash=input_hash,plan=plan,
        evaluator_hashes={name:digest((Path(__file__).parent/name).read_text(encoding='utf-8')) for name in evaluator_files},
        control_counts=counts,control_width=width,gate=gate,evidence=evidence,
        run_hashes=dict(baseline=[r['run_hash'] for r in baseline],candidate=[r['run_hash'] for r in candidate],
                        control=[r['run_hash'] for r in control]),
        judgment_hash=digest(labels),reports=reports,production_promotion=False,
        scope='REVIEWED_ARITHMETIC_GATE_NOT_PRODUCTION_PROMOTION')
