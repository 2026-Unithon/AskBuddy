# W 분류·관계 비용 계측

2026-09-16 · 요청: 남은 C0 작업 중 분류/관계 비용 계측을 먼저 구현.

## 구현과 인수 범위

- `categories/classifier.py`의 재분류 배치는 CLASSIFY receipt 한 행으로 기록한다.
  운영 재분류의 operation/logical key는 서버의 reclass job ID로 만든다.
  이 ID는 ingest job ID와 다른 테이블이므로 `UsageContext.job_id`에 넣지 않는다.
- 재분류 worker가 전체 작업 동안 빌리던 DB 연결을 `ShortSession`으로 교체했다.
  업무 상태/카드 수정의 기존 version/snapshot 조건은 유지하고 모델 호출 중 연결을 반환한다.
- `learn/knowledge_loop.py`의 관계 모델은 RELATION으로 기록하고 선행 후보 검색 임베딩은
  기존 `recorded_embeddings`로 호출한다. 두 receipt는 같은 분석 operation에 속하며 서로 다른 논리 키를 쓴다.
  공급자 진입점은 기존 `reg/embeddings.py::embed_texts` 하나를 유지한다.
- 기존 제품 호출을 바꾸지 않고 `build_knowledge_plan`이 trusted store scope로
  OPERATING/PRODUCT context와 DbUsageSink를 만든다. 평가/개발용 호출은 명시 context/sink로 목적을 보존한다.
  타 매장 context, 잘못된 stage, 절반만 주입한 context/sink는 거절한다.
- 공통 `usage/gemini.py`는 기존 recorder/repository/rate adapter를 사용한다.
  호출 전 STARTED를 커밋하고 usage를 JSON 검증 전에 관측한다.
  파싱 실패/timeout/cancellation은 FAILED이며 받은 token은 보존한다.
  시작 원장 실패는 유료 호출 전에 종료하고 RELATION 비즈니스 폴백으로 숨기지 않는다.
- 공급자 token의 실제 0, 누락, 추가 과금 단위를 구분한다. cached/thought와 원형 usage를 남기되
  과금 포함 관계가 미확정이면 PARTIAL이다. 응답 모델/요청 ID, 입력 bytes, prompt/config/schema hash를 기록한다.
  질문/답변/카드 본문은 usage 원장에 복제하지 않는다.
- SDK 재시도는 1시도, transport timeout은 30초로 제한했다.
  새 업무/명시 재시도 context는 별도 receipt이며 원장 확정 실패를 공급자 재호출로 복구하지 않는다.
  클라이언트 정리 오류는 이미 받은 결과나 원래 공급자 오류를 덮지 않는다.
- mock/빈 분류 배치는 공급자와 receipt를 만들지 않는다. 엄격히 동일한 답변은 RELATION 모델을 호출하지 않는다.
  후보 검색 EMBED가 실제 실행됐다면 그 비용은 별도로 남는다.

## 검증

- 구현 전 새 테스트: 15 실패/1 통과(4 subtest 포함). 기존 함수에 비용 주입/검사가 없는 것을 확인했다.
- 최종 W 합성 테스트: **16 tests / 4 subtests 통과**.
  정상 배치 귀속/단일 receipt, 실제 0/결측/추가 단위, parsing 실패, 시작/확정 저장 실패,
  timeout/cancellation, mock/빈 배치, 잘못된 stage/매장, 후보 EMBED operation 상속,
  worker 연결 수명, 시작 기록 선행, 클라이언트 정리 오류, 시도 번호 분리를 포함한다.
- 전체 회귀: **450 tests / 84 subtests 통과**.
- 공식 `postgres:15-alpine` 일회용 DB, 실제 PostgreSQL **15.19**:
  기존 MC0 원장 **14/14**, 새 W 경계 **7/7** 통과.
  새 검증은 실제 DbUsageSink/start/finalize와 제품 분류/관계 함수를 사용한다.
  독립 관측 연결에서 STARTED 선커밋, 1개 풀 연결 반환, CLASSIFY 귀속/금액 null,
  RELATION 기본 제품 sink의 JSON 오류 usage 보존, 타 매장에 W 비용이 기록되지 않음을 확인했다.
- 매장 격리 AST: categories 6개·knowledge_loop 1개·새 Gemini helper 1개, 위반 0건.
  변경한 기존 DB 쿼리는 없다. 새 SQL/migration/라우터가 없어 새 HTTP 401/403/404/422 인수는 추가하지 않았다.

재현 파일:

```text
api/.venv/bin/python -m pytest api/tests/test_w_classify_relation_usage.py -q
api/.venv/bin/python -m pytest api/tests -q
api/.venv/bin/python .claude/skills/store-isolation-check/check_store_id.py api/app/categories
api/.venv/bin/python .claude/skills/store-isolation-check/check_store_id.py api/app/learn/knowledge_loop.py
api/.venv/bin/python .claude/skills/store-isolation-check/check_store_id.py api/app/usage/gemini.py
```

DB 스크립트 `verify_w_classify_relation_usage.py`는 `.env`를 사용하지 않고
기존 원장 verifier의 `127.0.0.1:55439/usage_verify` 테스트 DSN을 사용한다.
새 일회용 PG15에서 `verify_r_answer_usage.py`로 MC0를 준비한 뒤 실행한다.
공급자는 fake이며 원본 자료/운영 DB/유료 모델을 사용하지 않았다.
이번에 생성한 컨테이너 `askbuddy-w-classify-20260916-b751`만 종료/제거하고 기존 Supabase 컨테이너는 보존한다.

## 남은 것

CLASSIFY/RELATION **호출 계측은 완료**다. 실제 모델 의미 정확성/가격·전체 CP-00B/C/D21 PASS는 아니다.
Storage byte-time/전송·매장 귀속, 다중 source/card 기여 링크, 요율/환율·전체 단계 비용 대조,
CP-05 통합은 그대로 남았다.

현재 관계 분석은 owner_answers 저장 전에 실행되므로 기본 context에는 서버 분석 operation이 있고
owner_answer_id/실제 question_id 연결은 없다. 이를 임의 source/job에 붙이지 않았다.
R의 원문 저장/outbox와 W ApplyOwnerAnswer를 연결할 때 이 operation과 답변 이력을 연결해야 한다.
이번 작업은 그 제품 순서/승인 정책을 변경하지 않는다.

업무 worker 영속 복구, 전체 pgvector 저장/발행·채팅 snapshot 왕복,
프론트/E2E/운영 배포는 이번 인수 범위가 아니다. 기존 review는 수정하지 않았다.
