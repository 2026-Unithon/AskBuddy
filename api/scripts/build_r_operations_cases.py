"""Non-recipe synthetic operations challenge. Design only; no API/model calls."""
import hashlib
import html
import json
from pathlib import Path
from build_r_reasoning_cases import turn, case

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/r-operations-challenge-20261006'

FACTS=[
 ('R01','환불','배달앱 결제는 앱 주문번호로 해당 앱에서 환불한다. 매장 POS에서 별도 환불하지 않는다.'),
 ('R02','환불','매장 직접 결제는 원결제 수단으로 POS에서 환불한다. 당일·2만원 이하·영수증 확인·POS 마감 전이면 담당 직원이 처리할 수 있다.'),
 ('R03','환불','결제 경로에 관계없이 2만원 초과 또는 이전 영업일 결제의 환불은 점주 승인이 먼저 필요하다.'),
 ('R04','환불','이미 환불 완료된 거래는 재환불하지 않는다. 승인·접수·완료를 구분하며, 고객 주장만으로 완료 여부를 확정하지 않고 원거래 기록을 확인한다.'),
 ('S01','오픈','오픈 인증자가 현장에 있고 오픈 체크리스트가 모두 완료되어야 영업을 시작한다. 열쇠 소지만으로 오픈 권한이 생기지 않는다.'),
 ('S02','오픈','예정 시각에 오픈 인증자가 없으면 영업 시작을 보류하고 당직 관리자에게 연락한다.'),
 ('S03','근무','영업 중에는 카운터를 볼 수 있는 직원 1명이 현장에 남아 있어야 한다. 휴게 교대 시 인수자가 현장 도착 후 인계받는다.'),
 ('S04','근무','출근 예정·연락 가능 상태는 현장 도착이나 업무 인수 완료를 대신하지 않는다.'),
 ('I01','발주','사용 가능 재고는 실물 재고에서 파손 수량과 기존 주문에 예약된 수량을 뺀 값이다. 예약 수량과 파손 수량은 서로 중복되지 않는다.'),
 ('I02','발주','이 평가 매장의 M컵과 M뚜껑의 목표 재고는 각각 240개다.'),
 ('I03','발주','추가 발주량은 max(0, 목표 재고 - 사용 가능 재고 - 확정 입고 예정량)이다. 견적·미확정 발주량은 입고 예정량에 포함하지 않는다.'),
 ('I04','판매','당장 판매 가능한 포장 수량은 현재 사용 가능한 같은 규격 컵과 뚜껑 수 중 작은 값이다. 미래 입고는 현재 판매 가능량에 넣지 않는다.'),
 ('I05','발주','거래처 발주 접수는 평일 15시 마감이며 15시 이후 확정한 발주는 다음 영업일 접수다. 접수일만으로 배송 완료일을 확정하지 않는다.'),
 ('P01','결제 장애','결제 중 연결이 끊기면 같은 거래를 재결제하기 전에 주문번호와 거래번호로 원결제 상태를 조회한다.'),
 ('P02','결제 장애','원결제 상태가 확인되지 않으면 대기 건으로 남기고 당직 관리자에게 확인을 요청한다. 승인 실패나 결제 완료로 단정하지 않는다.'),
 ('P03','결제 장애','당직 관리자가 해당 주문의 오프라인 현금 결제를 허용한 경우에만 주문번호·금액·수단을 수기 기록하고 현금을 받을 수 있다.'),
 ('P04','결제 장애','연결 복구 후 수기 거래를 등록하기 전 같은 주문번호의 기존 거래가 있는지 확인한다. 연결 복구만으로 대기 거래가 실패한 것은 아니다.'),
 ('C01','마감','마감 순서는 남은 환불 처리 완료 → 현금 대조 → POS 마감 → 점주 합계 보고다.'),
 ('C02','마감','현금 차이가 있으면 한 번 재계산한다. 재계산 후에도 차이가 남으면 점주 확인 전 POS 마감을 보류한다.'),
 ('C03','마감','처리 중 환불이나 미해결 현금 차이가 남으면 마감 완료로 표시하지 않는다. 근무 종료 시 미해결 건을 다음 담당자에게 인계한다.'),
 ('H01','인수인계','미해결 건 인계에는 주문번호 또는 사건번호, 현재 상태, 다음 조치, 기한, 담당자가 모두 필요하다.'),
 ('H02','인수인계','메시지 발송·읽음만으로 인계 완료가 되지 않는다. 지정 인수자가 업무 인수를 확인해야 한다.'),
 ('H03','인수인계','대기 건이 둘 이상이고 지시어의 대상이 불분명하면 사건을 특정하는 질문을 먼저 한다. 한 사건의 상태를 다른 사건에 적용하지 않는다.'),
 ('N01','공지 적용','상시 규칙은 회원 할인과 행사 쿠폰의 중복 적용 불가다.'),
 ('N02','공지 적용','승인된 한시 예외는 2026-10-06부터 2026-10-08까지 매장 직접 결제 포장 주문에 한해 회원 할인과 재오픈 쿠폰의 중복을 허용한다.'),
 ('N03','공지 적용','한시 예외는 배달앱 주문과 다른 행사 쿠폰에는 적용되지 않는다. 기간 종료 후에는 상시 규칙으로 돌아간다.'),
]


def pack():
    cases=[
      case('O01','단일 질문','환불 경로와 승인 권한의 교집합',[
        turn('어제 배달앱으로 2만4천원 결제한 손님이 매장에 와서 카드 취소해 달래. 영수증은 있어. 직원인 내가 바로 POS에서 취소해도 돼? 순서도 알려줘.',
          ['R01','R03','R04'],'바로 POS에서 취소하면 안 됩니다. 앱 주문번호로 원거래와 기존 환불 상태를 확인하고, 이전 영업일·2만원 초과 건이므로 점주 승인을 먼저 받은 뒤 해당 앱에서 환불합니다.',
          forbidden=['POS에서 별도 취소','영수증만 있으면 직원 단독 처리','점주 승인만 받으면 환불 완료'],
          checks=['처리 경로와 승인 필요 여부를 둘 다 판단한다.'])],
        '한 규칙만 찾아 영수증 확인을 승인 권한이나 환불 경로와 혼동하는 오류'),
      case('O02','단일 질문','열쇠·인증·현장 인계 구분',[
        turn('오픈 인증자가 20분 늦고 나는 인증이 없지만 열쇠는 있어. 다른 직원은 전화로 카운터 봐줄 수 있다고 했어. 지금 혼자 열고, 그 직원 오기 전에 창고에 다녀와도 돼?',
          ['S01','S02','S03','S04'],'지금은 영업 시작을 보류하고 당직 관리자에게 연락합니다. 열쇠나 전화상 지원은 현장 오픈 인증자를 대신하지 않습니다. 영업을 시작한 뒤에도 현장 인수자가 오기 전 카운터를 비우면 안 됩니다.',
          forbidden=['열쇠가 있으니 오픈 가능','전화 대기를 현장 인수로 간주'],checks=['오픈 가능 여부와 영업 후 자리 이탈 조건을 분리한다.'])],
        '물리적 접근 권한·업무 인증·현장 인수를 같은 것으로 취급하는 오류'),
      case('O03','단일 질문','사용 재고·미래 입고·현재 판매량 분리',[
        turn('M컵 실물은 180개인데 40개는 파손, 30개는 기존 주문에 잡혀 있어. 내일 70개 입고는 확정이고 추가 50개는 견적만 받았어. M뚜껑은 사용 가능한 게 150개이고 입고 예정은 없어. 컵·뚜껑을 각각 얼마나 더 발주하고, 지금 새 주문은 몇 세트까지 받을 수 있어?',
          ['I01','I02','I03','I04'],
          '컵 사용 가능량은 110개입니다. 컵은 60개, 뚜껑은 90개 추가 발주합니다. 현재 새 주문은 컵과 뚜껑을 맞춰 최대 110세트까지 받을 수 있습니다. 견적 50개와 미래 입고는 현재 판매량에 포함하지 않습니다.',
          derives=['사용 가능 컵: 180 - 40 - 30 = 110','컵 발주: 240 - 110 - 70 = 60','뚜껑 발주: 240 - 150 = 90','현재 세트: min(110,150) = 110'],
          forbidden=['견적 50개를 확정 입고로 반영','내일 입고로 오늘 판매량 증가'])],
        '보유량·가용량·예약량·입고 예정량을 섞는 오류',tier='ARITHMETIC_EXTENSION'),
      case('O04','단일 질문','복구와 거래 완료를 구분',[
        turn('카드 결제 중 통신이 끊겼는데 손님 폰에는 승인 문자가 왔어. 지금 인터넷은 돌아왔고 POS 상태는 아직 모르겠어. 한 번 더 긁고 나중에 하나 취소하면 돼? 지금 할 일을 순서대로 알려줘.',
          ['P01','P02','P04'],'먼저 주문번호·거래번호로 원결제 상태를 조회합니다. 문자나 연결 복구만으로 POS 완료·실패를 확정하거나 재결제하지 않습니다. 상태를 확인할 수 없으면 대기 건으로 남기고 당직 관리자에게 확인을 요청합니다.',
          forbidden=['먼저 재결제 후 중복 취소','연결이 복구됐으므로 이전 결제 실패'],
          checks=['미확인 상태를 보존하고 실제 결제 조회를 했다고 주장하지 않는다.'])],
        '연결 상태를 거래 상태로 오인하거나 중복 결제를 유도하는 오류'),
      case('O05','단일 질문','마감 순서 + 차액 예외 + 교대',[
        turn('퇴근 시간인데 환불 하나가 접수 상태고 현금도 2,500원 부족해. 다시 세어도 같고 점주는 연락이 안 돼. 일단 POS 마감하고 다음 사람에게 메신저만 보내면 끝일까?',
          ['C01','C02','C03','H01','H02'],
          'POS 마감과 완료 표시는 보류합니다. 환불은 완료 여부를 확인해야 하고, 재계산 후에도 남은 차액은 점주 확인이 필요합니다. 주문/사건번호·상태·다음 조치·기한·담당자를 기록해 다음 담당자에게 넘기고 업무 인수 확인까지 받아야 합니다.',
          forbidden=['접수를 환불 완료로 간주','메시지 발송으로 인계 완료','점주 부재이므로 차액 무시'],
          checks=['보류해야 할 일과 근무 종료 시 인계할 일을 모두 설명한다.'])],
        '절차 마지막 단계만 수행하거나 미해결 건을 인계 완료로 덮는 오류'),
      case('O06','단일 질문','날짜·채널·쿠폰 종류별 예외 적용',[
        turn('오늘이 2026년 10월 6일이야. 직접 결제 포장 손님은 회원 할인과 재오픈 쿠폰을 같이 쓰고 싶대. 배달앱 손님도 똑같이 해달라고 해. 둘 다 가능한가? 10월 9일에도 같아?',
          ['N01','N02','N03'],
          '10월 6일 직접 결제 포장 주문에는 재오픈 쿠폰과 회원 할인 중복이 가능합니다. 배달앱 주문은 예외 대상이 아니므로 불가합니다. 10월 9일에는 한시 예외가 끝나 상시 중복 불가 규칙을 적용합니다.',
          forbidden=['공지 날짜가 최신이면 모든 채널에 적용','예외를 10월 9일까지 연장','다른 행사 쿠폰도 중복 가능'],
          checks=['같은 질문 안의 두 주문과 미래 날짜를 각각 판정한다.'])],
        '최신 공지 한 줄만 선택해 예외의 기간·채널·종류 제한을 잃는 오류'),
      case('OD01','연속 대화','결제 경로 수정과 승인/완료 구분',[
        turn('오늘 매장에서 직접 결제한 18,000원 건이고 영수증 있어. POS 마감 전이야. 직원인 내가 환불하려면?',
          ['R02','R04'],'원거래와 이미 환불됐는지 확인한 뒤 직원이 원결제 수단으로 POS 환불할 수 있습니다.',
          slots=dict(channel='DIRECT',day='TODAY',amount=18000,status='UNVERIFIED')),
        turn('아, 직접 결제가 아니라 어제 배달앱 결제였어. 금액은 같아.',
          ['R01','R03','R04'],'금액은 18,000원이지만 이전 영업일 결제이므로 점주 승인이 필요합니다. 원거래 상태를 확인하고 승인 후 해당 배달앱에서 처리합니다.',
          slots=dict(channel='APP',day='PREVIOUS_DAY',amount=18000,status='UNVERIFIED'),
          forbidden=['18,000원이므로 승인 불필요','이전 POS 경로 유지']),
        turn('점주가 승인했어. 손님은 앱에서 이미 환불됐다고 하는데 한 번 더 눌러도 돼?',
          ['R01','R04'],'다시 누르지 말고 해당 앱의 원거래 환불 기록부터 확인합니다. 이미 완료라면 재환불하지 않습니다. 점주 승인이나 고객 발언 자체가 시스템의 완료 기록은 아닙니다.',
          slots=dict(channel='APP',day='PREVIOUS_DAY',amount=18000,approval='GRANTED',status='UNVERIFIED'),
          forbidden=['점주 승인=환불 완료','고객 말만으로 완료 확정'])],
        '수정된 거래 경로를 잊거나 승인 상태를 실제 처리 결과로 바꾸는 오류'),
      case('OD02','연속 대화','재고 정정 후 재계산과 중복 발주 방지',[
        turn('M컵 실물 180개, 파손 40개, 예약 30개이고 확정 입고 70개야. 컵을 더 몇 개 발주해?',
          ['I01','I02','I03'],'사용 가능 컵은 110개이므로 60개를 추가 발주합니다.',
          slots=dict(physical=180,damaged=40,reserved=30,confirmed_inbound=70),
          derives=['180 - 40 - 30 = 110','240 - 110 - 70 = 60']),
        turn('파손을 잘못 셌어. 40개가 아니라 20개야. 다른 숫자는 같고 아직 발주는 안 했어.',
          ['I01','I02','I03'],'사용 가능 컵은 130개로 바뀌므로 추가 발주량은 40개입니다.',
          slots=dict(physical=180,damaged=20,reserved=30,confirmed_inbound=70),
          derives=['180 - 20 - 30 = 130','240 - 130 - 70 = 40']),
        turn('방금 그 40개도 발주 확정받았어. 오늘은 평일 15시 10분이야. 이제 더 필요한 수량과 접수일, 배송일은?',
          ['I02','I03','I05'],'확정 입고가 기존 70개와 새 40개를 합쳐 110개이므로 추가 필요량은 0개입니다. 새 발주는 다음 영업일 접수이며 배송 완료일은 이 정보만으로 확정할 수 없습니다.',
          slots=dict(physical=180,damaged=20,reserved=30,confirmed_inbound=110),
          derives=['70 + 40 = 110','max(0,240 - 130 - 110) = 0'],
          forbidden=['기존 70개를 새 40개로 덮어쓰기','40개를 또 발주','다음 영업일 배송 완료 보장'])],
        '정정 숫자만 바꾸지 못하거나 같은 입고를 누락·중복 반영하는 오류',tier='ARITHMETIC_EXTENSION'),
      case('OD03','연속 대화','두 고객의 장애 상태 분리',[
        turn('A 주문은 카드 결제 중 끊겼고 조회해도 상태가 안 나와. 어떻게 남겨?',
          ['P01','P02','H01'],'A를 결제 상태 미확인 대기 건으로 남기고 당직 관리자에게 확인을 요청합니다. 주문번호·현재 상태·다음 조회 조치·기한·담당자를 기록합니다.',
          slots=dict(order_a='PAYMENT_UNVERIFIED')),
        turn('다른 손님의 B 주문은 관리자가 오프라인 현금을 허용했어. B는 어떻게 하고 A도 현금으로 다시 받으면 돼?',
          ['P01','P02','P03'],'B는 B 주문번호·금액·수단을 기록하고 현금을 받을 수 있습니다. B에 대한 허용은 A에 적용되지 않으며 A는 기존 카드 거래 확인 전 재결제하지 않습니다.',
          slots=dict(order_a='PAYMENT_UNVERIFIED',order_b='CASH_ALLOWED'),
          forbidden=['B 승인으로 A 현금 재결제 허용','A의 미확인 상태 해제']),
        turn('B 현금은 받았고 연결도 돌아왔어. 아까 첫 번째 건과 B 등록은 어떤 순서로 확인해?',
          ['P01','P02','P04'],'첫 번째인 A는 원거래 상태부터 조회하고 미확인이면 계속 대기 처리합니다. B는 같은 주문번호의 기존 거래가 있는지 확인한 뒤 수기 현금 거래를 등록합니다. 두 건 중 어느 것을 먼저 조회할지는 이 규칙으로 정해져 있지 않습니다.',
          slots=dict(order_a='PAYMENT_UNVERIFIED',order_b='CASH_RECEIVED_PENDING_REGISTER'),
          forbidden=['복구됐으니 A 실패 처리','B를 중복 확인 없이 등록','근거 없이 A/B 처리 우선순위 확정'])],
        '첫 번째/다른 손님 지시어와 주문별 승인 범위를 뒤섞는 오류'),
      case('OD04','연속 대화','도착과 체크 완료를 분리',[
        turn('나는 오픈 인증이 없고 인증자는 아직 안 왔어. 예정 시각인데 열쇠는 있어. 지금 열어?',
          ['S01','S02'],'영업 시작을 보류하고 당직 관리자에게 연락합니다. 열쇠만으로 인증 조건을 대신할 수 없습니다.',
          slots=dict(certified_present=False,checklist='INCOMPLETE')),
        turn('방금 인증자는 왔어. 체크리스트는 아직 덜 했고. 이제 열어도 돼?',
          ['S01','S04'],'인증자 현장 도착 조건은 충족했지만 체크리스트 완료 전에는 영업을 시작하지 않습니다.',
          slots=dict(certified_present=True,checklist='INCOMPLETE'),forbidden=['도착만으로 오픈 허용']),
        turn('체크리스트도 다 끝냈고 영업 시작했어. 내가 혼자 카운터 보는데 교대자가 10분 뒤 온대. 먼저 휴게 가도 돼?',
          ['S03','S04'],'교대자가 현장에 와서 인계받기 전에는 카운터를 비우지 않습니다. 도착 예정은 현장 인수 완료가 아닙니다.',
          slots=dict(certified_present=True,checklist='COMPLETE',counter_staff=1,replacement='NOT_ARRIVED'))],
        '조건 하나가 충족되면 나머지 조건까지 자동 충족됐다고 판단하는 오류'),
      case('OD05','연속 대화','부분 해결 후 남은 차단 조건 찾기',[
        turn('환불 하나가 처리 중이고 현금도 2,500원 부족해. 아직 다시 안 셌어. 마감하려면?',
          ['C01','C02','C03'],'환불 완료를 확인하고 현금을 재계산해야 합니다. 환불이나 차액이 미해결인 동안 POS 마감과 완료 표시는 보류합니다.',
          slots=dict(refund='PENDING',cash_difference=-2500,recount=False)),
        turn('다시 세니까 돈은 맞아. 환불은 아직 처리 중이야. 이제 POS 마감해?',
          ['C01','C03'],'차액 문제는 해결됐지만 환불이 처리 중이므로 POS 마감은 아직 보류합니다.',
          slots=dict(refund='PENDING',cash_difference=0,recount=True),forbidden=['현금이 맞으니 마감 허용']),
        turn('환불 완료 기록도 확인했고 현금은 다시 대조해서 맞아. 이제 남은 순서는?',
          ['C01','C02','C03'],'환불 완료와 현금 대조가 끝났으므로 POS 마감을 실행한 다음 점주에게 합계 보고를 보냅니다. 이전 차액이 남아 있는 것처럼 계속 차단하지 않습니다.',
          slots=dict(refund='COMPLETE',cash_difference=0,recount=True),
          forbidden=['이미 해결된 2,500원 차액 때문에 무기한 보류','점주 보고를 POS 마감보다 먼저 수행'])],
        '하나만 해결돼도 모두 완료로 보거나 해결된 문제를 계속 붙잡는 오류'),
      case('OD06','연속 대화','인계 대상 명확화와 읽음/수락 구분',[
        turn('A는 결제 상태 미확인, B는 환불 승인 대기야. 둘 다 다음 담당자에게 넘길 때 뭘 적어?',
          ['P02','H01','H03'],'A와 B를 별도로 기록합니다. 각각 주문번호·현재 상태·다음 조치·기한·담당자를 적습니다. A는 원결제 상태 확인, B는 환불 승인 확인이 다음 조치입니다.',
          slots=dict(order_a='PAYMENT_UNVERIFIED',order_b='REFUND_APPROVAL_PENDING')),
        turn('그 건은 메시지 읽었대. 인계 완료로 해도 돼?',
          ['H02','H03'],'A 결제 확인 건인지 B 환불 승인 건인지 먼저 확인합니다. 어느 건이든 읽음만으로는 인계 완료가 아닙니다.',action='CLARIFY',
          slots=dict(order_a='PAYMENT_UNVERIFIED',order_b='REFUND_APPROVAL_PENDING',referent='AMBIGUOUS'),
          checks=['대상 확인 질문과 읽음만으로 완료 아님을 함께 제시한다.']),
        turn('A 말이야. 담당자가 맡겠다고 확인했고 기한과 다음 조치도 전달했어. A 인계와 결제 상태, B는 각각 어떻게 남겨?',
          ['P02','H01','H02','H03'],'A는 지정 담당자의 인수 확인을 받아 인계 완료로 표시할 수 있지만, 결제 상태는 여전히 미확인입니다. B의 승인 대기·인계 상태는 A의 인수 확인으로 바뀌지 않습니다.',
          slots=dict(order_a='PAYMENT_UNVERIFIED',handoff_a='ACCEPTED',order_b='REFUND_APPROVAL_PENDING',handoff_b='UNCONFIRMED'),
          forbidden=['인계 완료=결제 완료','B도 함께 인계 완료'])],
        '업무 인계의 완료와 원래 사건의 해결을 혼동하는 오류'),
    ]
    return dict(schema_version='r_operations_challenge/v1',created_date='2026-10-06',
      status='DESIGNED_NOT_EXECUTED',truth_kind='SYNTHETIC_AGENT_AUTHORED_NOT_HUMAN_REVIEWED',
      facts=[dict(fact_id=i,category=c,assertion=a) for i,c,a in FACTS],cases=cases,
      conventions=[
        '모든 규칙은 평가용 가상 매장의 합성 정책이다. 실제 사업장 정책·법률·결제 사업자 규정에 대한 안내가 아니다.',
        '정적 정책 사실과 사용자 발화의 상황·숫자·관찰을 구분한다. 실시간 상태를 도구로 확인한 것처럼 답하지 않는다.',
        '사용자 발화가 이전 상황을 명시적으로 정정하면 그 항목만 바꾸고 다른 조건은 유지한다.',
        'expected_context는 채점용이며 모델 요청에 주입하지 않는다. 같은 세션에서 원래 발화만 순차 전송한다.',
        '사실 ID는 평가용 식별자다. 실제 승인 snapshot·fact_revision으로 매핑하기 전에는 제품 인용 ID가 아니다.',
        '불명확한 대상은 확인한다. 규칙에 없는 사건 간 우선순위나 배송일은 만들어내지 않는다.',
        '앞선 진단과 입력이 다르므로 점수를 직접 비교하지 않는다. 모든 사례는 아직 미실행이다.',
      ],grading=dict(
        dimensions=['필수 사실 조합','현재 상황과 정책 구분','예외·권한·기간·채널 적용','대상별 상태 유지','미해결/해결 상태 갱신','계산 정확성(해당 시)','출처와 주장 대응','금지 주장 부재'],
        full_pass='독립 의미 검토로 모든 예정 턴의 적용 차원을 충족해야 시나리오 완전 통과. 한 사실만 맞으면 부분 충족이다.',
        coverage='required_fact_ids별 올바른 적용을 따로 채점한다. 단순 인용 개수나 문자열 포함만으로 정답 처리하지 않는다.',
        failure_accounting='API 오류·미실행 후속 턴·판정 보류도 고정 분모에 남긴다.',
        reporting='운영 분야별, 단일/연속, 산술 포함 여부별로 나눠 보고한다.'),
      execution=dict(status='NOT_RUN',pass_rate=None,model_calls=0))


def validate(d):
    ids={f['fact_id'] for f in d['facts']}
    assert len(ids)==len(d['facts'])==26
    assert len({c['case_id'] for c in d['cases']})==len(d['cases'])==12
    assert sum(len(c['turns']) for c in d['cases'])==24
    for c in d['cases']:
        assert len({i for t in c['turns'] for i in t['required_fact_ids']})>=3
        for t in c['turns']:
            assert set(t['required_fact_ids'])<=ids
            assert len(set(t['required_fact_ids']))==len(t['required_fact_ids'])
            assert t['expected_action'] in ('ANSWER','CLARIFY','ESCALATE')
            assert t['reference_answer'] and t['question']
    assert 180-40-30==110 and 240-110-70==60 and min(110,150)==110
    assert 180-20-30==130 and 240-130-70==40 and max(0,240-130-110)==0


def write_html(d):
    e=html.escape
    facts={f['fact_id']:f for f in d['facts']}
    articles=[]
    for c in d['cases']:
        parts=[]
        for n,t in enumerate(c['turns'],1):
            evidence=''.join(f'<li><b>{i}</b> {e(facts[i]["assertion"])}</li>' for i in t['required_fact_ids'])
            parts.append(f'<section><h3>{n}턴 · {e(t["question"])}</h3><details><summary>기대 답변 · 근거 · 오답 조건</summary>'
              f'<p class="answer">{e(t["reference_answer"])}</p><p>기대 행동: {t["expected_action"]}</p><ul>{evidence}</ul>'
              +(f'<p><b>계산:</b> {e(" / ".join(t["derivations"]))}</p>' if t['derivations'] else '')
              +(f'<p><b>조건·상태:</b> {e(json.dumps(t["expected_context"],ensure_ascii=False))}</p>' if t['expected_context'] else '')
              +(f'<p class="bad"><b>오답 예:</b> {e(" / ".join(t["forbidden_claims"]))}</p>' if t['forbidden_claims'] else '')
              +(f'<p><b>추가 판정:</b> {e(" / ".join(t["grading_checks"]))}</p>' if t['grading_checks'] else '')+'</details></section>')
        articles.append(f'<article><small>{c["case_id"]} · {e(c["kind"])} · 미실행</small><h2>{e(c["title"])}</h2>'
          +''.join(parts)+f'<p class="target"><b>잡아낼 오류:</b> {e(c["failure_to_detect"])}</p></article>')
    rows=''.join(f'<tr><td>{i}</td><td>{e(c)}</td><td>{e(a)}</td></tr>' for i,c,a in FACTS)
    doc='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AskBuddy 매장 운영 고난도 질문</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f4f6f9;color:#22344b;font-family:'Malgun Gothic',sans-serif}main{max-width:1060px;margin:auto;padding:40px 24px}header{background:#173e48;color:white;border-radius:18px;padding:30px}h1{font-size:32px;line-height:1.5}h2{font-size:22px}h3{font-size:17px;line-height:1.8}p,li{line-height:1.85}article{background:white;border:1px solid #dce3eb;border-radius:14px;margin:22px 0;padding:26px}small{color:#5b7187}section{border-top:1px solid #e3e8ef;padding-bottom:14px}details{background:#f2f6fa;border-radius:9px;padding:16px}summary{cursor:pointer;color:#22617b}.answer{background:#e1f1eb;padding:15px;border-radius:8px}.bad{color:#933a30}.target{border-left:3px solid #bf8b44;padding-left:14px}.note{background:#fff1d4;padding:20px;border-radius:12px;margin:22px 0}table{width:100%;border-collapse:collapse;background:white}td,th{padding:10px;border-bottom:1px solid #e0e6ee;text-align:left;line-height:1.7}button{border:0;border-radius:8px;background:#22617b;color:white;padding:11px 17px;font:inherit;margin:6px 8px 6px 0;cursor:pointer}footer{color:#5c7087;font-size:13px;margin-top:25px}@media print{body{background:white}header{background:#eee;color:#173e48}button{display:none}article{break-inside:avoid}main{padding:0}}</style>
<main><header><div>ASKBUDDY / OPERATIONS CHALLENGE / 2026.10.06</div><h1>레시피 없이도 어려운 질문<br>여러 규칙과 바뀌는 상황을 함께 판단하기</h1><p>환불·근무·발주·결제 장애·마감·인수인계·공지 적용<br>합성 정책 사실 26개 / 단일 질문 6개 + 3턴 대화 6개 / 총 24개 발화</p></header>
<div class="note"><b>아직 실행하지 않은 평가 문제집입니다.</b><br>모든 정책은 가상 매장을 위한 합성 규칙입니다. 실제 매장 운영 지침이나 법률·결제 사업자 규정이 아닙니다. 실제 API·모델을 호출하지 않았으며 성능 점수는 없습니다.</div>
<p>질문의 길이보다 조건의 충돌·예외·정정·업무 간 의존성이 난도를 결정합니다. 각 문제는 필요한 사실과 실제 상황을 함께 적용해야 풀 수 있습니다. 정답과 근거는 접어 두었습니다.</p>
<button onclick="document.querySelectorAll('details').forEach(d=>d.open=true)">정답 모두 열기</button><button onclick="document.querySelectorAll('details').forEach(d=>d.open=false)">정답 모두 접기</button>
__CASES__
<h2>기준 정책 사실 26개</h2><table><tr><th>ID</th><th>분야</th><th>합성 정책</th></tr>__FACTS__</table>
<h2>채점 원칙</h2><p>정답 한 문장과의 문자열 일치 대신 필수 사실·상황·조건의 적용을 검토합니다. “어떻게 해야 하는가”를 설명하는 답변과 “실제로 처리됐다”는 상태 주장을 구분합니다. 여러 건의 상태는 따로 유지하고, 정정된 항목만 바꿔야 합니다. 모든 예정 턴을 통과해야 해당 대화 시나리오가 완전 통과입니다.</p>
<footer>독립 사람 검토 전 합성 문제입니다. 조건·상태 정답은 채점 전용이며 모델 입력에 주입하면 안 됩니다. 제품 코드는 변경하지 않았습니다.<br>입력·정답·채점 규칙: operations-challenge.json · 모든 사례 미실행 · 이 HTML은 파일 자체로 공유할 수 있습니다.</footer></main></html>'''
    (OUT/'AskBuddy-operations-challenge.html').write_text(doc.replace('__CASES__',''.join(articles)).replace('__FACTS__',rows),encoding='utf-8')


if __name__=='__main__':
    d=pack()
    validate(d)
    d['content_sha256']=hashlib.sha256(json.dumps(d,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'operations-challenge.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write_html(d)
    print('Validated: 26 facts, 12 cases, 24 turns. Created operations JSON/HTML. NOT RUN.')
