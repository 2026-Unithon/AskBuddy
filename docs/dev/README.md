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
| [C0_W_START_HANDOFF.md](plan/C0_W_START_HANDOFF.md) | R 계측 접점과 W 착수 인계 |

## docs/dev/review/ — 검증 결과

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
| `C0_W_HANDOFF_VALIDATION.json` | W 인계 검증 범위와 소스 해시 |
| [W_MEASUREMENT_FIXES_20260915.md](review/W_MEASUREMENT_FIXES_20260915.md) | 채점·CLI·W 임베딩 연결/계측·반복 산술 교정과 미완료 재평가 |
| [W_EVAL_CAMPAIGN_VALIDATION_20260916.md](review/W_EVAL_CAMPAIGN_VALIDATION_20260916.md) | split/hash/후보/실행표/예산·개봉 잠금 검증 |
