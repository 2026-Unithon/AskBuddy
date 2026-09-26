# PR #22 R reranker CI timeout 검토

## 기준과 관찰

- 기준: PR #22의 `3a3828a2c8d4973c59baebd0def748875a83f243`.
- 작업 브랜치: `codex/r-reranker-timeout-pr22`.
- 실패 기록: [R validation 36251188040](https://github.com/2026-Unithon/AskBuddy/actions/runs/36251188040).
- CI는 `verify_r_reranker_usage.py`의 `finalize-hangs` 사례에서 실패했다. 정리 작업에 도달하기 전에 `_BoundedSink.start`의 DB 저장이 200ms 기한을 넘겨 `UsageWriteError`가 발생했다.
- DB 지연의 세부 원인(실행 환경 부하, DB 대기 등)은 로그만으로 확정하지 못했다. PR 원본의 로컬 PostgreSQL 전체 회귀는 통과하여 자연 발생 실패는 재현하지 못했다.
- PR #22의 W `run_tag` 변경이나 unique 충돌이 이 CI 오류의 원인이라는 증거는 없다.

## 수정

운영 timeout을 늘리지 않고 DB 저장 계약 검증과 단계별 기한 검증을 분리했다.

1. `verify_r_reranker_usage.py`는 실제 `_model` adapter와 `DbUsageSink`를 사용한다. SDK 응답만 합성으로 대체하며, adapter 호출 기한은 검증용 30초, 시작/정리 기한은 검증용 5초로 둔다. 공통 DB repository 자체의 제한은 변경하지 않는다.
2. 실제 DB에서 호출 전 commit·연결 반환·중복 차단·사용량 귀속·잘못된 출력·공급자 timeout·취소 기록을 계속 확인한다. finalize 실패 뒤 STARTED/UNKNOWN 유지와 SDK 종료 실패 뒤 성공 기록도 검사한다.
3. 250ms 지연 후 실제 시작 기록을 저장하는 사례를 추가했다. DB 계약 검증이 운영 200ms 지연 인수와 섞이지 않는지 확인한다.
4. `test_r_reranker_lifecycle.py`에 9개 테스트를 추가했다. 실제 `rerank`/`_model` 경로에 제어 가능한 sink/SDK를 넣고 운영의 총 1초/정리 200ms 계산을 그대로 사용한다. 시작·모델·finalize·SDK 종료의 멈춤, 시작 실패, 호출자 취소, 잘못된 출력을 검증한다. 무한 대기를 막는 외부 테스트 기한은 5초다.
5. 취소 테스트는 진입 이벤트를 확인한 뒤 취소하고 task 종료까지 회수한다. DB 속도에 기대어 특정 시점에 취소하지 않는다.

운영 `api/app/` 코드, W 변경, migration, 공개 인터페이스는 바꾸지 않았다. 검증 분리는 운영 DB가 200ms를 넘겨도 성공하도록 만드는 변경이 아니다. 운영에서 최초 기록 기한을 넘으면 기존처럼 공급자 호출을 차단한다.

## 검증

- 기존 reranker + 새 단계별 테스트: 16 passed.
- 전체 단위·계약 회귀: 959 passed, 4 xfailed, 119 subtests passed. 기존 Starlette/AnyIO deprecation warning 1건.
- `verify_r_handoff.ps1 -IncludeSchemaRebuild`: 일회용 PostgreSQL 17, 전체 30개 migration 및 W/R DB 회귀 통과. RERANK 원가 검증 14개 포함.
- 로컬 검증은 외부 유료 모델을 호출하지 않았다. 검증용 컨테이너는 실행 후 정리했다.
- 원격 CI는 이 수정이 push된 뒤 별도로 확인해야 한다. 로컬 통과를 원격 통과로 표시하지 않는다.

## 남는 범위

실제 운영 DB의 지연 분포와 200ms 제한의 적정성은 별도 관측 대상이다. 이번 수정으로 운영 지연 목표를 충족했다고 주장하지 않는다. PR #22의 W 구현을 유지한 상태의 검증 보완이며, W/R 공개 snapshot 및 activate/finish 공동 연결 인수를 대신하지 않는다.
