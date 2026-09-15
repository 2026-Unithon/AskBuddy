# docs 구조

| 위치 | 담는 것 | 갱신 주기 |
|---|---|---|
| `docs/` | 제품·데이터·API 명세와 **전체 계획**. 정본이다 | 계속 갱신 |
| `docs/plan/` | 전체 계획에서 떼어낸 **구현 계획**. 무엇을 어떤 순서로 만들지 | 계속 갱신 |
| `docs/review/` | **검증 결과**. 구현 검증, 계획 검토, 측정 기록 | 검토할 일이 있을 때만 새로 쓴다 |

`docs/review/` 는 **그때의 관찰 기록**이다. 나중에 사실이 달라져도 고쳐 쓰지 않는다.
달라진 내용은 새 문서로 남기고, 정본(`docs/`)과 계획(`docs/plan/`)을 갱신한다.

## docs/ — 정본

| 파일 | 내용 |
|---|---|
| [ASKBUDDY_MVP_CURRENT.md](ASKBUDDY_MVP_CURRENT.md) | 제품·데이터·API·화면·배포 계약. **단일 정본** |
| [DEV_TODO_CURRENT.md](DEV_TODO_CURRENT.md) | 남은 작업의 실행 순서와 완료 기준 |
| [이관경계_실험설계.md](이관경계_실험설계.md) | 무엇을 모델에 넘기고 무엇을 우리가 쥐는가. 평가·승격 기준 |
| [C0_DECISIONS_AND_PLAN.md](C0_DECISIONS_AND_PLAN.md) | C0 결정서와 W/R 병렬 계획 |
| [HANDOFF_2026-09-14.md](HANDOFF_2026-09-14.md) | 신규 합류자 입구 문서 |
| `c0_cost_scenarios.json` | 원가 시나리오. **코드가 읽는다** (`api/app/usage/report.py`) |

## docs/plan/ — 구현 계획

| 파일 | 내용 |
|---|---|
| [C0_COST_MEASUREMENT_PLAN.md](plan/C0_COST_MEASUREMENT_PLAN.md) | CP-00A~C 원가 계측 |
| [W1_MEASUREMENT_PLAN.md](plan/W1_MEASUREMENT_PLAN.md) | 채점기 교정과 측정 구조 (①~⑤) |

## docs/review/ — 검증 결과

| 파일 | 내용 |
|---|---|
| [AI_PLAN_REVIEW_20260914.md](review/AI_PLAN_REVIEW_20260914.md) | AI 개선 계획 엄밀 검토 |
| [C0_REVIEW_20260914.md](review/C0_REVIEW_20260914.md) | C0 계약 반례 검토 (RV-01~12) |
| [C0_R_REVIEW_20260914.md](review/C0_R_REVIEW_20260914.md) | R 구현 검토 |
| [C0_R_IMPLEMENTATION_20260914.md](review/C0_R_IMPLEMENTATION_20260914.md) | R 구현 인수 기록 |
| [C0_WR_ANSWER_BOUNDARY.md](review/C0_WR_ANSWER_BOUNDARY.md) | W/R 답변 검증 접점 인수 기록 |
| [W0_BASELINE_20260915.md](review/W0_BASELINE_20260915.md) | W0 기준선 측정과 채점기 결함 |
