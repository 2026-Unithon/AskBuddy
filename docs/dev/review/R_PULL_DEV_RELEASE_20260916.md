# R/W pull 및 dev/release 분리 반영

2026-09-16. 원격 main의 `c73549a` 이후 4개 커밋을 받아 `4212fec`로 fast-forward했다. 기존 미커밋 R 작업은 include-untracked stash로 보존하고 적용했다. stash는 안전 사본으로 남겼다. 새 커밋·푸시·운영 배포는 하지 않았다.

## 통합 판단

- R 계획 1개와 검증 기록 8개를 `docs/dev/plan`, `docs/dev/review`로 옮겼다. 과거 검증 내용은 바꾸지 않았다. 정본/TODO/README의 원격 이동은 Git rename 통합으로 로컬 내용을 보존했다.
- 충돌 3개를 해결했다. TODO는 W와 R 기록을 모두 유지했다. 하네스는 W 임베딩·채점 migration 검증과 R 문맥 검증을 모두 실행한다.
- answer_metrics는 W의 모든 반복 필수 악화 검출과 R의 미판정/필수 목록 누락 차단을 보존했다. W가 추가한 `observed_must_have_regressions` 출력 이름은 R의 `must_have_regression_ids`와 같은 목록으로 제공한다. 누락 manifest를 빈 목록으로 자동 승인하지 않는다.
- 원격 W의 `20260917100000_w_score_undetermined.sql`과 로컬 R의 migration 번호가 겹쳤다. 운영 적용 전이며 격리 DB에서만 검증한 R 파일을 `20260917103000_m3_question_context.sql`로 옮기고 직접 참조 스크립트도 고쳤다. SQL 본문은 바꾸지 않았다. migration 번호 중복을 차단하는 회귀 검사를 추가했다.
- release README의 정본/TODO 링크 2개를 새 dev 경로로 고쳤다. release 계획과 완료 체크는 변경하지 않았다.
- 현재 R 개발 계획에 dev 핵심 구현/평가, release 실제 연동/기기 인수/사용성, W 공동 인수를 나눠 기록했다. 분류 이동을 완료 선언으로 사용하지 않는다. 다음 dev 독립 항목은 R0 v2 평가 결과 수집·보고 연결이다.

## 검증

단위 회귀 **515 passed / 106 subtests passed**. 기존 Starlette/AnyIO deprecation 경고 1개. 첫 실행에서 W가 추가한 async 테스트 5개가 pytest-asyncio 미설치 때문에 실행되지 않았고, Git 제외 `api/tmp/test-deps`에 pytest-asyncio 1.4.0을 설치·명시 활성화한 뒤 전부 통과했다. 제품 코드를 바꿔 테스트를 우회하지 않았다.

실제 PostgreSQL 17.11 신규 재구축 **26 migrations**와 **198 PASS 체크**가 통과했다. 합계는 기존 R 188 + W 임베딩 6 + W 채점 migration 4이며 고유 사용자 시나리오 수는 아니다. 원격 ShortSession 변경과 함께 v1 회귀·v2 실제 DB/API도 확인했다. 합성 provider를 썼으며 실제 모델 품질·원가 인수는 아니다.

재현 환경: `PYTHONPATH=api/tmp/test-deps`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTEST_PLUGINS=pytest_asyncio.plugin`. 실행은 `verify_r_handoff.ps1 -IncludeSchemaRebuild -IncludeUnitTests`. 일회용 Docker/DB는 종료·정리됐다. 프런트 코드는 이번 통합에서 새로 변경하지 않았으며 이전 브라우저/빌드 검증을 이번 신규 실행으로 표시하지 않는다. `git diff --check` 및 미해결 Git 충돌 없음 확인.

R 전체 개발, 실제 W 발행 종단, release 완료를 의미하지 않는다. 기존 R 플래그 기본 OFF를 유지한다.
