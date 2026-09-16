# C0-4 원가 계측 선행 계획

> 2026-09-14 사용자 회신 반영. 상태: 설계·순서 확정, 계측 코드와 DB migration은 구현 대기.
> D21의 월 3,000원은 매장별 운영 변동비다. 최초 등록 변동비는 별도 추적한다. 사용량은 시나리오로 검증하고 실제 운영 데이터로 교체한다.
> 전체 C0와 W/R 선행 관계는 [C0 결정서](../C0_DECISIONS_AND_PLAN.md), 실행 체크는 [TODO](../DEV_TODO_CURRENT.md), 평가 판정은 [실험설계](../이관경계_실험설계.md)를 따른다.

## 1. 비용 범위와 회수 개념

| 비용 | D21 포함 | 처리 |
|---|---|---|
| AI 호출 | 포함 | 추출·STT·조립·분류·관계 판정·임베딩·질문 해석·rerank·답변·검증·모든 유료 재시도 |
| Storage 저장·전송 | 포함 | 원본·파생 프레임 등 object 저장량의 시간 적분과 실제 전송량 |
| Railway·Vercel 서버 | 제외 | 이번 원가 정책에서는 고정비. 계정 총비용/부하 보고에는 남김 |
| DB | 제외 | 이번 원가 정책에서는 고정비. 매장 수·용량·부하 증가에 따른 요금 단계 변경 시 재검토 |
| 개발·품질평가 호출 | 제품 운영비에서 제외 | 실제 지출은 EVALUATION/DEVELOPMENT 열에 보존하고 고객 월 비용과 중복 합산하지 않음 |

서버/DB가 영구적으로 사용량에 무관하다는 가정은 하지 않는다. 이 항목의 사용량 기반 요금이나 규모 변화가 확인되면 범위 개정 이슈를 만든다. 지금은 사용자 결정대로 월 3,000원에 배분하지 않는다.

`cost_phase=REGISTRATION / OPERATING`과 `cost_purpose=PRODUCT / EVALUATION / DEVELOPMENT`를 별도 축으로 기록한다. REGISTERED 여부나 승인 카드 0건만 보고 단계를 자동 재분류하지 않는다. 초기 등록 캠페인 ID를 명시하고 같은 캠페인의 복구 재시도까지 연결한다. 초기 가이드 인계 후 추가 업로드·수정·점주 답변 지식화는 OPERATING이다.

초기 등록의 STT/추출/조립/분류/임베딩·등록 중 실제 과금 전송은 REGISTRATION이다. 최초 등록 파일이라도 이후 보관하는 byte-time와 조회 전송은 발생 월 OPERATING이다. 첫 달 저장량도 시간에 따라 OPERATING에 한 번만 배분하여 등록 원가와 이중 계산하지 않는다. 유효한 무상 과금 항목만 명시적으로 0이며 측정 누락은 null이다.

```text
I = 등록 AI 호출비 + 등록 중 과금 대상 전송비
O_m = 월 질문/후속 턴 AI 비용 + 월 추가 자료/수정/재색인 AI 비용
      + 월 저장 비용(최초 등록 파일 포함) + 월 운영 전송 비용
D21 운영비 통과: O_m ≤ 3,000원
첫 달 실제 변동 지출: I + O_1
H개월 누적 변동 지출: I + Σ(O_m), m=1..H
등록 예산환산 개월: I / 3,000원
예산 잔여분 보전 개월: Σ(3,000원 − O_m) ≥ I가 처음 성립하는 m
```

등록비 6,000원은 예산환산 2개월이다. 운영비가 매달 2,000원이라면 잔여 예산은 월 1,000원이어서 그 잔여분으로 등록비를 보전하는 데 6개월이 필요하다. 운영비가 계속 3,000원 이상이면 잔여 예산을 통한 보전은 불가능하다. 이 예시는 산식 검증용 가상 수치다.

매출을 통한 실제 회수기간은 별도다. 순수입·운영 변동비·결제 수수료 등 포함 범위를 정하지 않은 상태에서 등록 예산환산 개월을 손익분기/실제 회수기간으로 표시하지 않는다. 등록비 자체의 허용 상한/허용 회수개월은 운영 3,000원에서 추론하지 않으며 측정 후 상품 정책이 필요할 때 결정한다. 등록비 미지수를 이유로 계측/계약 구현을 멈추지 않는다.

## 2. 사용량 입력과 시나리오

사람이 정확한 미래 사용량을 정할 때까지 기다리지 않는다. [기계가 읽을 시나리오 입력](../c0_cost_scenarios.json)에 입력값·가정·null을 저장하고 구현 시 이 파일을 workload manifest의 시작점으로 사용한다.

필수 입력 6개는 직원 수, 1인 하루 질문 수(첫 달/안정기), 최초 영상 분, 최초 별도 음성 분, 최초 문서 페이지, 월 추가 자료(영상/음성 분·문서 페이지)다. 실제 근무일/질문 발생일, 카톡 메시지 수·입력 길이, 파일 bytes·전송량·보관 기간도 추가 계측한다. 문서 파일 개수를 페이지 수로 바꾸거나 MB로 음성 길이를 추정하지 않는다.

| 시나리오 | 직원 수 | 첫 달 1인/일 질문 | 안정기 1인/일 질문 | 질문 발생일 | 첫 달 기본 질문 | 안정기 기본 질문 | 최초 영상 |
|---|---|---|---|---|---|---|---|
| LOW | 3 | 5 | 0.3 | 30일 | 450 | 27 | 20분 |
| BASE | 4 | 8 | 0.5 | 30일 | 960 | 60 | 30분 |
| HIGH | 5 | 10 | 0.9 | 30일 | 1,500 | 135 | 40분 |

위 숫자는 사용자가 제공한 범위에서 고른 설계 가정이다. 모든 직원이 첫 달 신입이고 매일 질문한다는 보수적 초기 시나리오이며 실제 매장 평균이라고 주장하지 않는다. BASE 안정기 0.5 등 세부 선택값도 실측이 아니다. 월 30일은 forecast 단위, 실제 청구월은 해당 날짜 수로 계산한다.

운영 중 새 직원이 합류한 달에도 신입 질문 증가를 적용한다. 실제 forecast는 `(신입 직원 수×신입 질문 빈도 + 기존 직원 수×안정기 빈도)×각 질문 발생일`로 코호트를 나눈다. 두 번째 달부터 모든 직원을 무조건 안정기로 고정하지 않는다.

기본 질문 수 `Q=N×q×days`는 최초 사용자 질문이다. CLARIFY 후속 사용자 턴, 재전송, 추가 검색/모델 호출은 별도 기록한다. 시나리오에는 일반(추가 0턴), 명확화 부하(질문당 평균 추가 0.2턴), 상한 부하(모든 질문에 추가 2턴)를 함께 둔다. 질문 발생과 provider 재시도는 다른 단위다.

첫 주에 월 기본 질문의 50%를 보내는 별도 stress profile도 둔다. 이는 실측 행동이 아니라 집중 부하 시험이다. 7일·30일 지출·peak day·동시 요청·오류율을 보고하며 안정기 평균으로 첫 달 초과를 상쇄하지 않는다. 첫 달 HIGH가 3,000원을 넘으면 해당 시나리오의 D21 실패로 표시한다.

### 사용자 보고 store-a 표본

- 영상 38분·111MB, 별도 음성 2.5MB, 문서 3건, 카톡 1건, 총 약 118MB.
- 결과 사실 101건·카드 70장.
- 이 수치는 이번 사용자 보고의 실측 표본이다. 이번 작업에서 원본/DB/run을 재측정하지 않았고 run ID/hash도 제공되지 않았다.
- 음성 길이, 문서 페이지, 카톡 메시지 수, 정확 bytes는 null이다. 101건은 출력 사실 수이며 정답 truth의 분모나 recall이 아니다. 70장은 승인 여부를 확인하기 전 공개 카드 수로 쓰지 않는다.
- 기존 다른 실행의 사실/카드 수를 덮어쓰지 않는다. CP-00C에서 허용된 dev manifest·artifact와 매핑한 뒤 관측값을 추가한다. holdout은 사전 캠페인 없이 읽지 않는다.

NULL인 음성/페이지/추가 자료량은 자동 메타데이터 수집 대상으로 넘긴다. 그 값이 없는 forecast의 전체 비용은 UNKNOWN이며, 이미 관측된 구성요소의 부분합과 질문당 단가 역산 범위는 표시할 수 있다. 수집 후 각 scenario의 `workload_hash`를 고정한다.

## 3. 현재 코드에서 확인한 계측 공백

| 코드 | 현재 동작 | 우선 보강 |
|---|---|---|
| `api/app/ingest/extract/gemini.py::_call` | map/reduce 공용 호출에서 `res.text`만 반환. 재시도 decorator 존재 | 응답 즉시 usage·provider request/model·모든 attempt 저장 후 parsing/검증 |
| `api/app/ingest/preprocess/audio.py::transcribe_detailed` | 전사문·segments·모델 반환, 시간/문자 로그 | 청구 단위에 맞는 처리 duration, 입력 bytes, provider usage/요청 식별자, latency/실패 |
| `api/app/reg/embeddings.py::embed_texts` | token·latency 로그 후 vector만 반환 | 기존 단일 진입점 유지, context를 받아 durable usage receipt에 저장 |
| `api/app/categories/classifier.py`, `learn/knowledge_loop.py` | 분류 usage 일부 수집/로그, 관계 판정 모델 호출 | 등록/추가 자료/점주 답변 분류·관계 비용도 같은 receipt로 통합 |
| `api/app/learn/answering.py::_usage_of` | 일부 누락 usage를 0으로 채움 | null/실제 0 구분, 공급자 추가 billable 필드 보존, fallback/파싱 실패 비용 보존 |
| `api/app/team/runner.py`, `metrics.py` | 답변 비용 추정과 부분값 합산, 누락 token을 0으로 합산 | 전체 호출 원장 집계·관측률·known subtotal·complete total 분리 |
| `extraction_runs` migration | 토큰·원가·자료 크기 전용 컬럼 없음, 종료 후 freeze | 가산형 summary 컬럼 및 호출 원장·별도 reconciliation report |
| `api/app/ingest/preprocess/storage.py` | download/upload·서명 URL 제공, 전체 store별 저장/전송 비용 없음 | 실제 object inventory·byte-time·전송 계측·청구 대조 |

읽기 `prompt_tokens/completion_tokens/cost_usd`의 물리 컬럼은 `evaluation_results`에 있고 run 집계는 metrics JSON에 들어간다. 따라서 `evaluation_runs가 이미 전체 읽기 원가를 완전히 잰다`고 가정하지 않는다. 영상 STT와 별도 음성 STT, 실제 map 횟수, reduce·분류·임베딩을 모두 연결해야 한 번의 등록 원가를 계산할 수 있다.

## 4. 저장할 원가 데이터

### 4.1 호출 원장

논리 모듈은 기존 `api/app/contracts/usage.py` + `api/app/usage/`로 추가하는 계획이다. W가 공통 schema/repository·migration을 맡고 R이 자신의 호출부를 연결한다. 외부 계측 서비스·새 DB를 도입하지 않는다. 기존 함수 반환 계약을 깨지 않도록 trusted UsageContext/sink를 명시 인자로 전달하고 기본 도메인 반환은 유지한다.

`ai_usage_attempts`는 호출 전 시작 receipt를 commit하고 응답/실패를 제한적으로 finalize하는 원장이다. 최종 행은 불변, 늦은 공급자 정산·가격 재계산은 append-only cost assessment에 추가한다. 모델 호출 동안 DB connection/lock을 보유하지 않는다.

| 필드 묶음 | 필드·규칙 |
|---|---|
| 귀속 | store_id 필수, cost_phase, cost_purpose, registration_campaign_id, operation_id, job/source/segment/question 식별자, evaluation/extraction run 연결 |
| 호출 식별 | usage_attempt_id, logical_call_id, attempt_no, provider_request_id, stage; `(store, logical_call_id, attempt_no)` unique |
| 단계 | STT / EXTRACT / ASSEMBLE / CLASSIFY / RELATION / EMBED / QUERY / RERANK / ANSWER / VALIDATE |
| 재현 | requested_model, reported_model, prompt/schema/config hash, mode real/mock, rate_card_version |
| 실행 결과 | STARTED / SUCCEEDED / FAILED / UNKNOWN, started_at, finished_at, latency_ms, error_code, cache state |
| 모델 usage | prompt_tokens, completion_tokens, cached/thought/other units는 공급자 보고 원형과 함께 nullable로 저장; bigint 0 이상 |
| 입력 규모 | input_bytes, media_duration_sec, page_count, frame_count, actual_billable_units, 단위/근거; 누락 null |
| 원가 | currency, known_cost_usd, cost_usd nullable, price_status, fx_version, known_cost_krw, cost_krw nullable; NUMERIC/Decimal 사용 |
| 관측 상태 | usage_status=COMPLETE / PARTIAL / UNKNOWN / NOT_BILLABLE, 결측 이유·billable unit coverage |

한 호출이 여러 source를 조립하거나 여러 카드의 임베딩을 batch 처리하면 호출 receipt는 하나만 만든다. 별도 link로 source/card 기여를 연결하고 store 합계에서는 receipt 1회만 더한다. 평가 run 집계와 실제 지출 집계를 서로 합산하지 않는다.

계측 실패로 유료 호출을 무작정 반복하지 않는다. 시작 receipt 저장이 실패하면 새 유료 호출 전에 retryable 계측 오류로 종료한다. 응답 후 receipt finalize가 실패하면 이미 기록된 STARTED를 UNKNOWN으로 보고 DB 저장만 제한 재시도한다. 공급자 재호출로 복구하지 않는다. deadline 이후에도 미확정이면 비용 승격을 차단하고 기존 질문/작업 저장 상태를 왜곡하지 않는다.

### 4.2 extraction_runs summary

새 migration에서 `prompt_tokens`, `completion_tokens`(bigint nullable), `input_bytes`(고유 원본 bytes), `submitted_input_bytes`(모든 호출·재시도 전송량), `media_duration_sec`, `document_pages`, `ai_attempt_count`, `retry_count`, `known_cost_usd`, `cost_usd`, `cost_status`, `unknown_attempt_count`, `cost_phase`, `cost_report_id`를 추가한다. 보고 schema가 단위·집계 범위를 명시한다.

`cost_usd`는 해당 extraction run의 AI 시도 비용 총액이며 Storage 월 비용을 몰래 포함하지 않는다. AI+Storage 합계는 store cost report에서 계산한다. 음성/문서 비해당과 측정 누락을 구분한다. summary는 원장으로부터 만들고 partial total은 known_cost 열, 전체 미확정은 cost_usd=null이다.

run이 RUNNING일 때 summary와 종료 상태를 같은 성공 단위로 저장한다. 현재 freeze trigger를 꺼서 과거 종료 run을 수정하지 않는다. 과거 미계측 run은 UNKNOWN으로 표시하고, 늦은 정산은 새 `cost_reports` revision으로 남긴다. 평가 실패 run도 발생 비용과 raw receipt는 보존한다.

### 4.3 Storage

- `sources.file_size`의 클라이언트 값만 합산하지 않는다. 실제 object metadata의 bytes와 store scope를 서버에서 확인한다. 원본·프레임·기타 파생물·복구 가능한 잔존 버전을 같은 목록으로 관리하고 로컬 임시 파일은 외부 Storage 비용에서 구분한다.
- `(store, object path/version)` inventory와 daily byte-time sample/생성·삭제 시각을 기록한다. `Σ(bytes × 존재시간)`을 가격표의 GB-month 단위로 환산한다. MB 표시는 참고이며 계산에는 bytes와 GB/GiB·청구 시간 정의를 보존한다.
- 월초 등록 파일은 매월 남아 있으므로 저장비는 누적된다. 시나리오 report는 최소 1/3/6/12개월과 추가 자료/삭제 변화에 따른 저장 비용을 보여준다.
- native 영상 전송용 공급자 임시 파일도 bytes·생성/삭제를 기록하고 별도 요금이 있으면 포함 변동비로 매핑한다. 업로드 성공을 무료 저장이나 즉시 삭제로 가정하지 않는다.
- API/worker 다운로드, 프레임 업로드, 재시도, signed URL을 통한 브라우저 직접 조회를 포함한다. signed URL 발급 횟수를 다운로드 횟수나 전송량으로 간주하지 않는다.
- provider가 제공하는 object/store 경로별 전송 로그·청구 export가 있으면 정규화해 사용한다. 현재 접속/로그 가용성은 미검증이다. 귀속 불가능한 사용량은 `UNALLOCATED`로 남기고 store별 완전 비용 통과를 선언하지 않는다. 다운로드를 API proxy로 우회시키는 구조 변경은 이 작업에 포함하지 않는다.
- 공용 무료 구간·포함 사용량은 매장마다 반복 적용하지 않는다. 할인 전 동일 단가의 usage-based estimate와 계정 실제 billed amount·한 번만 적용한 quota를 따로 보고한다. D21 사전 시나리오는 동일 tariff의 무료 구간 차감 전 추정으로 보수적으로 평가하고, 실제 청구 통과는 정산 자료의 범위까지 별도 판정한다.
- source tombstone 시 비용 object 수명과 접근 상태를 갱신하되 이전 사용량 이력을 삭제하지 않는다. D20 사실·카드 보존과 Storage 과거 지출 보존은 양립한다.

## 5. 수집·계산에서 지킬 규칙

1. 가격표는 provider/model/mode/입출력·캐시·기타 billable units, 통화·시행일·공식 출처·요율 버전·반올림 기준을 고정한다. 모델 설정 문자열만으로 실제 단가를 추정하지 않는다. 실제 캠페인 전에 해당 시점 공식 요율을 확인하며 이번 계획에서 달러 단가를 발명하지 않는다.
2. 공급자에 token usage가 없는 STT는 제공 duration/청구 단위와 원본 메타데이터를 보존하고 요율 정의에 맞춰 계산한다. 음성 MB를 분으로 환산하거나 텍스트 token으로 대체하지 않는다. 측정 duration은 현재 probe의 정수 절삭을 피하고 정밀도를 보존한다.
3. usage가 있으면 JSON parsing·검증·fallback 전에 저장한다. 파싱 실패나 잘못된 카드 출력도 비용이 사라지지 않는다. 응답 전 timeout은 provider 청구 여부 UNKNOWN으로 남긴다.
4. app retry 안쪽의 실제 시도마다 기록한다. SDK 숨은 retry는 명시 시도로 제어하거나 transport 관측으로 드러내고, 불가능하면 관측 불완전으로 표시한다. 모델 재시도와 receipt 재저장은 서로 다른 키다.
5. local cache 재사용은 실제 새 provider 호출 0건과 재사용 근거 receipt를 표시한다. provider cache는 보고된 billable usage로 계산한다. STT/카드 재사용 평가를 최초 등록 전체 비용 0원으로 해석하지 않는다.
6. 실제 지출(INCURRED)과 기존 산출물을 재사용한 전체 경로의 비교 추정(RECONSTRUCTED)을 분리한다. 추정에 사용한 이전 receipt/hash를 연결하되 account/store 실제 합계에서 중복 합산하지 않는다.
7. Decimal/NUMERIC으로 곱하고 합계 후 정해진 통화 단위로 반올림한다. 단가·환율·사용량 중 필수 값이 없으면 total은 null이다. 측정된 0과 모름을 합치지 않는다.
8. provider billing 필드가 겹치는지 rate adapter에서 명시한다. 예를 들어 total과 cached 등의 부분합을 무조건 더하지 않는다. 같은 단위가 두 번 과금 계산되지 않는 fake response test를 둔다.
9. W의 현재 `run_extract_eval.py`가 외부 파이프라인 실행 동안 conn을 잡는 구간은 좁은 DB 작업으로 분리하고 trusted run/source context를 계측에 전달한다. 새 계측 때문에 shared connection을 병렬 작업에 넘기지 않는다.
10. real/mock·PRODUCT/EVALUATION 구분은 metadata에서 명시하며 직원·원본 민감 본문을 원가 로그에 복제하지 않는다. 모든 usage DB 조회/집계는 store_id 필수다.

## 6. 리포트와 집행

리포트는 CLI JSON + Markdown부터 구현한다. 새 비용 대시보드는 C0 선행조건에 넣지 않는다.

- 등록 리포트: 캠페인/run/source/단계별 실제 호출·재시도·토큰/초·bytes·등록 비용 I·부분합/미확정·예산환산 개월.
- 운영 리포트: 첫 7일/월, 첫 달/안정기, 질문/후속 턴·추가 자료·수정·Storage 저장/전송별 O_m, 3,000원 대비 여유·초과, p95·오류율/coverage.
- 시나리오 리포트: LOW/BASE/HIGH + 명확화/집중/보관 증가, 1/3/6/12개월 누적 지출, 예산잔여분 보전 개월과 불가/UNKNOWN 이유.
- 관측 리포트: 예상 시도 대 실제 receipt 수, COMPLETE/PARTIAL/UNKNOWN, 단위·가격·환율 누락, Storage UNALLOCATED, actual billed와 estimate 차이.
- 제외 비용 리포트: 서버·DB 고정비와 평가/개발 지출을 별도로 표시한다. 포함 변동비로 가장하거나 비용이 없는 것처럼 지우지 않는다.

원가 판정은 `PASS / FAIL / UNKNOWN`이다. known subtotal만으로 상한을 넘으면 FAIL, 미확정이 남고 아직 넘지 않으면 UNKNOWN, 필요한 변동비를 다 관측하고 고정한 시나리오에서 상한 이하면 PASS다. 전체 계정 actual billing과 일치 여부가 없으면 결과에 ESTIMATED를 표시하고 실제 청구 증거로 주장하지 않는다.

질문 초과 비용은 월별로 드러내며 첫 달을 안정기와 평균내 PASS로 만들지 않는다. 80% 예산 도달은 내부 관측 경보, 100%는 초과 경보다. 자동 과금·고객 업로드 차단·질문 차단은 도입하지 않는다. 예산을 넘는 시나리오가 확인되면 정확성을 유지하는 최적화·사용량 안내·상품 정책 중 제품 결정이 필요한 부분만 사용자에게 묻는다.

## 7. C0 순서와 분담

원가 계측 최소 계약을 C0-4의 `CP-00A/B/C`로 앞으로 옮긴다. 이 작업은 snapshot/발행 DTO에 의존하지 않아 기존 1패스·2패스 코드 모두에 붙일 수 있다. C0-2·C0-3 본구현/실험보다 우선하지만 보안 보완·C0 타입 오류 수정·문서 검토를 기다리게 하지 않는다.

| 작업 | 담당 | 산출물 | 선행/인수 |
|---|---|---|---|
| CP-00A | W usage·migration, R 읽기 소비 검토 | UsageContext/receipt/rate schema, nullable summary, price/phase/purpose, offline fake fixtures | 독립 MC0 migration·no network 계산 테스트; CP-01과 모듈 분리 병행 가능 |
| CP-00B | W extract/STT/storage, R embed/answer/metrics | 현재 호출부 계측, actual attempt/retry, 임베딩 단일 진입점, unknown 보존, store inventory/export 입력 | CP-00A; 기존 반환/API 호환, raw response parsing 실패 비용 보존 |
| CP-00C | W 등록 report·manifest, R 운영 report·질문 시나리오 | sample metadata 수집 계획, fake end-to-end cost report, 6개 입력틀·LOW/BASE/HIGH, freeze/재정산·Storage 대조 | CP-00B; 모든 필수 원가 반례 통과. actual live 측정은 권한·요율·dev 캠페인 별도 기록 |
| 이후 CP-02~04 | 기존 W/R | 공통 event/API schema·C0-3 fixture·C0-2 발행/삭제/경합 구현 | CP-00C와 CP-01 이후. 계측 test fixture를 제품 fixture와 공유 |
| CP-05 | R runner, W manifest | 새 품질 지표와 D18/D21 승격표 최종 통합 | CP-03 이후. 앞서 만든 계측/원가 계산을 재구현하지 않음 |

새 MC0 원가 migration은 기존 store/source/evaluation/extraction 식별자만 참조해 CP-04의 M0~M4보다 먼저 추가한다. store 범위 FK/unique·과거 run freeze·원가 report append-only를 검증한다. 종료 run에 알려지지 않은 과거 비용을 0으로 backfill하거나 freeze trigger를 해제하지 않는다. 신규 publication/fact 테이블을 선행 요구하지 않는다.

계측 연결의 기존 파일 담당은 유지한다. W는 `ingest/extract/gemini.py`, `preprocess/audio.py`, `preprocess/storage.py`, `run_extract_eval.py`, 공통 usage/schema/migration·rate manifest를 편집한다. R은 `reg/embeddings.py`, `learn/answering.py`, `team/runner.py`, `team/metrics.py`를 편집한다. 분류와 관계 판정은 W의 지식 흐름에 맞춰 한 명씩 편집자를 등록한다.

## 8. 검증과 완료 정의

필수 offline 반례는 다음과 같다. fixture는 합성 응답과 가상 요율을 쓰고 paid API를 호출하지 않는다.

1. 정상 extract/STT/embed/answer의 단계·store·run 귀속 및 summary 일치.
2. usage 전체 누락/부분 누락과 실제 0 구분, partial sum과 total=null.
3. STT duration 없음·단가 없음·환율 없음은 UNKNOWN, MB→분 임의 환산 없음.
4. 1회 실패 후 성공하면 실제 2시도·두 비용, 결과 JSON 파싱 실패도 비용 보존.
5. provider 응답 전 timeout은 UNKNOWN, provider 도달 전 취소는 근거가 있을 때 NOT_BILLABLE.
6. duplicate receipt finalize·배치 source 링크·report 재집계는 실제 지출 중복 없음.
7. cache hit·reuse-sources/reuse-cards·mock은 실제 지출과 재구성 전체비용을 구분.
8. 한 달 중간 생성·삭제 object의 byte-time, 파생 프레임·직접 다운로드·재시도 포함.
9. signed URL 발급만으로 전송비를 추정하지 않음, 귀속 불가 전송은 UNALLOCATED.
10. 고정비 제외·등록/운영/EVALUATION 분리, 무료 quota 중복 차감 없음.
11. 등록 6,000/운영 2,000 가상값에서 예산환산 2개월·잔여 예산 보전 6개월, 운영≥3,000에서 보전 불가.
12. 첫 달 HIGH 초과를 안정기 평균으로 통과시키지 않음, 상한 이하 partial은 UNKNOWN.
13. 종료 extraction run 동결 유지, 늦은 청구/가격 수정은 새 cost report, 과거 결과 불변.
14. 교차 store usage 조회/상호 연결 거절, ledger 시작/종료 저장 실패와 재시작 미확정 복구.

계획 완료는 원가 범위·가정·수집법·책임·선행·검증 조건의 고정이다. 계측 구현 완료는 CP-00A~C 코드와 offline/격리 DB 인수 통과다. 실자료 비용·운영 D21 통과는 실제 관측과 동결 workload/rate manifest가 있어야 별도로 판정한다. 사용자가 미래 사용량을 정확히 확정하지 못한다는 사실은 계획 완료의 차단 사유가 아니다.
