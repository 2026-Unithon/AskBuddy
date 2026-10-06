# 추출 진단 — 현행 파이프라인 vs 다수결 참조 (2026-10-05)

> 방향 탐색용 1회 진단이다. 판정·승격 근거가 아니다 (D17·D18 캠페인 아님).
> 결과로 정하는 것은 하나다: **SCAN 다단계 추출을 W3 보다 먼저 할지.**

## 왜

외부 앱 실행 6개를 다수결로 합친 참조(`api/eval/data/store-a/reference/a-scan-recipebook__consensus6__20261005.json`,
사실 1,823건, Git 제외)가 생겼다. 기존 정답지 28건은 표본이라 상위 실행이 모두 만점이어서 변별력이 없다.
현행 제품 경로(`process_source` → HYBRID → Gemini 한 번 호출)가 이 표에서 무엇을 얼마나 뽑는지 참조로 잰다.

## Global Constraints

- 평가 자료의 브랜드명·상호·메뉴 고유명을 코드·주석·테스트 픽스처·문서에 쓰지 않는다. 테스트는 `메뉴A` 같은 익명 이름만 쓴다.
- 주석은 한국어. 프롬프트·모델명·임계값 리터럴을 새로 만들지 않는다.
- DB 조회는 `store_id` 를 필수 인자로 받고 `WHERE store_id = $1` 를 건다. 이 진단은 DB 를 **읽기만** 한다.
- 커밋하지 않는다. 커밋·머지는 사용자가 한다. 변경은 작업 트리에 남긴다.
- 참조는 정답지가 아니다. 보고서에 "재현율"을 쓸 때 "참조 대비"를 붙인다.
- holdout(store-c·store-d)은 열지 않는다.

## Task 1: 참조 대조 스크립트 `api/scripts/compare_reference.py`

**목표:** 한 자료의 사실 원장(`source_facts`)을 다수결 참조와 대조해 참조 대비 재현율과 값 충돌을 보고한다.

**재사용:** 정규화·키 함수는 `api/scripts/build_consensus_reference.py` 의 `n`·`t`·`value`·`unit`·`column`·`key`·`blob` 을 import 해서 쓴다. 복사하지 않는다.

**순수 함수 `compare(reference_results: list[dict], ledger: list[dict]) -> dict`**

1. 행 연결: 참조 사실은 `consensus.row` (메뉴 번호 1~101 또는 `"각주"`)를 가진다. 참조에서 `(정규화 대상명, variant) → row` 표를 만든다.
   정규화 대상명 = `n(subject)` 에서 `HOT`·`ICE` 를 지운 것. 원장 사실은 ① 정확히 같은 키, ② variant 무시하고 대상명만 같은 것, ③ 한쪽이 다른 쪽을 포함하는 대상명(2글자 이상) 순으로 row 를 찾는다. ③에서 후보가 여럿이면 연결하지 않는다(모호).
   어느 것도 없으면 `unmapped` 로 센다.
2. 참조 사실 하나의 재현 판정 — 같은 row 의 원장 사실 중 하나라도:
   - 키가 `PRICE`·`NUM`: `key()` 가 같거나, 참조 키의 바늘(`value+unit`, 단위 `회`는 `번`으로)이 원장 사실 `blob()` 안에 있다.
   - `NEG`: 원장 사실의 polarity 가 `NEGATE` 이고 `column(attribute)` 가 같다.
   - `TXT`·`STEP`: 참조 바늘(`t(value)`, STEP 은 단계 글)이 원장 사실 `blob()` 안에 있다. 바늘이 비면 재현 아님.
3. 값 충돌 후보: 원장 `NUM` 사실 중 같은 row·같은 `column` 에 참조 `NUM` 값이 있는데 단위가 같은 값이 하나도 일치하지 않는 것. (원장 값, 참조 값 목록, 원장 원문)을 목록으로.
4. 반환 dict 키(정확히 이 이름):
   - `reference_total`, `recalled`, `recall` (소수 3자리)
   - `by_kind`: `{"PRICE"|"NUM"|"TXT"|"STEP"|"NEG": {"total", "recalled"}}`
   - `menu_rows_total`(참조의 정수 row 수), `menu_rows_touched`(재현 1건 이상인 정수 row 수), `price_recalled`(PRICE 재현 수)
   - `ledger_total`, `ledger_mapped`, `ledger_unmapped`, `unmapped_subjects`(정규화 대상명 상위 20개와 개수)
   - `conflicts`: 목록, `missed_examples`: 재현 안 된 참조 사실 중 row 순 앞 30개의 `(row, kind, original_assertion)`

**CLI**
```
python api/scripts/compare_reference.py --store store-a --source-key a-scan-recipebook \
    [--reference <path>] [--label <text>]
```
- `--reference` 기본값: `api/eval/data/<store>/reference/<source_key>__consensus*__*.json` 중 이름순 마지막.
- 매장 slug 는 `api/eval/data/<store>/manifest.json` 의 `store_slug`. DB 는 `get_settings().supabase_db_url`(api/.env, `run_extract_eval.py` 와 같은 방식).
- 원장 조회: `stores.store_slug` 로 store_id → `sources.title = source_key` 이고 그 매장인 source_id → `source_facts` 중 `is_superseded` 가 참이 아닌 것. 모든 쿼리에 store_id 조건.
- 출력: 요약을 stdout 에 찍고 `api/eval/reports/reference_compare_<source_key>_<UTC stamp>.json`·`.md` 를 쓴다(이 폴더는 Git 제외). md 에는 메타(참조 파일명·sha256 앞 16자, 원장 사실 수, label, 현재 `pdf_input_mode`·`extract_locator_hints`·`extract_truncation_split_max_depth` 설정값)와 위 지표 표, 충돌·누락 예시를 담는다.

**테스트 `api/tests/test_compare_reference.py`** (DB 없이, 익명 픽스처)
- 가격·숫자 정확 일치 재현, 단위 철자 차이(`P`/`펌프`) 재현
- 대상명 포함 매칭(원장 `ICE 메뉴A` ↔ 참조 `메뉴A`/ICE) 재현
- 모호한 포함 매칭(후보 2개)은 unmapped
- NEG 칸 일치 재현, 칸이 다르면 재현 아님
- STEP 바늘이 원장 원문에 포함되면 재현
- 값 충돌: 같은 row·칸·단위에 참조 225ml, 원장 255ml → conflicts 1건
- 집계 키 이름과 recall 계산

검증: `cd api && source .venv/bin/activate && pytest tests/test_compare_reference.py -q` 통과, 기존 `tests/test_extraction_eval.py` 회귀 없음.
`python3 .claude/skills/store-isolation-check/check_store_id.py api/scripts` 에서 새 파일 경고 없음(있으면 사유).

## Task 2: 현행 파이프라인 1회 실행 (컨트롤러)

```
cd api && python scripts/reset_eval_store.py --store store-a   # eval-a 자료·카드만. 실행 이력은 남는다
python scripts/run_extract_eval.py --store store-a --only-source a-scan-recipebook --label diag-hybrid-default
python scripts/compare_reference.py --store store-a --source-key a-scan-recipebook --label diag-hybrid-default
```
- `INGEST_MODE=real` 인지 실행 전에 확인한다(D10). mock 이면 멈춘다.
- 플래그를 켠 비교 실행은 하지 않는다 — `.env` 가 프로세스 환경을 덮어써(`override=True`) 설정을 바꾸려면 공용 `.env` 를 고쳐야 한다. 기본 설정 1회만 잰다.

## Task 3: 결과 기록 (컨트롤러)

`docs/dev/review/W_EXTRACTION_DIAGNOSIS_20261005.md` 에 실행 조건·지표·해석·권고(2순위 진행 여부)를 남긴다.
분기 기준: 참조 대비 재현율 80% 미만이면 "SCAN 다단계 추출을 W3 보다 먼저" 를 권고한다.
