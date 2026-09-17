# R3 재정렬 계측·장애 처리 검증

2026-09-16. 이전 구현 범위는 `R_RUNTIME_IMPLEMENTATION_20260916.md`를 따른다. 이번 항목은 R3 선택형 reranker의 실제 SDK 어댑터와 원가 원장 사이 장애 처리다. R 전체 완료나 실제 모델 검색 품질 향상 판정은 아니다.

## 계획과 구현

- C0의 호출 전 원장 기록·누락 비용 UNKNOWN 원칙, R3의 후보 밖 ID 차단, 동일 요청 기한을 유지한다. W 변경은 필요하지 않다.
- NullSink와 잘못 복사된 UsageContext를 거절한다. 원장 시작의 일반 예외도 UsageWriteError로 통일해 SDK 호출 전에 차단한다.
- JSON 오류뿐 아니라 누락·중복·후보 밖 ID도 원가 기록 구간 안에서 검증한다. 오류 응답에서 관측한 토큰은 보존하고 호출 상태는 FAILED로 남긴다. 원래 후보 순서로 복귀한다.
- 재정렬에 주어진 남은 시간(최대 1초)에서 원장 확정과 SDK 정리 시간을 예약한다. 원장 시작/확정과 SDK close에 각각 제한을 둔다. 새 요청 기한을 부여하지 않는다. asyncio 취소에 협조하는 비동기 작업을 전제로 하며 운영 지연 보장 실측은 별도다.
- 원장 확정만 지연되면 유효한 순위 결과는 유지하고 원장은 STARTED, 비용은 미확정으로 남긴다. 이를 무료 호출로 세거나 SDK를 다시 호출하지 않는다.
- 호출 취소는 상위 호출자에게 전파한다. 재정렬을 켠 v2 API에서 호출 전 계측 실패는 USAGE_UNAVAILABLE 503이며 점주 문의를 만들지 않는다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| API 단위 회귀 | 434 passed, 95 subtests passed |
| 격리 PostgreSQL 17.11 신규 스키마 | migration 25개 적용 성공 |
| 실제 DB/API 전체 하네스 | 172 PASS 체크 |
| 위 결과 중 새 RERANK 계측 검증 | 13개: 호출 전 commit/연결 반환, 재시도 제한, 토큰·hash, 중복 차단, 오류 출력, timeout·취소, 시작 실패, 확정/정리 지연 |
| 위 결과 중 v2 API 검증 | 41개: 재정렬 APPLIED 답변 저장 및 계측 실패의 503/문의 미생성 포함 |
| 매장 격리 정적 검사 | reranker.py 1개 파일, 위반 0 |
| git diff --check | 통과 |

172는 하네스 PASS 체크 합계(50+31+13+16+41+21)이며 고유 사용자 시나리오 수가 아니다. 단위 회귀 후 HTTP 인수 사례를 추가했고 DB/API 하네스를 다시 실행했다. 의도적으로 원장 확정을 지연시키는 사례의 기록 확정 실패 로그는 예상 결과다. 단위 실행의 기존 Starlette/AnyIO deprecation 경고 1개는 남아 있다.

실행: `api/scripts/verify_r_handoff.ps1 -IncludeSchemaRebuild -IncludeUnitTests` 및 HTTP 사례 추가 후 `-IncludeSchemaRebuild`. 격리 Docker DB를 생성·정리했다. 운영 DB와 실제 Gemini 호출은 사용하지 않았다. Google SDK Client 응답만 합성으로 대체하고 실제 reranker 어댑터, 원가 recorder/repository, PostgreSQL 및 v2 API를 검증했다.

## 남은 범위

선택형 reranker 기본 OFF는 유지한다. 실제 모델의 순위 품질·비용·지연 및 승격 기준은 실제 평가로 확인해야 한다. 이번 작업에는 새 migration이나 화면 변경이 없으며 브라우저 검증을 새로 수행하지 않았다. 정책 후속 확인·알림/FAQ·실제 평가·DB UI E2E·W 공동 발행 연결 등 이전 기록의 다른 미완료 항목은 그대로 남는다.
