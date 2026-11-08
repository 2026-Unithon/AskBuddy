데모 사이트 전체 직원용: `bash deploy/demo-gemini.sh enable`. 모든 매장의 승인된
공개판을 읽되 매장별로 별도의 승인 해시를 검증한다. 직원 가입 순서나 계정 ID는
대상 조건이 아니다. 빈 매장은 기존 점주 확인 경로를 사용한다. 새 매장의 첫 공개나
공개판 변경 후에는 `bash deploy/demo-gemini.sh refresh`로 승인 범위를 갱신한다.
데모 설정은 7일간 유효하며 `bash deploy/demo-gemini.sh disable`로 중단할 수 있다.
11월 8일 요청은 지정된 데모 EC2에 이 변경을 배포할 때 한 번만 적용한다.
완료 표시가 남으므로 이후 배포가 운영자의 중단을 취소하지 않는다.

단일 매장 9 실험도 별도로 지원한다. 다른 매장은 기존 채팅 경로를 사용한다.
Gemini는 검색이 성공한 뒤에도 기본 판정으로 답을 못 하는 질문에만 쓰인다.
임베딩 장애를 복구하지 않는다. 모델 제안·검증에는 실제 운영 요금이 발생한다.

배포 후 EC2의 ubuntu 사용자로 `cd /home/ubuntu/askbuddy` 후
`bash deploy/store9-gemini.sh enable`을 실행한다. 운영 키를 출력하지 않는다.
현재 승인 공개판·실행 이미지·모델에 묶인 24시간 설정을 만든 뒤 API만 재생성한다.
이 명령은 모델을 시험 호출하지 않는다. flag가 이미 켜져 있으면 자동 갱신하지 않는다.
expiry 또는 공개판 변경 뒤에는 기본 처리로 돌아간다. 지속 사용하려면 재검토한다.

실제 확인은 매장 9 직원의 재질문 유발 입력 1건으로 한다.
`ai_usage_attempts`의 PRODUCT/real/ANSWER 성공과 같은 operation의
`r_answer_receipts.execution_metadata.general_semantics` 결과를 함께 확인한다.
`PILOT_BASELINE`은 Gemini 결과를 채택하지 않고 기존 판정으로 응답했다는 뜻이다.
원복: `bash deploy/store9-gemini.sh disable`. 상태: `bash deploy/store9-gemini.sh status`.
