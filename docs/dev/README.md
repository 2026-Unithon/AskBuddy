# docs 구조

W 개발의 문서 기준은 `docs/dev/`다. 현재 작업에서는 이 폴더의 정본·계획·검증 기록만 읽는다.
`docs/release/`는 별도 릴리스 작업 영역이며, 명시적인 요청 없이 읽거나 수정하지 않는다.
폴더 이동에 따른 경로만 보정하며 과거 review의 관찰·판정은 변경하지 않는다.

| 위치 | 담는 것 | 갱신 주기 |
|---|---|---|
| `docs/dev/` | 제품·데이터·API 명세와 **전체 계획**. 정본이다 | 계속 갱신 |
| `docs/dev/plan/` | 전체 계획에서 떼어낸 **구현 계획**. 무엇을 어떤 순서로 만들지 | 계속 갱신 |
| `docs/dev/review/` | **검증 결과**. 구현 검증, 계획 검토, 측정 기록 | 검토할 일이 있을 때만 새로 쓴다 |
| `docs/release/` | 별도 릴리스 영역. W 개발 문서 기준에 포함하지 않음 | 별도 담당 작업에서 갱신 |

`docs/dev/review/` 는 **그때의 관찰 기록**이다. 나중에 사실이 달라져도 고쳐 쓰지 않는다.
달라진 내용은 새 문서로 남기고, 정본(`docs/dev/`)과 계획(`docs/dev/plan/`)을 갱신한다.

## docs/dev/ — 정본

| 파일 | 내용 |
|---|---|
| [ASKBUDDY_MVP_CURRENT.md](ASKBUDDY_MVP_CURRENT.md) | 제품·데이터·API·화면·배포 계약. **단일 정본** |
| [DEV_TODO_CURRENT.md](DEV_TODO_CURRENT.md) | 남은 작업의 실행 순서와 완료 기준 |
| [이관경계_실험설계.md](이관경계_실험설계.md) | 무엇을 모델에 넘기고 무엇을 우리가 쥐는가. 평가·승격 기준 |
| [C0_DECISIONS_AND_PLAN.md](C0_DECISIONS_AND_PLAN.md) | C0 결정서와 W/R 병렬 계획 |
| [HANDOFF_2026-09-14.md](HANDOFF_2026-09-14.md) | 신규 합류자 입구 문서 |
| `c0_cost_scenarios.json` | 원가 시나리오. **코드가 읽는다** (`api/app/usage/report.py`) |

## docs/dev/plan/ — 구현 계획

| 파일 | 내용 |
|---|---|
| [C0_COST_MEASUREMENT_PLAN.md](plan/C0_COST_MEASUREMENT_PLAN.md) | CP-00A~C 원가 계측 |
| [W1_MEASUREMENT_PLAN.md](plan/W1_MEASUREMENT_PLAN.md) | 채점기 교정과 측정 구조 (①~⑤) |
| [W_EVAL_CAMPAIGN_V1.md](plan/W_EVAL_CAMPAIGN_V1.md) | W 평가 캠페인 사전등록·잠금 계약 |
| [R_IMPLEMENTATION_PLAN.md](plan/R_IMPLEMENTATION_PLAN.md) | R0~R5 항목별 순서·완료 기준과 반복 평가 계약 |
| [R_TO_W_HANDOFF_20260917.md](plan/R_TO_W_HANDOFF_20260917.md) | R 누적 구현 push 인계·W 연결점·통합 검증과 잔여 |
| [C0_W_START_HANDOFF.md](plan/C0_W_START_HANDOFF.md) | R 계측 접점과 W 착수 인계 |

## docs/dev/review/ — 검증 결과

R0 반복 캠페인: [R_V2_CAMPAIGN_20260916.md](review/R_V2_CAMPAIGN_20260916.md) — 실행 동일성·반복 안전성·A/A 대조·외부 인수 경계.

R0 단일 질문 수집·보고: [R_V2_EVALUATION_20260916.md](review/R_V2_EVALUATION_20260916.md) — 고정 질문 분모, 출력별 검토 연결, v2 실제 DB/API 인수.

R/W 최신 pull 통합: [R_PULL_DEV_RELEASE_20260916.md](review/R_PULL_DEV_RELEASE_20260916.md). `4212fec`와 R 로컬 작업의 충돌 해결·문서 이동·migration 번호 검증.

R 후속 구현: [R_POLICY_NOTIFICATIONS_20260916.md](review/R_POLICY_NOTIFICATIONS_20260916.md) — 정책 명시 확인·직원 앱 알림 연결과 권한·중복·실패 검증.

R 최신 구현/미완료 범위: [R_RUNTIME_IMPLEMENTATION_20260916.md](review/R_RUNTIME_IMPLEMENTATION_20260916.md).

R 후속 검증: [R_RERANK_USAGE_20260916.md](review/R_RERANK_USAGE_20260916.md) — 재정렬 계측·장애 처리, 434 tests/95 subtests 및 DB/API 172 PASS. 실제 모델 품질 평가는 별도다.

| 파일 | 내용 |
|---|---|
| [AI_PLAN_REVIEW_20260914.md](review/AI_PLAN_REVIEW_20260914.md) | AI 개선 계획 엄밀 검토 |
| [C0_REVIEW_20260914.md](review/C0_REVIEW_20260914.md) | C0 계약 반례 검토 (RV-01~12) |
| [C0_R_REVIEW_20260914.md](review/C0_R_REVIEW_20260914.md) | R 구현 검토 |
| [C0_R_IMPLEMENTATION_20260914.md](review/C0_R_IMPLEMENTATION_20260914.md) | R 구현 인수 기록 |
| [C0_WR_ANSWER_BOUNDARY.md](review/C0_WR_ANSWER_BOUNDARY.md) | W/R 답변 검증 접점 인수 기록 |
| [W0_BASELINE_20260915.md](review/W0_BASELINE_20260915.md) | W0 기준선 측정과 채점기 결함 |
| [C0_R_SEQUENTIAL_STATUS.md](review/C0_R_SEQUENTIAL_STATUS.md) | R 순차 진행 상태 |
| [C0_R_ANSWER_USAGE.md](review/C0_R_ANSWER_USAGE.md) | R 답변 호출 계측 기록 |
| [C0_R_STRICT_REVIEW_20260915.md](review/C0_R_STRICT_REVIEW_20260915.md) | R 엄밀 검토 |
| [C0_WR_PULL_REVIEW_20260915.md](review/C0_WR_PULL_REVIEW_20260915.md) | W/R 합류 검토 |
| [R0_REPEAT_SAFETY_20260915.md](review/R0_REPEAT_SAFETY_20260915.md) | R0 반복 안전성 직접 재현과 회귀 검증 |
| [R_E0_STALE_CONTEXT_20260915.md](review/R_E0_STALE_CONTEXT_20260915.md) | E0 오프라인 기준선·stale 재검색·M3 문맥 첫 단위, DB 장애와 미완료 범위 |
| [R_DB_RESUME_20260916.md](review/R_DB_RESUME_20260916.md) | Docker 재개·DB 50개·PG17 전체 migration 재구축·검증 환경 정정 |
| `C0_W_HANDOFF_VALIDATION.json` | W 인계 검증 범위와 소스 해시 |
| [W_MEASUREMENT_FIXES_20260915.md](review/W_MEASUREMENT_FIXES_20260915.md) | 채점·CLI·W 임베딩 연결/계측·반복 산술 교정과 미완료 재평가 |
| [W_EVAL_CAMPAIGN_VALIDATION_20260916.md](review/W_EVAL_CAMPAIGN_VALIDATION_20260916.md) | split/hash/후보/실행표/예산·개봉 잠금 검증 |
