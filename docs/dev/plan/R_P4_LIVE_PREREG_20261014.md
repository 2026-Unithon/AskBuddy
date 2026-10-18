# R P4 유료 평가 사전등록 — 절차와 사용자 결정 대기 목록

2026-10-14 (KST). 담당 R. 기준 `main` `e34c9b4`(PR #58 머지 뒤).
선행: [통합 실행 계획](RW_NEXT_EXECUTION_20261012.md) P4, [P4 로컬 구현 기록](../review/R_P4_CASE_CONTEXT_20261013.md).
정본 규칙: D17·D18·D21, [실험설계](../이관경계_실험설계.md) §9-3.

**이 문서는 유료 실행 승인이 아니다.** 유료 호출은 0회이며, 아래 §4 가 비어 있는 동안
실행할 수 없다(코드가 막는다).

---

## 1. 왜 이것이 먼저인가

P4 의 남은 범위는 "실제 모델 품질·지연 인수" 다. 그런데 D17·D18 은 실험 **전에**
정답·채점기·snapshot 버전·분모·반복 수·실패 처리·대표 개선량을 고정하라고 요구한다.
고정하지 않고 돌리면 결과가 나온 뒤에 분모나 필수 질문을 고를 수 있고, 그러면
"개선했다" 가 증명이 되지 않는다.

코드에서 확인한 빈칸(2026-10-14): `app/team/v2_campaign.py` 의 `compare_campaign` 은
`plan['registration_ref']` 를 **문자열로만** 받는다. 그 모듈 주석도 "hash는 서명/실제
사전등록 증명이 아니다" 라고 적어 두었다. 즉 등록 레코드 자체와 사후 대조가 없었다.

## 2. 이번에 만든 것

| 파일 | 역할 |
|---|---|
| `api/app/team/prereg.py` | 등록 레코드 계약(`r_campaign_registration/v1`), hash, 유료 호출 전 가드, 실행 전 입력 대조, 실행 후 캠페인 대조 |
| `api/scripts/register_r_campaign.py` | ① 등록 파일 생성(`--output`) ② 끝난 캠페인 대조(`--check-report`) |
| `api/scripts/run_r_operations_http.py` | `--live-plan` 을 주면 `--registration` 을 **필수**로 요구하고, 등록과 실제 입력이 같은지 확인한 뒤에만 시작 |

고정하는 것(한 글자 바뀌면 hash 가 달라진다):

- 정답·질문 세트 `manifest_hash`(= frozen challenge 의 `content_sha256`), `truth_kind`·`truth_version`
- snapshot: `snapshot_id`·`knowledge_revision`·`snapshot_hash`
- 채점기 `evaluator_hashes`(기본 `prereg.py`·`v2_campaign.py`·`v2_evaluation.py`·`answer_metrics.py`)
- 실행 당시 코드 `source_manifest_hash`
- 분모 `question_ids`(**순서·개수까지**), 필수 질문 `must_have_ids`
- 반복 `repeat_count` ≥ 3, A/A 대조 `control_count` ≥ 3, 대표 개선량 `min_median_delta`
- 실패 처리: 제품 오류 = `FALSE`, 평가자 장애 = `UNJUDGED`, timeout 처리, 재시도 한도, 중단된 실행 처리
- 모델 `model_ids`, `provider_mode`, 예산 승인(상한·승인자·승인 시각·승인 근거)

막는 것:

| 상황 | 결과 |
|---|---|
| 등록 없이 유료 실행 | 러너가 시작 전에 `ValueError` |
| 등록은 해 두고 다른 질문 세트·다른 코드·다른 모델로 실행 | `PreregViolation` |
| 분모 순서·개수 변경 | `PreregViolation` |
| 계획의 원화 상한이 등록한 상한을 넘음 | `BudgetDeniedByPrereg` |
| 등록 파일 덮어쓰기(= 나중에 고친 사전등록) | 스크립트가 거절 |
| 실행 뒤 채점기·반복 수·필수 질문 변경 | `check_campaign` 이 `EVALUATOR_CHANGED`·`REPEAT_COUNT_CHANGED`·`MUST_HAVE_NOT_REGISTERED` 로 보고 |
| 대표 개선량이 등록한 최소치 미달·미판정 | `BELOW_REGISTERED_MIN_DELTA`·`REPRESENTATIVE_DELTA_UNJUDGED` |

**예산 집행 자체는 기존 `app/team/evaluation_budget.py` 의 DB 예약이 맡는다.** 이번
가드는 "등록한 상한을 넘는 계획을 들고 오는 것" 과 "등록 밖 입력으로 돌리는 것" 을
막는다. 둘을 하나로 합치지 않았다.

## 3. 쓰는 순서

```powershell
# ① 등록 (유료 실행 전, 모델 호출 0회)
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe scripts/register_r_campaign.py `
  --challenge ../output/<run>/frozen-challenge.json `
  --snapshot  ../output/<run>/published-snapshot.json `
  --sources   ../output/<run>/evaluator-sources.json `
  --must-have ../output/<run>/must-have-ids.json `
  --purpose "P4 실제 품질·지연 인수" --registered-by "<이름>" `
  --provider-mode LIVE --model <config.py 의 모델> `
  --repeats 3 --controls 3 --min-median-delta <정할 값> `
  --usd-cap <정할 값> --krw-cap <정할 값> --fx-krw-per-usd <정할 값> `
  --approved-by "<승인자>" --approved-at <ISO8601+09:00> --approval-ref "<승인 근거>" `
  --output ../output/<run>/registration.json

# ② 유료 실행 (등록 파일을 함께 넘긴다)
.venv/Scripts/python.exe scripts/run_r_operations_http.py `
  --input ../output/<run>/frozen-challenge.json --output ../output/<new-run> `
  --live-plan <plan.json> --plan-hash <digest> --approved-by "<승인자>" `
  --registration ../output/<run>/registration.json

# ③ 사후 대조
.venv/Scripts/python.exe scripts/register_r_campaign.py `
  --registration ../output/<run>/registration.json `
  --check-report ../output/<new-run>/campaign-report.json
```

## 4. 사용자가 정해야 실행되는 것 (지금 비어 있다)

| # | 결정 | 왜 필요한가 | 현재 |
|---|---|---|---|
| 1 | **유료 예산 상한**(USD, 원화 상한·환율은 선택) | D21·로드맵 §0-6. 과거 1만원 예산·778원 잔여는 **당시 기록**이며 새 승인이 아니다 | 미정 |
| 2 | **승인자·승인 시각·승인 근거 문구** | 등록 레코드에 그대로 들어간다. 추정해 적지 않는다 | 미정 |
| 3 | **필수 질문 목록**(24턴 중 어느 것이 must_have 인가) | D18 의 안전성 차단이 이 집합에서만 걸린다. 비우면 "악화 0건" 이 의미를 잃는다 | 미정 |
| 4 | **대표 개선량 최소치** `min_median_delta` | 산술 게이트의 내부 문턱(`max(5, 대조폭×배수)`)과 **별도**로 사전 고정하는 값 | 미정(스크립트 기본 5) |
| 5 | **정답 검토 담당과 truth 종류** | 현재 frozen challenge 의 `truth_kind` 는 `SYNTHETIC_AGENT_AUTHORED_NOT_HUMAN_REVIEWED` 다. 사람 검토 없이 돌리면 품질 인수가 아니라 배선 확인이다 | 미정 |
| 6 | **반복 수**(3회 이상 몇 회) | 반복을 늘려도 최댓값−최솟값은 줄지 않는다(D18). 비용과 맞바꾼다 | 기본 3 |

§4 의 1·2 가 없으면 `provider_mode=LIVE` 등록이 애초에 만들어지지 않는다(모델 검증에서 거절).

## 5. 이번에 확인한 것과 하지 않은 것

확인(2026-10-14 실측):

- 단위 `api/tests/test_r_campaign_prereg.py` — 42 passed, 10 subtests
- 전체 `pytest -q tests` — **2436 passed / 6 skipped / 4 xfailed / 198 subtests**
- 스크립트 실제 실행: P3 산출물(`no-provider-02`)로 합성 등록 생성 → **질문 분모 24개** 확인,
  분모 밖 필수 질문 ID 거절, 등록 파일 덮어쓰기 거절, 대조 모드의 통과(exit 0)·불일치(exit 1)

하지 않은 것:

- **유료 모델 호출 0회.** P4 실제 품질·지연은 여전히 미인수다
- 운영 p95 5초 인수, 사람 검토 truth, 승격 판정

### 5-1. Docker 복구 뒤 추가 실행 (2026-10-15)

앞 문단에서 "못 했다" 고 적은 PG17 종단 실행을 돌렸다. 폐기용 pgvector/pgvector:pg17
컨테이너 두 개(55439·55440), 실행 뒤 DB·컨테이너 정리.

| 실행 | 결과 |
|---|---|
| `verify_r_schema_rebuild.py` (전체 migration + W/R 시나리오) | **exit 0**, migration 50개, PostgreSQL 17.11, `PASS WA all scenarios`. 로그 1,242줄 |
| `verify_r_p4_case_context.py` (P4) | **exit 0**, `PASS P4 real fact HTTP case/selection/correction/recovery controls; zero paid calls`. **이 스크립트가 `run_r_operations_http.main()` 을 직접 부른다**(`:187`) — 사전등록 가드를 넣은 뒤에도 합성 경로가 그대로 돈다 |
| `run_r_operations_http.py` 24턴 채점 경로 | **exit 0**, 시나리오 12 / 턴 24 / HTTP 200 24 / receipt 24 / `required_facts_in_candidates` 24 / CLARIFY 24 / 기대 행동 일치 1. **2026-10-13 기록과 같은 수치**다(일반 모델 OFF 배선 확인이며 품질 통과가 아니다) |
| 새 단위 `tests/test_r_operations_runner_prereg.py` | 2 passed. `--live-plan` 에 `--registration` 이 없으면 **DB 에 붙기 전에** `ValueError` — 닫힌 포트를 DSN 으로 넣어도 같은 오류가 나는 것으로 순서를 고정했다 |
| 전체 `pytest -q tests` | **2438 passed / 6 skipped / 4 xfailed / 198 subtests** |

여전히 실행하지 않은 것: **유료 경로 자체**. `verify_live_plan` 의 유료 분기는 단위
테스트와 러너 가드까지만 확인했고, 실제 모델 호출로 돌려 본 적은 없다.

## 6. 다음

1. §4 결정 수집 → 등록 파일 생성(모델 호출 0회)
2. Docker 복구 → 합성 경로 종단 재실행으로 러너 변경 회귀 확인
3. 승인된 범위에서 소수 실제 평가 → 고정 24턴 → 반복·독립 검토(D17 순서)
4. 단계별 지연 분리 측정으로 p95 목표 확인. timeout 증가·검증 제거를 성능 달성으로 처리하지 않는다
