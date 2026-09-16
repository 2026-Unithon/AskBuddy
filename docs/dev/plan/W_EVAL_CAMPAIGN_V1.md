# W 평가 캠페인 v1

`run_extract_eval.py`가 dev/holdout 실행 전에 읽는 사전등록 계약이다. 실제 자료와 캠페인 파일은
Git 제외 경로에 둔다. holdout은 이 검증을 통과해 slot 잠금을 만든 뒤에만 원본과 truth를 읽는다.

## 필수 구조

| 필드 | 고정 내용 |
|---|---|
| `schema_version` | `w-eval-campaign/v1` |
| `campaign_id`, `status` | 고유 ID, `APPROVED` |
| `approved_by`, `approved_at`, `split` | 승인자·승인시각·`dev`/`holdout` |
| `stores` | store별 manifest/truth 전체 SHA-256과 source별 전체 SHA-256 |
| `candidates` | `CONTROL`, `CANDIDATE`, `CONTROL_REPEAT`와 각 후보의 정확한 runtime settings |
| `schedule_method`, `schedule_seed` | `RANDOMIZED`/`COUNTERBALANCED`, 결과 확인 전 고정한 seed |
| `schedule` | 1부터 연속인 slot, store/candidate/repeat/label. 후보마다 최소 3회 |
| `budgets` | 실행 수, 실행당 원본 bytes, 실행당·전체 provider attempt, 등록비 USD 상한 |
| `gates` | 3회·2회 양의 방향·최소 순증 5·must-have 악화 0·월 운영비 3,000원 |

후보 `settings`에는 채점기/코드/두 프롬프트 hash, 모델 3종, ingest mode, 온도,
추출 schema hash, 영상 전처리 값, pipeline version, `reuse_cards`/`reuse_sources`를 정확히 적는다.
현재 값을 추정해 쓰지 않고 실행 환경에서 출력한 값과 대조한다.
미커밋 변경이 있는 `-dirty` 코드에서는 캠페인을 실행하지 않는다.

```bash
cd api
python scripts/run_extract_eval.py --print-campaign-settings
```

## 실행

```bash
cd api
python scripts/run_extract_eval.py \
  --store store-c \
  --label sealed-BASE-1 \
  --allow-holdout \
  --campaign /git-excluded/path/campaign.json \
  --campaign-candidate BASE \
  --campaign-repeat 1
```

검증 순서는 다음과 같다.

1. manifest의 split/hash 목록, 후보 설정, 전체 실행표와 예산을 검증한다.
2. 캠페인 hash를 `campaign.json.locks/campaign.json`에 원자적으로 고정한다.
3. 해당 slot을 `slot-NNNN.json`으로 한 번만 claim한다. 실패한 slot도 다시 쓰지 않는다.
   앞 slot이 `SUCCEEDED` 또는 `FAILED`로 끝나기 전에는 다음 slot을 시작하지 않는다.
4. 그 뒤 실제 원본과 truth를 처음 읽어 사전등록 hash·byte 상한을 확인한다.
5. 실행 중 `events.jsonl`에 `OPENED/STARTED/SUCCEEDED/FAILED`를 추가한다.
6. 종료 시 원장의 provider attempt와 완전 관측된 등록비를 앞 slot 누계에 더해 실행당·캠페인
   전체 상한 이내인지 확인한다.

원가가 미관측이면 예산 통과로 간주하지 않고 실행을 실패시킨다. 이 잠금은 holdout을 다시
봉인해 주는 기능이 아니다. 앞 slot의 비용이 미관측이면 다음 slot도 시작하지 않는다.
claim 뒤 오류가 났다면 이미 개봉을 시도한 기록으로 남긴다.

## 범위

이 구현은 캠페인 실행을 강제하는 도구다. 실제 holdout 개봉 승인이나 유료 호출을 뜻하지 않는다.
사람 정답 인수, 16개 과거 입력 복구, 전체 원가/Storage 요율과 CP-05 승격 판정은 별도다.
