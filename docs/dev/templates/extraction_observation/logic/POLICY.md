## name

운영 규칙·응대(환불·할인·응대·금지 사항 등)
## intro

해도 되는 것·안 되는 것과 그 조건이 담긴 자료입니다.
## subject_examples

규칙 이름(예: 환불, 쿠폰 사용, 외부 음식 반입)
## attributes

허용 · 금지 · 대상 · 한도 · 처리 방법 · 안내 문구 · 근거
## ext

{"scope": "CUSTOMER / STAFF / ALL / null"}
## rules

- 금지는 polarity NEGATE로 적으세요("~하지 않는다", "~불가", "~금지").
- 예외("단, 당일은 가능")는 반드시 exceptions에 적고, 예외를 별도 허용 사실로 바꾸지 마세요.
- 손님에게 그대로 말해야 하는 문장은 attribute "안내 문구"로 원문 그대로 적으세요.
## checks

1. 금지·불가 문장 중 polarity가 AFFIRM으로 잘못 적힌 것은 없는가?
2. "단", "다만", "예외"가 붙은 규칙의 예외가 모두 exceptions에 들어갔는가?
