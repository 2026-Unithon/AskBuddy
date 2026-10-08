# W3a 사실 조립 배치 동시성 측정 (W3-1b) — 2026-10-08

관찰 기록이다. 한 번 쓰고 고치지 않는다.

**합성 지연이며 실제 모델 지연·공급자 rate limit 은 재지 않았다. 기본값 1 을 올리는 것은 사용자가 정한다.**

## 조건

| 항목 | 값 |
|---|---|
| 스크립트 | `api/scripts/probe_w3a_assemble_concurrency.py --model-delay-ms 1500 --repeats 3` |
| 입력 | 합성 대상 8개 × 사실 5개 (`EntityGroup` 직접 생성, DB 없음) |
| `assemble_batch_facts` | 5 → 배치 8 |
| 모델 | `gemini._call` 합성 대역 — 1500ms 잠든 뒤 `mock._planned` 계획을 돌려준다. 비용 0 |
| 경로 | `fact_assembly.plan_entities` → `extract.assemble_card_plan` → `gemini.assemble_plan` → `measured_call`(전역 게이트 `ingest_model_concurrency`) |
| `ingest_model_concurrency` | 4 (기본값) |
| 원가 수집기 | 메모리 목록 대역(`start`/`finalize`) |
| 기기 | macOS-26.6.2-arm64 · arm64 · CPU 10 · Python 3.12.14 |

## 벽시계

| `assemble_concurrency` | 반복별(초) | 중앙값(초) |
|---|---|---|
| 1 | 12.025, 12.027, 12.029 | 12.027 |
| 2 | 6.014, 6.013, 6.023 | 6.014 |
| 4 | 3.010, 3.007, 3.012 | 3.010 |

배치 8 × 1.5초 = 12초가 c=1 의 하한이다. c=2·4 는 각각 그 1/2·1/4 에 가깝다 — 합성 대역에는
공급자 쪽 대기·rate limit 이 없으므로 이 비율은 실제 호출에서 기대할 수 있는 상한이지 예측이 아니다.

## 확인

| # | 내용 | 결과 |
|---|---|---|
| ① | c=1·2·4 의 `PlanningOutcome.proposals` 동일(같은 c 안 반복도 동일) | 통과 |
| ② | c 가 클수록 짧음 (기록만, 합격선 없음) | 12.027 > 6.014 > 3.010 |
| ③ | c=4·non-strict, 배치 3(plan3)에만 예외 → `failed_entity_ids == [4]`(그 배치 대상), `errors == ["plan3: ValueError: 합성 배치 실패"]`, 나머지 대상 제안이 ①과 같음 | 통과 |
| ④ | 같은 실패 + strict → `RuntimeError("카드 조립 실패 …")`, `__cause__` 가 원래 예외 | 통과 |
| ⑤ | 원가 시도 기록 수 = 배치 수(8), `segment_id` 집합 `plan0..plan7` — c=1·2·4 모두 같음 | 통과 |

## 원 결과 (JSON)

```json
{"conditions":{"entities":8,"facts_per_entity":5,"assemble_batch_facts":5,"batches":8,"model_delay_ms":1500,"repeats":3,"ingest_model_concurrency":4,"machine":"macOS-26.6.2-arm64-arm-64bit · arm64 · CPU 10 · Python 3.12.14"},"timings_sec":{"1":[12.025,12.027,12.029],"2":[6.014,6.013,6.023],"4":[3.01,3.007,3.012]},"median_sec":{"1":12.027,"2":6.014,"4":3.01},"checks":{"1_same_proposals":true,"2_faster_with_c (기록만)":true,"3_partial_failure":{"failed_entity_ids":[4],"expected":[4],"errors":["plan3: ValueError: 합성 배치 실패"],"rest_same":true},"4_strict_raises":true,"5_segments":{"by_c":{"1":["plan0","plan1","plan2","plan3","plan4","plan5","plan6","plan7"],"2":["plan0","plan1","plan2","plan3","plan4","plan5","plan6","plan7"],"4":["plan0","plan1","plan2","plan3","plan4","plan5","plan6","plan7"]},"attempts_by_c":{"1":8,"2":8,"4":8},"ok":true}}}
```

## 재지 않은 것

- 실제 모델 지연과 그 분산, 공급자 rate limit·429 재시도, 큰 배치의 출력 토큰 지연.
- `ingest_model_concurrency` 를 다른 단계(사실 추출 구간)와 함께 쓸 때의 경합.
- 실제 DB 저장 시간(저장은 이 측정 범위가 아니다).
