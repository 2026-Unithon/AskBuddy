## name

공지·일정(이번 주 공지·행사·근무 변경 등)
## intro

기간이 있는 알림이 담긴 자료입니다. 공지 안에 레시피·규칙이 **바뀌는** 내용이 있으면 그것도 사실로 적되 attribute에 무엇이 바뀌었는지 드러나게 적으세요.
## subject_examples

공지 제목 또는 바뀌는 대상(메뉴·규칙 이름)
## attributes

내용 · 대상 · 시작 · 끝 · 변경 전 · 변경 후
## ext

{"valid_from": "YYYY-MM-DD 또는 null", "valid_until": "YYYY-MM-DD 또는 null", "date_original": "원문의 날짜 표현"}
## rules

- 날짜는 원문 그대로 ext.date_original에 남기고, 해석한 날짜를 valid_from/valid_until에 적으세요. 해석할 수 없으면 null로 두고 meta.unreadable에 적으세요.
- "아메리카노 물 225→250ml"처럼 지식이 바뀌는 문장은 변경 후 값을 value로, 변경 전 값은 attribute "변경 전" 사실로 따로 적으세요.
## checks

1. 기간이 없는 공지는 어느 것인가?
2. 지식이 바뀌는 문장(레시피·규칙 변경)을 모두 따로 적었는가?
