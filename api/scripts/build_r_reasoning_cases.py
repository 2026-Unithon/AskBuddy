"""Create a public synthetic multi-fact/multi-turn challenge pack; no model evaluation."""
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/r-reasoning-challenge-20261006'

FACTS = [
    ('F01','레시피','HOT M 라테의 기본 우유량은 225ml다.'),
    ('F02','레시피','ICE M 라테의 기본 우유량은 175ml다.'),
    ('F03','규격','라테 L은 같은 온도의 M보다 우유 또는 대체 음료를 50ml 더 사용한다.'),
    ('F04','레시피','라테는 온도와 크기에 관계없이 에스프레소 2샷을 사용한다.'),
    ('F05','옵션','디카페인 선택 시 일반 샷을 같은 수의 디카페인 샷으로 교체한다.'),
    ('F06','옵션','오트 선택 시 레시피의 우유를 같은 부피의 오트 음료로 교체한다.'),
    ('F07','보관','일반 우유는 2번 냉장고에 보관한다.'),
    ('F08','보관','오트 음료는 3번 냉장고에 보관한다.'),
    ('F09','가격','HOT/ICE M 일반 우유·일반 샷 라테의 기본 가격은 4,500원이다.'),
    ('F10','가격','라테 L 변경은 잔당 1,000원 추가다.'),
    ('F11','가격','라테 오트 변경은 잔당 500원 추가다.'),
    ('F12','가격','라테 디카페인 변경은 잔당 500원 추가다.'),
    ('F13','가격','크기·오트·디카페인 추가금은 함께 선택하면 모두 합산한다. 묶음 할인은 없다.'),
    ('F14','대체','일반 우유가 부족해 오트로 대체할 때에는 고객 동의를 먼저 받아야 한다.'),
    ('F15','마감','마감할 때에는 남은 환불 처리를 완료한 뒤 현금을 센다.'),
    ('F16','마감','현금 계산을 마친 뒤 POS 마감을 실행한다.'),
    ('F17','마감','POS 마감을 실행한 뒤 점주에게 마감 합계 보고를 보낸다.'),
]


def turn(question, facts, answer, *, action='ANSWER', slots=None, forbidden=(), derives=(), checks=()):
    return dict(question=question, expected_action=action, required_fact_ids=list(facts),
        reference_answer=answer, expected_context=slots or {}, forbidden_claims=list(forbidden),
        derivations=list(derives), grading_checks=list(checks))


def case(ident, kind, title, turns, failure, *, tier='COMPOSITION'):
    return dict(case_id=ident, kind=kind, title=title, tier=tier, turns=turns,
        failure_to_detect=failure, execution_status='NOT_RUN')


def pack():
    cases=[
        case('C01','단일 질문','레시피 + 규격 + 옵션 + 보관 위치',[
            turn('따뜻한 L 라테를 오트와 디카페인으로 만들 때, 재료 양과 샷 수, 재료를 꺼낼 위치까지 알려줘.',
                ['F01','F03','F04','F05','F06','F08'],
                '3번 냉장고의 오트 음료 275ml와 디카페인 2샷을 사용합니다.',
                slots=dict(menu='라테',temperature='HOT',size='L',milk='OAT',coffee='DECAF'),
                forbidden=['일반 우유 275ml','오트 음료 225ml','일반 샷 2샷','2번 냉장고'],
                derives=['225ml + 50ml = 275ml'],checks=['수량·샷 종류/수·보관 위치를 모두 포함한다.'])],
            '각 옵션은 찾지만 서로 연결하지 못하거나 다른 재료의 위치를 섞는 오류'),
        case('C02','단일 질문','온도별 조리량 비교',[
            turn('오트 L 라테는 따뜻한 것과 차가운 것에 각각 얼마나 들어가고, 둘의 차이는 얼마야?',
                ['F01','F02','F03','F06'],'HOT은 오트 275ml, ICE는 오트 225ml이며 HOT이 50ml 더 많습니다.',
                forbidden=['HOT과 ICE 모두 275ml','ICE 175ml'],
                derives=['HOT: 225 + 50 = 275ml','ICE: 175 + 50 = 225ml','차이: 275 - 225 = 50ml'])],
            '규격별 사실을 합쳐 범위 하나로 답하거나 L 추가량을 누락하는 오류'),
        case('C03','단일 질문','조건부 대체 + 수량 + 위치',[
            turn('HOT M 라테 주문인데 우유가 부족해. 오트로 바로 바꿔도 돼? 동의받았다면 어디에서 얼마나 꺼내?',
                ['F01','F06','F08','F14'],
                '바로 바꾸면 안 됩니다. 먼저 고객 동의를 받고, 동의했다면 3번 냉장고에서 오트 225ml를 꺼냅니다.',
                forbidden=['고객 동의 없이 대체','2번 냉장고에서 오트'],
                checks=['대체 전 동의 조건과 동의 후 실행을 구분한다.'])],
            '양과 위치만 맞고 고객 동의라는 필수 선행 조건을 빠뜨리는 오류'),
        case('C04','단일 질문','세 사실의 선후 관계 연결',[
            turn('환불 처리도 남았고 현금도 아직 안 셌어. POS 마감과 점주 보고까지 어떤 순서로 하면 돼?',
                ['F15','F16','F17'],'남은 환불 처리 → 현금 계산 → POS 마감 → 점주에게 마감 합계 보고 순서입니다.',
                forbidden=['현금 계산 전에 POS 마감','POS 마감 전에 점주 합계 보고'],
                checks=['네 단계가 빠짐없이 올바른 순서로 연결된다.'])],
            '개별 절차는 찾지만 전체 순서를 잘못 조립하는 오류'),
        case('C05','단일 질문','가격 규칙의 합산',[
            turn('ICE L 라테에 오트랑 디카페인을 둘 다 추가하면 한 잔 얼마야? 항목별로도 알려줘.',
                ['F09','F10','F11','F12','F13'],
                '기본 4,500원 + L 1,000원 + 오트 500원 + 디카페인 500원으로 총 6,500원입니다.',
                derives=['4500 + 1000 + 500 + 500 = 6500원'],
                forbidden=['옵션 중 하나만 과금','묶음 할인 적용'])],
            '관련 가격 사실 일부를 누락하거나 근거 없는 할인을 적용하는 오류',tier='ARITHMETIC_EXTENSION'),
        case('C06','단일 질문','여러 잔의 재료 합계와 단위 구분',[
            turn('HOT L 오트 디카페인 라테 2잔과 ICE M 일반 라테 1잔을 준비해. 오트·우유 총량과 일반·디카페인 샷을 각각 알려줘.',
                ['F01','F02','F03','F04','F05','F06'],
                '오트는 550ml, 일반 우유는 175ml입니다. 디카페인 4샷과 일반 2샷이 필요합니다.',
                derives=['오트: (225 + 50) × 2 = 550ml','우유: 175 × 1 = 175ml','디카페인: 2 × 2 = 4샷','일반: 2 × 1 = 2샷'],
                forbidden=['우유와 오트를 구분 없이 725ml만 제시','일반 6샷'])],
            '잔 수·재료 종류·샷 종류를 서로 섞거나 잔당 수치만 답하는 오류',tier='ARITHMETIC_EXTENSION'),
        case('D01','연속 대화','한 조건씩 변경하고 나머지 유지',[
            turn('HOT M 라테의 우유 양과 샷 수 알려줘.',['F01','F04'],'일반 우유 225ml와 일반 2샷입니다.',
                slots=dict(menu='라테',temperature='HOT',size='M',milk='DAIRY',coffee='REGULAR')),
            turn('그거 우유만 오트로 바꿀게. 어디서 얼마나 꺼내?',['F01','F06','F08'],'3번 냉장고에서 오트 225ml를 꺼냅니다. HOT M 조건은 유지됩니다.',
                slots=dict(menu='라테',temperature='HOT',size='M',milk='OAT',coffee='REGULAR'),forbidden=['ICE로 변경','일반 우유 사용']),
            turn('크기는 큰 걸로. 샷은 그대로 맞지?',['F01','F03','F04','F06'],'HOT L 오트 라테로 바뀌므로 오트 275ml이며 샷은 일반 2샷 그대로입니다.',
                slots=dict(menu='라테',temperature='HOT',size='L',milk='OAT',coffee='REGULAR'),derives=['225 + 50 = 275ml'],
                forbidden=['오트 변경을 잊고 일반 우유 사용','샷 수 3으로 증가'])],
            '최근 한 턴만 읽어 온도나 오트 선택을 잊거나 크기와 샷 수를 같이 바꾸는 오류'),
        case('D02','연속 대화','두 조건 수정과 기존 옵션 취소',[
            turn('HOT L 오트 라테의 재료 양과 샷 수 알려줘.',['F01','F03','F04','F06'],'오트 275ml와 일반 2샷입니다.',
                slots=dict(menu='라테',temperature='HOT',size='L',milk='OAT',coffee='REGULAR'),derives=['225 + 50 = 275ml']),
            turn('아니, 차갑게 하고 우유도 일반으로 바꿔줘. 어디서 얼마나 꺼내?',['F02','F03','F07'],'ICE L 일반 우유 라테입니다. 2번 냉장고에서 일반 우유 225ml를 꺼냅니다.',
                slots=dict(menu='라테',temperature='ICE',size='L',milk='DAIRY',coffee='REGULAR'),derives=['175 + 50 = 225ml'],
                forbidden=['HOT 275ml 유지','오트 유지','M으로 축소']),
            turn('샷만 디카페인으로 하면?',['F02','F03','F04','F05'],'ICE L 일반 우유 225ml는 유지하고 샷만 디카페인 2샷으로 교체합니다.',
                slots=dict(menu='라테',temperature='ICE',size='L',milk='DAIRY',coffee='DECAF'),derives=['175 + 50 = 225ml'])],
            '명시적으로 취소한 이전 옵션을 계속 적용하거나 샷 변경 때 다른 조건까지 초기화하는 오류'),
        case('D03','연속 대화','두 주문을 분리해 지시어 연결',[
            turn('HOT M 라테 한 잔이랑 ICE L 라테 한 잔, 우유 양과 샷 수를 각각 알려줘.',['F01','F02','F03','F04'],
                'HOT M은 일반 우유 225ml와 일반 2샷, ICE L도 일반 우유 225ml와 일반 2샷입니다.',
                slots=dict(order_a='HOT M DAIRY REGULAR',order_b='ICE L DAIRY REGULAR'),derives=['ICE L: 175 + 50 = 225ml']),
            turn('차가운 것만 오트로 바꾸면 어디서 얼마나 꺼내?',['F02','F03','F06','F08'],
                'ICE L 한 잔만 3번 냉장고의 오트 225ml로 바꿉니다. HOT M 한 잔은 일반 우유 그대로입니다.',
                slots=dict(order_a='HOT M DAIRY REGULAR',order_b='ICE L OAT REGULAR'),derives=['175 + 50 = 225ml'],
                forbidden=['두 잔 모두 오트로 변경']),
            turn('그럼 큰 것의 샷만 디카페인으로 해줘. 최종 두 잔을 정리해줘.',['F01','F02','F03','F04','F05','F06'],
                'HOT M은 일반 우유 225ml와 일반 2샷, ICE L은 오트 225ml와 디카페인 2샷입니다.',
                slots=dict(order_a='HOT M DAIRY REGULAR',order_b='ICE L OAT DECAF'),derives=['ICE L: 175 + 50 = 225ml'],
                forbidden=['두 잔 모두 디카페인으로 변경','ICE L의 오트 선택 취소'])],
            '차가운 것/큰 것을 잘못된 주문에 연결하거나 주문 간 옵션이 섞이는 오류'),
        case('D04','연속 대화','빠진 조건만 확인하고 짧은 답 수용',[
            turn('오트 L 라테는 얼마나 넣어?',['F01','F02','F03','F06'],'HOT인지 ICE인지 확인해야 합니다.',action='CLARIFY',
                slots=dict(menu='라테',size='L',milk='OAT'),forbidden=['HOT으로 임의 확정','ICE로 임의 확정'],
                checks=['이미 정해진 메뉴·크기·오트는 다시 묻지 않고 온도만 묻는다.']),
            turn('차갑게.',['F02','F03','F06'],'ICE L이므로 오트 225ml를 넣습니다.',
                slots=dict(menu='라테',temperature='ICE',size='L',milk='OAT'),derives=['175 + 50 = 225ml']),
            turn('그 재료는 어디에 있어?',['F08'],'오트 음료는 3번 냉장고에 있습니다.',
                slots=dict(menu='라테',temperature='ICE',size='L',milk='OAT'),forbidden=['일반 우유 위치인 2번 냉장고'])],
            '재질문 전 조건을 잊거나 생략한 재료를 일반 우유로 잘못 해석하는 오류'),
        case('D05','연속 대화','알 수 없는 재고와 알려진 레시피 분리',[
            turn('ICE M 오트 라테의 재료 양과 샷 수 알려줘.',['F02','F04','F06'],'오트 175ml와 일반 2샷입니다.',
                slots=dict(menu='라테',temperature='ICE',size='M',milk='OAT',coffee='REGULAR')),
            turn('그 재료 지금 매장에 얼마나 남아 있어?',[],
                '현재 오트 재고 정보가 없어 확인이 필요합니다. 레시피의 175ml는 남은 재고량이 아닙니다.',action='ESCALATE',
                slots=dict(menu='라테',temperature='ICE',size='M',milk='OAT',coffee='REGULAR'),
                forbidden=['오트 재고가 175ml 남음','3번 냉장고에 있으니 재고 충분']),
            turn('그럼 재고 말고 아까 레시피만 다시 알려줘.',['F02','F04','F06'],'ICE M 오트 라테는 오트 175ml와 일반 2샷입니다.',
                slots=dict(menu='라테',temperature='ICE',size='M',milk='OAT',coffee='REGULAR'),
                forbidden=['재고 확인 없이는 레시피도 답할 수 없음'])],
            '레시피 양을 재고량으로 답하거나 모르는 질문 이후 알려진 질문까지 계속 차단하는 오류'),
        case('D06','연속 대화','주제 전환 뒤 이전 주제로 복귀',[
            turn('HOT L 오트 라테의 양 알려줘.',['F01','F03','F06'],'오트 275ml입니다.',
                slots=dict(menu='라테',temperature='HOT',size='L',milk='OAT'),derives=['225 + 50 = 275ml']),
            turn('이제 마감할 건데 환불부터 점주 보고까지 순서 알려줘.',['F15','F16','F17'],
                '남은 환불 처리 → 현금 계산 → POS 마감 → 점주에게 마감 합계 보고 순서입니다.',slots=dict(active_topic='마감'),
                forbidden=['음료 조리 조건을 마감 답변에 적용']),
            turn('아까 그 음료, 아이스로 바꾸면 양이 어떻게 달라져?',['F01','F02','F03','F06'],
                'L 오트 조건을 유지하면 HOT 275ml에서 ICE 225ml로 바뀌어 50ml 줄어듭니다.',
                slots=dict(menu='라테',temperature='ICE',size='L',milk='OAT'),
                derives=['HOT: 225 + 50 = 275ml','ICE: 175 + 50 = 225ml','275 - 225 = 50ml'])],
            '최근 주제만 기억해 음료를 복원하지 못하거나 L·오트 조건을 잃는 오류'),
    ]
    return dict(schema_version='r_reasoning_challenge/v1',created_date='2026-10-06',status='DESIGNED_NOT_EXECUTED',
        truth_kind='SYNTHETIC_AGENT_AUTHORED_NOT_HUMAN_REVIEWED',
        description='합성 가상 매장 전용. 기존 28개 진단과 다른 입력이며 성능 수치를 직접 비교하지 않는다.',
        facts=[dict(fact_id=i,category=c,assertion=a) for i,c,a in FACTS],cases=cases,
        conventions=[
            '사실 목록은 모두 같은 가상 매장의 현재 승인 사실이다. 실시간 재고·할인 등 추가 사실은 없다.',
            '나열된 수치는 평가 전용이며 실제 매장 레시피나 운영 지침이 아니다.',
            'required_fact_ids는 의미적 근거 ID이며 실제 fact_revision_id/공개 snapshot에 매핑되기 전에는 제품 인용 ID가 아니다.',
            'expected_context는 채점용 정답이다. 실제 질문 요청·모델 입력에 주입하지 않는다.',
            'reference_answer는 허용되는 답변의 한 예다. 동일 의미의 표현도 허용하며 단순 문자열 일치로 채점하지 않는다.',
            '대화는 같은 세션에 원래 사용자 발화만 순서대로 보낸다. 앞선 조건을 평가기가 대신 복구하지 않는다.',
            '미실행·오류·판정 보류도 전체 분모에 남긴다. 아직 어떤 사례도 실행하지 않았다.',
            'C01/C02 및 일부 대화의 수량도 규칙 기반 산술을 포함한다. 산술 지원 여부와 정확도를 별도 기록한다.',
            '가격·다중 주문 합계(C05/C06)는 확장 목표다. 지원되지 않는 기능을 이미 구현된 것으로 보지 않는다.',
        ],grading=dict(
            dimensions=['행동 적절성','필수 사실 완전성','조건·대상 연결','대화 조건 유지/수정','계산 정확성(해당 시)','근거 인용','금지 주장 부재'],
            scenario_pass='모든 예정 턴에서 적용되는 차원을 충족해야 완전 통과. 독립 검토자의 의미 판정 필요.',
            fact_coverage='답변에 올바르게 반영한 필수 fact 수 / 필수 fact 수. 언급만 하고 잘못 연결하면 충족하지 않음.',
            citation='각 주장과 근거가 대응해야 한다. 계산 결과는 원문 인용으로 위장하지 않고 입력 사실과 계산식을 함께 제시.',
            reporting='단일 질문/연속 대화 및 조합/산술 포함 사례를 분리 보고. 큰 통합 점수 하나로 숨기지 않는다.'),
        execution=dict(status='NOT_RUN',reason='난이도 높은 평가 설계 산출물. 실제 승인 snapshot 매핑과 의미 채점 후 실행.',
            full_chat_accuracy=None,pass_rate=None))


def validate(data):
    known={f['fact_id'] for f in data['facts']}
    assert len(known)==len(data['facts'])==17
    assert len({c['case_id'] for c in data['cases']})==len(data['cases'])==12
    assert sum(len(c['turns']) for c in data['cases'])==24
    for c in data['cases']:
        assert len({f for t in c['turns'] for f in t['required_fact_ids']})>=3
        for t in c['turns']:
            assert set(t['required_fact_ids'])<=known
            assert len(set(t['required_fact_ids']))==len(t['required_fact_ids'])
            assert t['expected_action'] in ('ANSWER','CLARIFY','ESCALATE')
            assert t['reference_answer'] and t['question']
            if t['expected_action']=='ANSWER':assert t['required_fact_ids']
    assert 4500+1000+500+500==6500
    assert (225+50)*2==550 and 175+50==225


def write_html(data):
    e=html.escape
    cards=[]
    facts={f['fact_id']:f for f in data['facts']}
    for c in data['cases']:
        turns=[]
        for n,t in enumerate(c['turns'],1):
            grounding=''.join(f'<li><b>{i}</b> {e(facts[i]["assertion"])}</li>' for i in t['required_fact_ids']) or '<li>현재 재고를 뒷받침하는 사실 없음</li>'
            turns.append(f'<section class="turn"><h3>{n}턴 · {e(t["question"])}</h3>'
                f'<details><summary>기대 답변과 채점 기준 보기</summary><p class="answer">{e(t["reference_answer"])}</p>'
                f'<p><b>기대 행동:</b> {t["expected_action"]}</p><ul>{grounding}</ul>'
                +(f'<p><b>계산:</b> {e(" / ".join(t["derivations"]))}</p>' if t['derivations'] else '')
                +(f'<p><b>유지·수정할 조건:</b> {e(json.dumps(t["expected_context"],ensure_ascii=False))}</p>' if t['expected_context'] else '')
                +(f'<p class="bad"><b>오답 예:</b> {e(" / ".join(t["forbidden_claims"]))}</p>' if t['forbidden_claims'] else '')
                +(f'<p><b>추가 확인:</b> {e(" / ".join(t["grading_checks"]))}</p>' if t['grading_checks'] else '')
                +'</details></section>')
        cards.append(f'<article><div class="tag">{c["case_id"]} · {e(c["kind"])} · 미실행</div>'
            f'<h2>{e(c["title"])}</h2>'+''.join(turns)+f'<p class="target"><b>잡아낼 오류:</b> {e(c["failure_to_detect"])}</p></article>')
    source_rows=''.join(f'<tr><td>{f["fact_id"]}</td><td>{e(f["category"])}</td><td>{e(f["assertion"])}</td></tr>' for f in data['facts'])
    doc='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AskBuddy 복합 질문 챌린지</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f3f5f9;color:#1f3045;font-family:'Malgun Gothic',sans-serif}main{max-width:1060px;padding:40px 24px;margin:auto}header{padding:32px;background:#142d4b;color:white;border-radius:18px}header p{color:#d4e0ef}h1{font-size:34px;line-height:1.4}h2{font-size:22px}h3{font-size:17px;line-height:1.7}p,li{line-height:1.85}article{background:white;border:1px solid #dce4ed;border-radius:14px;padding:26px;margin:20px 0}.tag{font-size:13px;color:#526c89}.turn{border-top:1px solid #e3e8f0;padding:6px 0 14px}details{background:#f4f7fb;padding:15px;border-radius:9px}summary{cursor:pointer;color:#285b95}details[open] summary{margin-bottom:16px}.answer{background:#e4f1ed;padding:14px;border-radius:7px}.bad{color:#903f36}.target{border-left:3px solid #bf8b44;padding-left:14px}.note{background:#fff1d4;border-radius:12px;padding:20px;margin:22px 0}.facts{overflow:auto}table{width:100%;border-collapse:collapse;background:white}td,th{padding:11px;border-bottom:1px solid #dfe5ed;text-align:left;line-height:1.7}button{background:#295f99;color:white;border:0;border-radius:8px;padding:12px 17px;font:inherit;cursor:pointer;margin:6px 8px 6px 0}footer{color:#5e7189;font-size:13px;margin-top:30px}@media print{body{background:white}header{background:#eee;color:#142d4b}header p{color:#142d4b}button{display:none}article{break-inside:avoid}main{padding:0}}</style>
<main><header><div>ASKBUDDY / REASONING CHALLENGE / 2026.10.06</div><h1>한 질문에 여러 사실,<br>여러 대화에 하나의 일관된 조건</h1><p>가상 매장의 사실 17개 · 복합 단일 질문 6개 · 3턴 대화 6개<br>총 12개 시나리오 / 24개 사용자 발화</p></header>
<div class="note"><b>평가 문제집입니다. 아직 실행한 성능 결과가 아닙니다.</b><br>질문·정답·필수 근거·오답 조건을 고정했습니다. 조건 조합, 지시어, 수정, 주제 복귀, 알 수 없는 정보와 산술을 분리해서 채점합니다. 앞선 28개 진단과 입력이 달라 점수를 직접 비교할 수 없습니다.</div>
<p>정답을 먼저 보지 않고 질문만 시연할 수 있도록 답변은 접어 두었습니다. 사실 ID는 평가용이며 실제 제품 fact_revision ID가 아닙니다.</p>
<button onclick="document.querySelectorAll('details').forEach(d=>d.open=true)">정답 모두 열기</button><button onclick="document.querySelectorAll('details').forEach(d=>d.open=false)">정답 모두 접기</button>
CASES
<h2>평가의 기준이 되는 합성 사실 17개</h2><div class="facts"><table><tr><th>ID</th><th>분류</th><th>승인 사실</th></tr>FACTS</table></div>
<h2>채점할 때 볼 것</h2><p>① 필요한 사실을 빠짐없이 포함했는가<br>② 대상·온도·크기·재료 조건을 맞게 연결했는가<br>③ 후속 발화에서 바뀐 조건만 바꾸고 나머지를 유지했는가<br>④ 모르는 재고를 조리량으로 꾸며 답하지 않았는가<br>⑤ 계산이 필요한 경우 입력 사실과 계산식을 구분했는가<br>⑥ 각 주장에 올바른 근거를 붙였는가</p>
<p>한 사실만 맞힌 답변은 전체 정답으로 세지 않습니다. 대화 시나리오는 모든 예정 턴이 기준을 충족해야 완전 통과합니다. 표현은 달라도 의미가 같으면 허용하며, 문자열 일치만으로 채점하지 않습니다.</p>
<footer>모든 자료는 합성이며 독립 사람 검토 전입니다. 제품 코드를 수정하거나 모델·운영 API를 호출하지 않았습니다. 기대 조건은 채점 전용이며 질문 요청에 주입하면 안 됩니다. 가격·다중 주문 산술은 별도 확장 평가 항목입니다.<br>질문 원본과 채점 규칙: challenge.json · 이 HTML은 외부 연결 없이 파일로 공유할 수 있습니다.</footer></main></html>'''
    (OUT/'AskBuddy-reasoning-challenge.html').write_text(doc.replace('CASES',''.join(cards)).replace('FACTS',source_rows),encoding='utf-8')


if __name__=='__main__':
    data=pack()
    validate(data)
    data['content_sha256']=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'challenge.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write_html(data)
    print('Created 17 facts, 12 scenarios, 24 turns. All references validated. Evaluation NOT RUN.')
