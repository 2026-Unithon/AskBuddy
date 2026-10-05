# SCAN 구역 기반 다단계 추출 — 설계 (2026-10-06)

> 상태: 설계 승인 대기 → 승인 후 구현 계획(writing-plans).
> 근거: `../review/W_EXTRACTION_DIAGNOSIS_20261005.md` — 현행 SCAN 단일 호출 경로가 레시피 표에서 참조 대비 0.7%(13/1,823).
> 결정 변경: 추출 모델 공급자 고정 해제(MVP 5-2 "모델 범위", CLAUDE.md 스택 표, 2026-10-05). `gemini-3.6-flash` 단일 호출은 기준선으로 남는다.

## 1. 목표와 성공 기준

표·문단·각주·사진이 섞인 스캔 자료를 **사람이 읽는 방식**(훑어보기 → 구역 나누기 → 구역별로 읽기 → 애매한 곳만 들여다보기)으로 처리해, 원장이 요약 몇 건으로 끝나는 문제를 없앤다.

| 구분 | 기준 |
|---|---|
| 기능 | store-a SCAN 3건(`a-scan-recipebook`·`a-scan-basestock`·`a-scan-notice`)이 LAYOUT 모드·실제 모델로 끝까지 처리된다. SINGLE 모드 동작과 기존 테스트는 바뀌지 않는다 |
| 품질 목표 | 레시피북 참조 대비 재현율 ≥ 80%, 메뉴 행 도달 ≥ 95/101, 값 충돌 후보 ≤ 재현 사실의 1% |
| 정직성 | 판독 불가·상한 도달이 모두 미해결 또는 PARTIAL 로 드러난다. 단계별 손실 합계가 맞아떨어진다(조용히 사라진 칸 0) |
| 원가 | 실행마다 실제 비용을 기록한다. 실험 전체의 Anthropic 사용액 ≤ 7 USD |
| 테스트 | 합성 표 이미지로 단계별 코드 검사를 단위 테스트한다. 공급자는 대역, mock 모드에서도 LAYOUT 경로가 돈다 |

품질 목표에 못 미치면 단계별 손실로 원인 단계를 고친다. 그래도 안 되면 기록하고 멈춰 상의한다. 목표를 낮추지 않는다.

## 2. 원칙

1. **모델의 자기 보고를 판정 근거로 쓰지 않는다.** "다 했다·맞다" 는 무시한다. 완료는 코드가 행 수·열 수·겹침 일치·토큰 반영으로 판정한다.
2. **판단은 비싼 모델, 반복은 싼 모델.** 싼 모델에는 판단이 필요 없는 일(잘라낸 띠 하나를 그대로 옮기기, 몇 행을 사실로 펼치기)만 준다.
3. **한 호출에 많이 맡기지 않는다.** 많이 맡기면 요약한다(진단의 원인). 입력은 띠·몇 행 단위로 작게.
4. **추정하지 않는다.** 판독 불가는 사실을 만들지 않고 미해결로 남긴다.
5. **흐름은 코드가 고정, 유연성은 재확인에만.** 자유 에이전트는 재확인 단계에서 호출 상한 안에서만 쓴다.

## 3. 흐름

```
SCAN 파일
 ① 쪽 이미지           (코드)
 ② 구역 지도           (판단 모델, 쪽당 1회) + 빈 영역 검사(코드)
 ③ 구역별 전사         (싼 모델, 병렬) + 구조 검사(코드)
 ④ 재확인              (판단 모델 + 자르기·확대 도구, 상한)
 ⑤ 사실 전개           (싼 모델, 텍스트) + 토큰 반영 검사(코드)
 ⑥ ExtractedAssertion → 기존 서버 검사 → 원장 → 조립
```

### ① 쪽 이미지
- 스캔 PDF: 쪽에 박힌 원본 이미지를 `pypdf` 로 꺼낸다(재샘플링 없음).
- 벡터·혼합 PDF: `pypdfium2` 로 렌더링한다(신규 의존성, `requirements.txt` 한 줄 추가). 렌더 DPI 는 설정.
- JPG/PNG: 그대로 1쪽.
- 쪽 수 상한은 기존 `ingest_scan_max_pages`.

### ② 구역 지도
판단 모델에 쪽 이미지(긴 변 상한 리사이즈)를 주고 구조화 출력을 받는다.

```
RegionMap { regions: [ {
  region_id, kind: TABLE | PROSE | FORM | PHOTO | FOOTNOTE,
  bbox: [x0, y0, x1, y1]   # 0~1 정규화
  reading_order,
  table?: { header_columns: [str], expected_rows: int | null, row_label_column: int | null }
} ] }
```
코드 검사:
- bbox 를 쪽 안으로 자르고 최소 크기 미만은 버린다.
- **빈 영역 검사:** 쪽을 흑백 임계로 글자 마스크를 만들고, 모든 구역 합집합 밖의 연결 성분 중 면적 임계 이상을 `UNCLASSIFIED` 구역(문단처럼 처리)으로 추가한다.
- 지도 호출이 재시도 후에도 실패하거나 스키마가 깨지면 쪽 전체를 `UNCLASSIFIED` 구역 하나로 둔다.
- **지도는 저장한다**(`ingest_job_sources.recovery_state` 의 구역 목록). PARTIAL 재시도는 저장된 지도를 재사용해 구역 ID 가 같은 영역을 가리키게 한다.

### ③ 구역별 전사
- **TABLE:** 구역을 가로 띠로 자른다. 띠 높이는 `expected_rows` 와 구역 높이로 행 4~6개 분량, 위아래 1행 분량 겹침. 띠마다 원본 해상도 crop 을 2배 확대해 싼 모델에 준다. 머리글 열 목록을 함께 주고 **칸 원문 그대로**를 받는다.
  ```
  BandRows { rows: [ { row_label: str | null, cells: [str], cut_top: bool, cut_bottom: bool } ] }
  ```
  병합 칸은 아래 행에 `↑` 로 적게 하고 채우기는 코드가 한다. 해석·환산·요약 금지.
- **PROSE / FOOTNOTE / FORM / UNCLASSIFIED:** 줄 단위 원문 전사(띠 분할 동일, 겹침 줄은 코드로 중복 제거).
- **PHOTO:** 보이는 글자·사실만 서술(추정 금지).

코드 검사(TABLE):
- 열 수 = 머리글 열 수. 다르면 그 행을 재확인 대상.
- `row_label` 이 숫자면 연속성. 빠진 번호는 해당 띠를 재확인 대상.
- 겹친 행의 두 판독 비교. 다르면 그 칸을 재확인 대상.
- 전사 행 수 vs `expected_rows`. 모자라면 재확인 대상.
- **경로 오판 복구:** 행의 절반 이상이 열 구조에 맞지 않으면 그 구역을 PROSE 로 다시 처리한다.

### ④ 재확인
- 대상: ③에서 걸린 칸·행 목록(좌표 포함).
- 판단 모델에 도구 `crop(bbox, scale)` 를 주는 tool-use 루프. 구역당 도구 호출 상한, 자료당 재확인 호출 상한(설정).
- 칸마다 `value` 또는 `UNREADABLE(reason)` 을 받는다. 목록의 모든 칸에 답이 있어야 끝난다(코드 판정). 상한 도달 시 남은 칸은 `UNREADABLE(cap)`.

### ⑤ 사실 전개
- **TABLE 행:** 머리글 + 행 원문 N개(설정, 기본 10)를 싼 모델에 텍스트로 주고 `ExtractedAssertion` 목록을 받는다. 프롬프트는 `api/prompts/` 새 파일.
- **문단류:** 전사 글을 기존 `extract_facts`(텍스트 입력)로 넘긴다.
- 코드 검사: 행 원문의 숫자 토큰과 `x` 칸이 모두 어떤 사실의 `value`·`original_assertion`·조건에 들어갔는지. 빠지면 빠진 토큰을 짚어 1회 재호출, 그래도 빠지면 `행 N 의 값 X 미반영` 을 미해결로.
- `UNREADABLE` 칸은 사실을 만들지 않고 미해결(쪽·구역·칸·사유).

### ⑥ 합류
- 구역 1개 = 기존 구간(segment) 1개. `segment_id = p{쪽}-r{구역}`. 구간별 체크포인트·PARTIAL 재시도·원래 응답 기록·원가 영수증을 그대로 쓴다.
- 근거 위치: `PAGE` locator 를 `{"page": N, "region": "r2", "bbox": [...], "row": "17"}` 로 확장(가산, 기존 `{"page": N}` 호환).
- 그 뒤 서버 검사(`validate_assertions`)·원장·조립은 기존 코드.

## 4. 모델 역할과 공급자

| 역할 | 설정 키(안) | 기본값 | 실험 후보 |
|---|---|---|---|
| 구역 지도 | `layout_region_model` | `anthropic:claude-sonnet-5-5` | `anthropic:claude-opus-5-5`, OpenAI 상위 |
| 띠 전사 | `layout_transcribe_model` | `gemini:gemini-3.6-flash` | `anthropic:claude-haiku-4-5-20251001`, OpenAI mini |
| 재확인 | `layout_recheck_model` | `anthropic:claude-sonnet-5-5` | `anthropic:claude-opus-5-5` |
| 사실 전개 | `layout_expand_model` | `gemini:gemini-3.6-flash` | `anthropic:claude-haiku-4-5-20251001` |

- 모델명은 `config.py` 단일 출처(불변식 8). 형식 `공급자:모델`.
- **공급자 어댑터:** `call(model, prompt, images, schema, max_output_tokens, tools?) -> CallResult` 하나로 통일. 기존 Gemini `_call` 을 감싸고 Anthropic·OpenAI 어댑터를 추가한다. 모두 원래 응답 기록(`raw_sink`)·원가 receipt(`recorder`)·재사용 키를 거친다. 온도 0.
- 키: `ANTHROPIC_API_KEY`(로컬만 존재). LAYOUT 모드에서 필요한 공급자 키가 없으면 **시작 시 명확한 오류**로 멈춘다(SINGLE 로 조용히 넘어가지 않는다).
- 운영 기본값은 `scan_extract_mode = "SINGLE"`.

## 5. 예산

1. **호출 상한(항상):** 자료당 쪽 수·띠 수·재확인 호출·도구 호출·전개 재호출 상한(설정). 넘으면 해당 구역 PARTIAL.
2. **금액(실험):** `run_extract_eval.py` 에 `--max-usd` — 실행 전 예상 호출×요율로 추정해 넘으면 거부, 실행 후 실제 토큰×요율 기록. 요율은 `api/config/rate_card.json` 에 쓰는 모델 단가를 공식 가격 페이지 출처·날짜와 함께 넣는다(사용자 1회 확인). 요율 없는 모델은 추정 불가로 실행 거부.

## 6. 상태·실패

- 구역 상태: `SUCCEEDED` / `PARTIAL`(판독 불가 칸·상한 도달) / `FAILED`.
- 자료·작업 상태는 기존 의미: 구역 하나라도 PARTIAL·FAILED 면 작업 `PARTIAL`.
- 공급자 오류는 현행 재시도 정책, 끝내 실패하면 그 구역만 FAILED.
- 모든 판독 불가·미반영은 미해결 목록에 쪽·구역·칸·사유와 함께 남아 검수 화면에서 보인다.

## 7. 측정

- 대조: 다수결 참조 + `api/scripts/compare_reference.py`.
- 단계별 손실 기록(보고서에 함께): 빈 영역 검사로 추가된 구역 수, 전사 행 / 예상 행, 재확인으로 바뀐 칸, 판독 불가 칸, 전개 미반영 토큰.
- **참조 편향:** 참조가 Claude 실행에 기대므로 Claude 를 쓰는 구성의 점수는 일치율이 부풀 수 있다. Gemini 만 쓴 구성과 분리 보고하고, 갈림 판독 23·이견 19 건은 점수와 별도로 원본 대조. 최종 승격 판단 전 참조 표본 사람 검토(정답지 승격)를 거친다.
- 실험 순서(탐색 1회씩, 최종만 3회 — D17 최소):
  1. 기준선 SINGLE (완료, 0.7%)
  2. LAYOUT 기본 구성
  3. 전사 모델 교체(Flash ↔ Haiku)
  4. 판단 모델 교체(Sonnet ↔ Opus) — 예산이 남을 때
  5. 최선 구성 3회 반복, 변동 보고

## 8. 코드 배치

```
api/app/ingest/layout/
  __init__.py        # run_layout_extraction(source, path, ...) -> 구간별 ExtractionOutcome 호환 결과
  pages.py           # ① 쪽 이미지
  regions.py         # ② 구역 지도 호출 + 빈 영역 검사 + 저장/재사용
  transcribe.py      # ③ 띠 분할·전사·구조 검사·병합 채우기·경로 오판 복구
  recheck.py         # ④ tool-use 재확인 루프
  expand.py          # ⑤ 행 → 사실, 토큰 반영 검사
  schemas.py         # RegionMap · BandRows · RecheckAnswer
api/app/ingest/providers/   # 공급자 어댑터 (gemini 감싸기 · anthropic · openai)
api/prompts/layout_*.ko.txt # 역할별 프롬프트
```
`pipeline.py` 는 SCAN 이고 `scan_extract_mode == "LAYOUT"` 일 때 `_preprocess_scan`·`_extract_facts_all` 대신 이 모듈을 부르고, 결과를 기존 체크포인트·원장 경로에 넘기는 분기만 추가한다.

## 9. 테스트

- 합성 표 PNG(PIL, 익명 글자): 띠 분할·겹침, 빈 영역 검사, 병합 `↑` 채우기, 열 수·행 연속 검사, 경로 오판 복구.
- 전개 토큰 반영 검사: 빠진 숫자·`x` 탐지.
- 공급자 어댑터는 대역. 상한 도달 시 PARTIAL·미해결 기록.
- 저장된 구역 지도 재사용으로 PARTIAL 재시도가 같은 구역을 가리킴.
- mock 모드: LAYOUT 경로 결정적 출력.
- 회귀: SINGLE 모드 기존 테스트 전부.
- `store-isolation-check` 로 새 쿼리 확인.

## 10. 범위 밖

카톡 캡처 이미지, W3, 운영 서버에서 켜기, 영상·음성, 정답지 승격 작업 자체(측정 판단 전 선행 조건으로만 명시).

## 11. 운영 전 할 일 (이번 범위 아님)

- 개인정보 처리방침 위탁처에 Anthropic 추가.
- 운영 서버 `ANTHROPIC_API_KEY` 등록.
