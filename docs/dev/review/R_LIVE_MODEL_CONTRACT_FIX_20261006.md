# R 실제 Gemini 실패 기반 계약 보완 — 2026-10-06

## 문제와 변경

이전 실제 Gemini 단회 진단은 합성 비레시피 질문 24턴 모두 최종 API 오류였다. JSON 잘림 6건, 응답 schema 오류 5건, 필수 해석 근거 또는 문맥 충돌 13건이었다. 이전 결과와 점수는 덮어쓰지 않았다.

- `general_wire.py`: 모델용 schema에서 서버가 소유하는 context ID와 정책 action을 제외했다. CLARIFY 제안을 파싱할 때 서버가 ID를 발급하고 기존 공개 AnswerPlan의 필수 필드·상태 검사에 넘긴다. 모델이 보낸 임의 ID는 거절한다. 블록을 선택한 CLARIFY나 임의 선택지는 여전히 실패한다.
- `v2_router.py` / `general_semantics.py`: 일반 의미 모델과 별도 검증에 실제 사용자 선택 문맥만 전달한다. 현재 질문을 처리하며 planner가 추정한 단일 대상을 확정값으로 취급하지 않는다. 사용자가 실제로 확정한 대상·온도·크기 충돌 검사는 유지한다. 복합 질문의 part와 전체 참조 합집합 검사도 유지한다.
- 모델 schema 설명·프롬프트에 entity ID와 표시명, 필수 entity/predicate 인용, temperature/size 규격, RAW-only 형식, 미지원 계산의 ESCALATE 계약을 명시했다. 누락 필드를 답안에 맞춰 자동 보정하거나 잘린 JSON을 수리하지 않는다.
- `general_provider.py`: Gemini의 `response_json_schema`에 모델용 schema를 실제로 전달한다. release에 고정되는 thinking_level은 기본 low다. 생성 토큰 상한과 예산 강제는 유지한다. countTokens가 generation config를 받지 않는 SDK 제약을 고려해 프롬프트+schema와 여유분으로 사전 검사하고 실제 사용량도 다시 검사한다. 구조화 출력은 의미 정확성 보장이 아니다.
- 공급자 종료 사유가 STOP이 아니면 완성돼 보이는 JSON도 거절한다. 잘림·안전 차단도 사용량을 기록하고 자동 유료 재시도는 하지 않는다.
- 모델·코드·승인판에 묶인 기본 OFF release 게이트를 유지했다. 새 wire 코드와 프롬프트도 source hash에 포함된다. 기존 인수 파일을 그대로 재사용할 수 없다.

## 검증

- 실제 실패 응답 24개를 `api/tests/fixtures/r_general_live_20261006.json`에 고정했다. 합성 정책과 공급자 원문 출력만 포함하며 자격증명·응답 헤더·불투명한 thought signature는 제외했다.
- 원래 실패 응답이 수정 후 무조건 ANSWER로 통과하지 않는지 검사했다. 사람이 계약 필드만 교정한 별도 복사본으로 다중 RAW 참조·조건·출처 렌더 경로를 검증했으며 이를 실제 모델 정답으로 집계하지 않았다.
- 모델이 context ID 없이 CLARIFY 제안 → 서버 ID 발급, 임의 ID 거절, 불완전/조작 선택지 거절, 실제 확정 문맥 충돌, 두 모델 단계의 확정 슬롯 일치, 원본 응답 불변을 검증했다.
- 실제 Google SDK와 HTTP MockTransport로 구조화 schema·low 설정이 요청에 실리는지 확인했다. STOP/MAX_TOKENS/SAFETY/종료 사유 누락, 실패 사용량 정산과 생성 1회 제한을 검증했다. 실제 Google 서비스 응답 형식 인수는 재평가 대상이다.
- Python 전체: **1,770 passed, 4 xfailed, 131 subtests passed**. 기존 Starlette/AnyIO deprecation warning 1개.
- 매장 격리 AST: 변경 `api/app/learn` 폴더 위반 0건.
- 실제 격리 PostgreSQL 17에 migration 41개를 재구축하고 R API/DB 및 W/R 소비 계약 회귀를 통과했다. 특히 제목을 언급해 planner의 대상 추정이 생긴 질문 → 일반 의미 ANSWER → 저장·인용 → 다음 사용자 질문에 이전 원문 전달 → 동일 요청 무재호출·잘못된 참조 rollback을 확인했다. 공급자 응답만 합성이다.
- 초기 로컬 테스트의 Windows 임시 경로·cp949 인코딩 오류는 작업 폴더 내 임시 경로와 UTF-8 실행으로 해결했다. DB 검증 하네스의 고정 포트 55439를 WSL 평가용 55440으로 일관되게 맞춘 뒤 전체 검증을 다시 통과했다.
- 로그: `api/tmp/r-general-full-06.log`, `api/tmp/r-general-pg17-02.log`(Git 제외). 일회용 UUID 데이터베이스는 검사 종료 시 삭제했다.

## 남은 검증

이번 보완에는 **추가 유료 호출이 없으며 수정 후 정확도·지연·비용 개선 수치는 아직 없다.** 이전 유료 단회 결과의 $0.34791525를 이번 변경의 성능으로 재사용하지 않는다. 같은 고정 질문·동일 근거로 실제 Gemini를 재평가한 뒤, 성공한 대화에서 후속 맥락과 필요한 재질문을 검토해야 한다.

서비스의 5초/모델 3초 제한, W 실제 출력과 실제 임베딩의 종단 품질, 자유형 사건 A/B 명확화, RAW 숫자의 임의 계산은 이번 변경으로 완료되지 않는다. 본 변경은 운영 활성화나 공개 API/W snapshot 계약 변경을 포함하지 않는다.

설정 참고: [Gemini 구조화 출력](https://ai.google.dev/gemini-api/docs/structured-output), [추론 강도·출력 한도](https://ai.google.dev/gemini-api/docs/thinking). low는 추론량 조절이며 특정 토큰 수나 응답 시간의 보장이 아니다.
