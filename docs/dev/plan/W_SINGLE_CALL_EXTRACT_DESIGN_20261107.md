# 한 번 호출 추출 전환 — 설계 (2026-11-07)

담당: W. 근거: `api/eval/single_call/README.md`(결정 S1~S7), 측정 `docs/dev/review/SINGLE_CALL_EXTRACT_3RUNS_20261106.md`.
브랜치: `w/extract-single-call-eval`.

## 1. 목표

영상을 뺀 모든 입력 형식(사진·텍스트 입력·docx·txt·pdf·음성 전사·카톡 캡처)의 사실 추출을 **Sonnet 5.5 한 번 호출**로 바꾼다.
그 한 호출이 **분류(자료 종류)와 사실 추출을 함께** 한다. 끊긴 호출을 정답 없이 입력만 보고 잡아 내고, 못 뽑은 부분만 사장님께 사유와 함께 보여 준다.

측정 근거(3회, 43건): 끊기지 않은 실행의 추출률 97~100%, 매번 놓친 사실 0개. 단 129회 호출 중 2회(약 1.6%)가 오류 없이 자료 중간에서 멈췄다 — 끊김 검사가 필수 조건이다.

## 2. 사용자 결정 (2026-11-06~07)

| # | 결정 |
|---|---|
| S1 | 기본 추출은 Sonnet 5.5 급 한 번 호출. 이 경로에 Gemini 를 쓰지 않는다 |
| S2 | 추출률 90% 미만이면 에이전트 위임·전용 파이프라인 검토. 이상이면 한 번 호출 |
| S3 | 추출률 = 정답 사실 중 결과 어디에든 언급된 비율(놓침만 잰다) |
| S4 | 영상은 범위 밖(잠정 보류) |
| S6 | 비용 상한은 매장 단위 일·월. 자료별 상한은 사고 방지 안전핀만 |
| S7 | 끊김·호출 실패·빈 결과면 최대 3번 시도 |
| S8 | **입구 분류도 같은 Sonnet 한 호출에 합친다**(별도 Gemini 분류 호출 없음) |
| S9 | **3번 시도 뒤에도 못 뽑은 부분은 그 부분만 실패로 둔다.** 뽑힌 사실은 성공으로 반영하고, 못 뽑은 부분은 사장님께 위치·사유와 함께 따로 보여 준다. 자료 전체를 실패로 만들지 않는다 |
| S11 | (2026-11-07) 배포 스위치를 따로 만들지 않고 바로 적용한다. 추출 쪽 기존 환경변수 스위치도 되도록 없앤다 |
| S10 | **사장님이 [다시 시도] 를 누르면** 처리 안 된 범위를 다시 시도될 때까지 최대 3번 시도한다. 그래도 남으면 [다시 시도] 버튼을 없애고 [직접 적기] 만 보여 준다 |

## 3. 바뀌는 확정 결정 (먼저 정본을 고친다)

- **D16** "기존 gemini-3.6-flash·온도 0.0 을 구조 실험의 비교 기준으로 고정" → 영상 제외 추출의 제품 기본을 Sonnet 5.5 로 바꾼다. Gemini Flash 는 영상·레이아웃 경로와 과거 수치의 비교 기준으로만 남는다.
- **CLAUDE.md 스택 표** "멀티모달 추출: 기준선 Gemini" → "영상 제외 추출 Sonnet 5.5, 영상·레이아웃 Gemini".
- 규칙대로 `docs/dev/ASKBUDDY_MVP_CURRENT.md`·`docs/dev/DEV_TODO_CURRENT.md`·로드맵을 구현 전에 먼저 고친다.

## 4. 설계

### 4-1. 호출 구조
- 자료 하나 = Sonnet 5.5 호출 한 번(분류+추출). 기존 `extract_facts_with_intake` 경로(B2)를 모든 크기의 자료에 쓴다. `intake_single_call_small` 스위치와 크기 제한 대신 새 설정으로 켠다.
- 입력: docx·txt·카톡·사장님 글은 글, 음성은 whisper 전사본(기존 그대로), 글자 PDF 는 PDF 원본, 사진·카톡 캡처는 이미지.
- 새 설정(`config.py`): `extract_model = "anthropic:claude-sonnet-5-5"`, `extract_anthropic_effort = "high"`, `extract_anthropic_max_tokens = 64000`, `extract_max_attempts = 3`. **배포 스위치는 두지 않는다(S11)** — 바로 이 경로가 제품 경로다. 영상용 `gemini_model` 은 그대로.
- **추출 쪽 환경변수 스위치 정리(S11):** `intake_single_call_small`(삭제 — 영상·레이아웃 밖 전부 한 호출), `extract_locator_hints`(삭제 — 늘 켬), `extract_truncation_split_max_depth`(삭제 — 이어서 뽑기로 대체), `pdf_input_mode`(삭제 — HYBRID 고정), `extract_clear_ungrounded_values`(삭제 — 끔 고정), `extract_max_output_tokens`(삭제 — 추출 모델 설정으로), `intake_bundle_enabled`(삭제 — 켬 고정). 영상 실험 스위치·SCAN LAYOUT 모드·평가용 재사용 스위치는 범위 밖이라 둔다.
- 단순해지는 것: 한 자료 안 로직별 구간 나누기(`plan_extraction` 의 다구간) 대신 **자료 단위 판정 하나**. 자료 전체가 `NOTICE` 면 지금처럼 보류(`INTAKE_NOTICE`), `NONE` 이면 본 추출 결과를 버린다.
- `extract_version`·`single_call_route` 의 `gemini_model` 하드코딩은 실제 쓴 모델로 바꾼다.
- 영상·SCAN LAYOUT 모드·사장님 사실 파싱(`parse_owner_facts`)은 바꾸지 않는다. 사장님 답변 사실 추출(`owner_text`)은 같은 `extract_facts` 를 타므로 함께 바뀐다.

### 4-2. Claude 통로 보강 (`app/ingest/providers/anthropic_call.py`)
- PDF `document` 블록 입력을 더한다(지금은 png/jpg 만).
- 스트리밍으로 받는다(긴 출력의 HTTP 시간 초과 방지).
- 추출용 effort·max_tokens 를 레이아웃 설정과 분리해 받는다.
- 비용 원장(`ai_usage_attempts`)·원본 응답(`extraction_raw_responses`)·재사용 키는 기존 `measured_call` 을 그대로 탄다. 요율표에 Sonnet 5.5 가 이미 있다.
- refusal 은 지금처럼 예외. 서버 측 fallback 은 넣지 않는다(다른 모델로 바뀌면 추출 결과의 출처 모델이 섞인다).

### 4-3. 끊김 검사 — 정답 없이 입력만 본다
- **줄 번호:** 글 입력은 줄마다 `[#N]` 을 붙인다(카톡은 기존 `message_numbers`, docx·txt·전사·사장님 글은 새 함수). 글자 PDF 는 기존 `[N쪽]` 쪽 표지 + 줄 번호. 사진·글자층 없는 스캔은 쪽 번호만.
- **모델 출력(스키마 가산):** 사실마다 근거 `line`/`page`(기존 W1-4 위치 표지). 끝에 `coverage`: 입력의 **모든 줄 번호**에 대해 `{line, refs: [local_ref…]}` 또는 `{line, no_content: "인사·잡담" 같은 짧은 이유}`.
- **서버 판정(결정적):**
  1. `coverage` 에 빠진 줄 번호 → 그 줄들은 처리 안 됨.
  2. `refs` 가 가리키는 사실이 실제로 없으면 → 그 줄은 처리 안 됨.
  3. 사실이 0개이고 `no_content` 도 없으면 → 빈 결과.
- **한계:** 사진·글자층 없는 스캔은 쪽 단위까지만 본다. 한 장 안에서 중간에 끊기면 못 잡는다(지금까지 관찰된 끊김 2건은 모두 글 입력).
- `coverage` 는 모델의 자기 보고다. 측정(§6)에서 실제 끊김을 잡는지 확인한 뒤에 켠다.

### 4-4. 재시도와 부분 실패 (S7·S9)
- 1번째 시도 뒤 처리 안 된 줄이 있으면, **2·3번째 시도는 처리 안 된 줄만** 다시 보낸다(이어서 뽑기). 앞에서 뽑힌 사실은 유지한다. 호출 실패·잘림(`max_tokens`)·형식 오류도 같은 시도 횟수를 쓴다.
- 3번 시도 뒤:
  - 뽑힌 사실은 **성공으로 원장·카드에 반영**한다.
  - 남은 줄은 **처리 안 된 범위**로 기록한다: 줄 범위(예: 31~67줄), 그 범위의 첫 줄 일부(사장님이 어디인지 알아보게), 사유(`TRUNCATED` 처리 도중 끊김 / `CALL_FAILED` 호출 실패 / `EMPTY` 빈 결과).
  - 자료 상태는 `PARTIAL`, 작업 상태는 기존 규칙(`final_job_status`)을 따른다. 처리 안 된 줄이 **전부**일 때만 그 자료가 `FAILED` 다.
- 저장(가산 migration): `ingest_job_sources.unprocessed_ranges jsonb`(범위·사유·첫 줄 일부·시도 횟수·`owner_retry_used`). 기존 `failed_segment_ids` 와 별개다.
- 다시 시도: 기존 PARTIAL 재시도(`job_worker` 의 잃은 구간 재추출)에 "처리 안 된 범위만" 을 더한다. 사장님의 다시 시도는 범위당 한 번(그 안에서 최대 3번 시도) — §4-5.

### 4-5. 사장님 화면 (업로드 결과 O4)
- 자료별로: "이 자료의 31~67줄(「5. 첫 샷 2잔은…」부터)을 정리하지 못했어요 · 처리 도중 끊겼어요(3번 시도)". 버튼 [다시 시도] [직접 적기].
- **[다시 시도](S10):** 누르면 서버가 처리 안 된 범위만 **다시 시도될 때까지 최대 3번** 시도한다(§4-4 와 같은 이어서 뽑기). 진행 중에는 기존 작업 상태 폴링으로 보여 준다.
  - 다 뽑히면 그 안내가 사라지고 새 사실이 카드에 반영된다.
  - 3번 뒤에도 남으면 **[다시 시도] 버튼을 없애고 [직접 적기] 만** 보여 준다. 사장님이 다시 시도를 쓴 범위는 `unprocessed_ranges` 에 `owner_retry_used: true` 로 남겨 버튼을 다시 그리지 않는다(새로고침·재진입에도 서버 상태가 정본).
  - 일부만 더 뽑히면 남은 범위로 안내를 갱신하고, 역시 [직접 적기] 만 남긴다.
- [직접 적기] 는 기존 사실 편집·사장님 답변 흐름으로 보낸다(새 입력 화면을 만들지 않는다).
- 나머지 카드는 지금처럼 "맞아요" 로 승인한다.
- 화면 파일(`web/app/owner/jobs/[jobId]/page.tsx`)은 지금 다른 브랜치(`w/ui-redesign`)에서 고치는 중이다 — 화면 작업은 그 브랜치가 머지된 뒤에 하거나 그쪽과 맞춘다.

### 4-6. 사장님 수정 지표
- 기존 기록 `fact_revision_meta.change_kind`(`OWNER_ADD`·`OWNER_CORRECTION`)와 사실의 출처 자료를 이어, 자료·형식·로직별 "사장님이 추가/고친 사실 수 ÷ 뽑힌 사실 수" 를 내는 보고 스크립트(`scripts/owner_correction_report.py`). 새 표 없음. 원본 내용은 꺼내지 않고 숫자만 낸다.

## 5. 범위 밖
영상, SCAN LAYOUT 모드, 매장 단위 비용 상한(S6, 별도 작업), 알바 질문 역추적(R 과 함께), 촘촘한 스캔 두 번 뽑기 보강.

## 6. 검증
- 단위: 줄 번호 붙이기(형식별), `coverage` 판정 3규칙, 이어서 뽑기 입력 만들기, 3회 시도 뒤 부분 실패 기록, 처리 안 된 줄이 전부면 FAILED, PDF document 블록, 스트리밍 응답 파싱, 설정 정리 뒤 영상 경로 요청 유지, 사장님 수정 지표 집계.
- 합성 대역 실제 DB 종단(`verify_r_schema_rebuild.py` 에 시나리오 추가): 끊긴 응답 → 이어서 뽑기 → 성공 사실은 카드, 남은 범위는 `unprocessed_ranges`, 작업 PARTIAL. 3번 모두 실패 → 그 범위만 실패.
- 매장 격리 검사, `pnpm check`, 합성 API Playwright(부분 실패 안내·다시 시도 진행·3번 뒤 [다시 시도] 사라지고 [직접 적기] 만·새로고침 뒤에도 유지).
- **유료 재측정(승인 받음 범위):** 시험 세트 43건 × 3회를 새 경로(분류 꼬리·줄 번호·coverage)로. 통과 기준: ① 추출률 3회 중앙값 90% 이상 유지 ② 끊긴 호출이 나오면 coverage 판정이 잡는다(못 잡으면 coverage 를 켜지 않고 다시 설계) ③ 분류 결과가 사례의 주된 로직과 맞는지 기록. 예상 4~5 USD, 실행별 기록.

## 7. 위험

| 위험 | 대응 |
|---|---|
| coverage 를 모델이 거짓으로 채움(처리 안 한 줄을 "내용 없음" 으로) | 측정에서 끊김 사례로 확인. 근거 줄 끝부분 검사(사실 근거 줄이 입력 끝까지 닿는가)를 함께 본다 |
| 출력이 길어져 비용 증가 | 줄마다 짧은 답. 측정에서 토큰 증가분을 기록 |
| 이어서 뽑기에서 앞뒤 문맥이 끊겨 사실이 잘림 | 이어 보내는 범위 앞에 몇 줄 겹쳐 보낸다(겹친 줄의 사실은 중복 제거) |
| 자료 단위 분류로 바뀌어 섞인 자료의 공지 구간을 따로 보류하지 못함 | Phase C 공지 설계에서 다시 본다. 이번엔 자료 전체 공지만 보류 |
| 화면 파일이 다른 브랜치와 겹침 | 화면 작업 순서를 마지막에 두고 머지 상태를 확인 |

## 8. 구현 기록 (2026-11-07, 브랜치 `w/extract-single-call-eval`, 커밋 전)

| 부분 | 파일 |
|---|---|
| Claude 추출 통로(스트리밍·PDF·이미지·SDK 스키마 변환) | `app/ingest/providers/anthropic_call.py` `call_extract` |
| 한 번 호출(줄 번호·끊김 판정·이어서 뽑기·합치기·시도 반복) | `app/ingest/extract/single_call.py` |
| 지시문 꼬리 | `prompts/extract_facts_single_suffix.ko.txt`(줄 처리 보고), `prompts/extract_facts_continuation.ko.txt`(이어서 뽑기) |
| 결과 형식 | `schemas.py` `CoverageItem`·`SingleCallExtractionResult`·`UnprocessedRange` |
| 입구·파이프라인 | `intake/route.py`(`single_call_eligible`·`single_call_source`·`extract_with_intake`), `pipeline.py`(입구 블록·`_record_unprocessed`·`UNPROCESSED_LINES`) |
| 작업자·API | `job_worker.py`(`owner_retry_lines`·PARTIAL 재시도가 남은 줄만), `job_repository.py`·`router.py`(작업 상세 `unprocessed_ranges`) |
| 점주 답변 | `owner_text.py` — 사실 추출만 한 번 호출(판정은 기존 답변 묶음 분류 그대로) |
| migration | `supabase/migrations/20261107100000_w_single_call_unprocessed.sql` |
| 화면 | `web/components/owner/unprocessed-ranges.tsx`, `web/app/owner/jobs/[jobId]/page.tsx` |
| 수정 지표 | `app/usage/owner_correction_report.py`, `scripts/owner_correction_report.py` |

설계와 달라진 점·추가 결정:
- **저장된 판정이 있어도 한 번 호출로 뽑는다**(재시도·복구·평가 실행). 판정은 다시 저장하지 않는다. 이전에는 저장 판정이 오면 Gemini 보통 추출로 갔다.
- **작업 묶음 분류는 구역(LAYOUT) 스캔에만** 쓴다. 영상 밖 자료를 미리 묶어 분류하면 한 호출의 판정이 묻힌다(S8).
- **저장된 NONE 판정이면 전처리·모델 호출 없이 끝낸다**(한 호출 자료는 구간 계획이 없으므로). 재시도에 모델 0회.
- 점주 칩이 모델의 NONE 을 뒤집으면 Gemini 보통 추출 대신 "업무 자료로 지정" 문구를 붙여 한 호출로 다시 뽑는다.
- 사장님 [다시 시도]는 새 API 없이 **기존 작업 재시도**(`POST /ingest/jobs/{id}/retry`)를 탄다 — PARTIAL 자료를 다시 대기열에 넣으면 작업자가 남은 줄만 이어서 뽑는다. [직접 적기]는 자료 넣기(`/owner/add`)로 보낸다.
- 잘린 출력을 반으로 나눠 다시 뽑던 코드(`_extract_with_split`·`_split_input`)는 스위치를 없애며 죽은 코드가 되어 지웠다.
- 남은 Gemini 호출: 영상 추출, SCAN LAYOUT, 점주 답변 묶음 분류(답변 글+첨부 판정), 카드 조립(`assemble_card_plan`), 점주 사실 파싱. 이번 범위 밖이다.

구현 중 발견해 고친 문제:
- **제품 통로가 숫자 칸의 minimum/maximum 을 보내 Anthropic 이 400 으로 거절**했다(신뢰도 0~1 등). 시험 실행기는 SDK 변환을 써서 드러나지 않았다. `anthropic.transform_schema` 로 바꾸고 회귀 테스트를 더했다. 실제 DB 검증 중 발견 — 이 검증에서 실제 요청 3건이 나갔고 모두 400(처리 전 거절, request_id `req_011CgoDYyEQAnyJRBVKr2XGN`·`req_011CgoDZ1ByRxfUVM4v3e3TG`·`req_011CgoDZ34aKfYSzUkzWQWyy`).
- 그 원인: 한 번 호출이 mock/실제를 자기 설정으로 갈라 `.env` 의 `INGEST_MODE=real` 이 새었다. **추출 모듈과 같은 설정으로 가르게** 고쳤다. 이후 검증은 API 키 셋을 비운 채 돌려 실제 호출 0건을 확인했다.
- R 검증 스크립트 `verify_r_legacy_owner_flow.py` 의 점주 답변 처리가 입구 분류(Gemini)를 대역 없이 부르고 있었다(키가 있으면 실제 호출). 공용 대역 `intake_context()` 한 줄을 더했다.

검증(합성·비용 0): API 테스트 전체 통과, 실제 DB 종단(`verify_r_schema_rebuild.py`) 전체 통과 — 새 시나리오 i-18(끊김 3번 → 범위·PARTIAL, 재시도 → 남은 줄만·SUCCEEDED, 재시도 실패 → owner_retry_used·모델 0회, 수정 지표 조회), 매장 격리 기존 15건 외 새 위반 0, `pnpm check`, 합성 API Playwright 390·360(`scripts/verify_single_call_partial_ui.cjs`).
