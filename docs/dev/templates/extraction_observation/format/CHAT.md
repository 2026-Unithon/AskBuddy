## name

대화 — 카카오톡 내보내기·캡처
## step_examples

대화를 처음부터 끝까지 봄 / 날짜·보낸 사람 구분 / 정정 메시지 추적 / 사실로 정리 / 재검증
## why_example

"다음 날 메시지에서 앞서 말한 시간을 바꿈"
## meta_amount

"messages": 메시지 수, "date_range": "첫 날짜 ~ 마지막 날짜",
## locator

{"kind": "DATE", "date": "YYYY-MM-DD", "line": 줄 번호 또는 null}
## rules

- 나중 메시지가 앞의 값을 바꾸면 나중 값을 사실로 적고, 바뀐 이력을 original_assertion에 남기세요.
- 잡담·인사는 적지 마세요.
## checks

- 나중 메시지가 앞의 값을 바꾼 곳은 모두 어디인가?
- 누가 말했는지가 중요한 사실(점주 지시 등)을 구분했는가?
## input_note

[첨부] 카카오톡 대화 내보내기 파일(txt) 또는 대화 캡처를 이 메시지에 첨부했습니다.
