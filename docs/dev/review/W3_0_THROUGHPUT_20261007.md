# W3-0 처리량 측정 — 두 W2 플래그 켜짐 (2026-10-07)

> 설계: `docs/dev/plan/W3_0_FLAG_READINESS_DESIGN.md` §3-5. 합격선 없음(D21 카드 생성 지연 상한 보류).
> 합성 데이터·합성 모델 대역, 유료 호출 0, 비용 0. 숫자는 이 조건의 관찰 기록이며 운영 지연 보장이 아니다.

## 조건

- 스크립트: `api/scripts/probe_w3_flag_throughput.py` (브랜치 `w/w3-fact-assembly`, 측정 시 HEAD `55d9bcc` + 미커밋 작업 트리)
- 명령(`api/` 에서, 로컬 Docker `pgvector/pgvector:pg17` 을 127.0.0.1:55439 로 띄운 뒤):
  `PYTHONPATH=. PYTHONUTF8=1 <venv python> -B scripts/probe_w3_flag_throughput.py --model-delay-ms 1500 --out <JSON 경로>` (종료 코드 0)
- DB: 로컬 Docker `pgvector/pgvector:pg17`, migration 전체 적용한 새 UUID DB. 기기: Apple M4, 메모리 16GB, macOS(Darwin 25.6.0 arm64)
- 측정일: 2026-10-07 (KST)
- 자료: 영상 자료 1건, 구간 10개, 사실 300건(구간당 30), 대상 60개(`측정메뉴00`~`59`, 대상마다 후보 계산이 돈다)
- 플래그: `w_entity_revision_enabled=true`, `w_upload_proposals_enabled=true`
- 변수: 구간 동시성 1·2 × 합성 모델 지연 0ms·1500ms (호출마다 `asyncio.sleep`). 각 조건 1회씩 측정(반복 없음)
- 정의: total = `process_source` 벽시계 / link = 구간마다 `link_source_facts`(안의 잠금 대기 포함) / lock_wait = 트랜잭션에서 처음 매장 잠금을 잡기까지 / lock_hold = 처음 잡은 때 → `_persist_ledger`·`_persist` 가 끝날 때(commit 제외) / 후보 = 새 대상 하나의 `_propose_candidates`

## 결과

| 지연 ms | 동시성 | total ms | link p50/p95 ms (합) | lock_wait p50/p95/max ms | lock_hold 합 ms | lock_hold 몫 | 후보 p50/p95 ms (n) |
|---|---|---|---|---|---|---|---|
| 0 | 1 | 1891.3 | 90.1/187.8 (1065.6) | 0.2/0.6/0.6 (n=11, 합 3.2) | 1338.3 | 0.708 | 1.6/2.5 (n=60) |
| 0 | 2 | 1796.5 | 192.8/371.8 (2216.3) | 65.6/163.2/163.2 (n=11, 합 814.5) | 1643.2 | 0.915 | 1.7/3.3 (n=60) |
| 1500 | 1 | 18893.5 | 95.0/241.2 (1217.4) | 0.3/0.9/0.9 (n=11, 합 4.0) | 1396.2 | 0.074 | 1.8/4.7 (n=60) |
| 1500 | 2 | 10831.8 | 151.3/440.2 (1957.9) | 0.7/312.1/312.1 (n=11, 합 531.6) | 1612.5 | 0.149 | 1.6/3.1 (n=60) |

모든 조건에서 `source_facts`=300, `knowledge_entities`=60, `fact_revisions`=300, `fact_occurrences`=300, `upload_change_proposals`=60, `knowledge_entity_candidates`=265.

## 관찰

- 매장 lock 보유 몫(lock_hold 합 / total): 지연 1500ms 조건에서 동시성 1 은 0.074, 동시성 2 는 0.149 로 0.5 미만이다. 모델이 느린 조건에서는 매장 lock 이 자료 처리 시간의 작은 몫이다.
  지연 0ms 조건에서는 0.708(동시성 1)·0.915(동시성 2)로 0.5 를 넘는다. 이는 모델 대기가 없어 DB 작업이 시간 대부분을 차지하는 조건이며, 실제 모델 지연은 재지 않았다.
- 동시성 2 에서 두 구간이 실제로 겹쳤는가: 겹쳤다. 동시성 2 의 lock_wait 는 지연 0ms 에서 합 814.5ms·p95 163.2ms, 지연 1500ms 에서 합 531.6ms·p95 312.1ms·max 312.1ms 로 0 보다 크다(구간이 매장 lock 을 두고 기다렸다). 동시성 1 의 lock_wait 최대는 0.6ms(0ms 지연)·0.9ms(1500ms 지연)로 사실상 대기가 없다. 1500ms 조건에서 total 이 동시성 1 의 18893.5ms 에서 동시성 2 의 10831.8ms 로 줄어 모델 대기가 겹쳤음도 보인다. 겹침 판단은 lock_wait 와 total 변화로 한 것이며 구간별 시각 기록은 남기지 않았다.
- 동시성 2 에서는 lock 대기로 link 시간이 늘었다(p95 187.8 → 371.8ms @0ms, 241.2 → 440.2ms @1500ms).
- 대상 하나당 후보 계산: p50 1.6~1.8ms, p95 2.5~4.7ms, 새 대상 수 n=60(조건마다).
- lock_wait 의 n=11 은 구간 10개의 원장 연결 트랜잭션 + 카드 저장 트랜잭션 1회다.

## 한계

- 로컬·합성 조건이다. 운영 DB(Supabase) 왕복 지연·동시 매장 부하는 들어가지 않았다.
- 조건마다 1회 측정이라 변동 폭을 모른다.
- lock_hold 는 commit 시간을 빼고, link 는 안의 잠금 대기를 포함한다.
- 실제 모델 지연은 재지 않았다(1500ms 는 합성 값).

## 원자료

```json
[
  {
    "conditions": {
      "facts": 300,
      "entities": 60,
      "segments": 10,
      "segment_concurrency": 1,
      "model_delay_ms": 0
    },
    "total_ms": 1891.3,
    "link": {
      "n": 10,
      "sum_ms": 1065.6,
      "p50_ms": 90.1,
      "p95_ms": 187.8,
      "max_ms": 187.8
    },
    "lock_wait": {
      "n": 11,
      "sum_ms": 3.2,
      "p50_ms": 0.2,
      "p95_ms": 0.6,
      "max_ms": 0.6
    },
    "lock_hold": {
      "n": 11,
      "sum_ms": 1338.3,
      "p50_ms": 90.0,
      "p95_ms": 275.6,
      "max_ms": 275.6
    },
    "candidates_per_new_entity": {
      "n": 60,
      "sum_ms": 107.4,
      "p50_ms": 1.6,
      "p95_ms": 2.5,
      "max_ms": 12.6
    },
    "lock_hold_share": 0.708,
    "rows": {
      "source_facts": 300,
      "knowledge_entities": 60,
      "knowledge_entity_candidates": 265,
      "fact_revisions": 300,
      "fact_occurrences": 300,
      "upload_change_proposals": 60
    }
  },
  {
    "conditions": {
      "facts": 300,
      "entities": 60,
      "segments": 10,
      "segment_concurrency": 2,
      "model_delay_ms": 0
    },
    "total_ms": 1796.5,
    "link": {
      "n": 10,
      "sum_ms": 2216.3,
      "p50_ms": 192.8,
      "p95_ms": 371.8,
      "max_ms": 371.8
    },
    "lock_wait": {
      "n": 11,
      "sum_ms": 814.5,
      "p50_ms": 65.6,
      "p95_ms": 163.2,
      "max_ms": 163.2
    },
    "lock_hold": {
      "n": 11,
      "sum_ms": 1643.2,
      "p50_ms": 124.4,
      "p95_ms": 240.9,
      "max_ms": 240.9
    },
    "candidates_per_new_entity": {
      "n": 60,
      "sum_ms": 109.0,
      "p50_ms": 1.7,
      "p95_ms": 3.3,
      "max_ms": 4.3
    },
    "lock_hold_share": 0.915,
    "rows": {
      "source_facts": 300,
      "knowledge_entities": 60,
      "knowledge_entity_candidates": 265,
      "fact_revisions": 300,
      "fact_occurrences": 300,
      "upload_change_proposals": 60
    }
  },
  {
    "conditions": {
      "facts": 300,
      "entities": 60,
      "segments": 10,
      "segment_concurrency": 1,
      "model_delay_ms": 1500
    },
    "total_ms": 18893.5,
    "link": {
      "n": 10,
      "sum_ms": 1217.4,
      "p50_ms": 95.0,
      "p95_ms": 241.2,
      "max_ms": 241.2
    },
    "lock_wait": {
      "n": 11,
      "sum_ms": 4.0,
      "p50_ms": 0.3,
      "p95_ms": 0.9,
      "max_ms": 0.9
    },
    "lock_hold": {
      "n": 11,
      "sum_ms": 1396.2,
      "p50_ms": 96.6,
      "p95_ms": 240.3,
      "max_ms": 240.3
    },
    "candidates_per_new_entity": {
      "n": 60,
      "sum_ms": 127.1,
      "p50_ms": 1.8,
      "p95_ms": 4.7,
      "max_ms": 8.7
    },
    "lock_hold_share": 0.074,
    "rows": {
      "source_facts": 300,
      "knowledge_entities": 60,
      "knowledge_entity_candidates": 265,
      "fact_revisions": 300,
      "fact_occurrences": 300,
      "upload_change_proposals": 60
    }
  },
  {
    "conditions": {
      "facts": 300,
      "entities": 60,
      "segments": 10,
      "segment_concurrency": 2,
      "model_delay_ms": 1500
    },
    "total_ms": 10831.8,
    "link": {
      "n": 10,
      "sum_ms": 1957.9,
      "p50_ms": 151.3,
      "p95_ms": 440.2,
      "max_ms": 440.2
    },
    "lock_wait": {
      "n": 11,
      "sum_ms": 531.6,
      "p50_ms": 0.7,
      "p95_ms": 312.1,
      "max_ms": 312.1
    },
    "lock_hold": {
      "n": 11,
      "sum_ms": 1612.5,
      "p50_ms": 128.2,
      "p95_ms": 311.4,
      "max_ms": 311.4
    },
    "candidates_per_new_entity": {
      "n": 60,
      "sum_ms": 106.8,
      "p50_ms": 1.6,
      "p95_ms": 3.1,
      "max_ms": 4.0
    },
    "lock_hold_share": 0.149,
    "rows": {
      "source_facts": 300,
      "knowledge_entities": 60,
      "knowledge_entity_candidates": 265,
      "fact_revisions": 300,
      "fact_occurrences": 300,
      "upload_change_proposals": 60
    }
  }
]
```

이 측정은 브랜치가 main `efa5763`(PR #45: `retry_io`·대상 단위 조립 배치)을 따라잡기 전에 했고, 그 뒤 다시 측정하지 않았다.
