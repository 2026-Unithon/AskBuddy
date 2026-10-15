# W→R 인계 R 할 일 닫기와 계약 결정 2건 — 2026-10-15

기준 `main` `e34c9b4`(PR #58 머지 뒤). 담당 R.
대상 문서: [W→R 공개 인계](../plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md) "R 이 할 일".
근거가 되는 구현·검증: [P1](R_OWNER_FLOW_20261013.md) · [P2](R_FACT_CONSUMPTION_20261013.md) ·
[P3](R_FACT_EVALUATION_20261013.md) · [P4](R_P4_CASE_CONTEXT_20261013.md) ·
[통합 계획 §4 G-A 표](../plan/RW_NEXT_EXECUTION_20261012.md).

**이 기록의 범위:** 구현이 인계 요구를 충족하는지의 R 판정이다. 실제 모델 품질·운영
p95·승격은 여기서 닫지 않는다. 이번 턴에 유료 호출·배포·DB 변경은 없다.

## 0. 증거의 종류를 구분한다

| 표시 | 뜻 |
|---|---|
| `[코드]` | 2026-10-15 에 이 기준 commit 의 소스를 직접 읽어 확인 |
| `[GA]` | 2026-10-13 세션의 G-A 인수 실행(합성 API·폐기용 PG17). 그 세션의 출력물이 증거 |
| `[결정]` | R 이 이번에 내린 판단. 코드 변경이 아니라 판정 |

처음 판정할 때는 Docker 엔진이 없어 `[GA]` 를 2026-10-13 기록 인용으로만 적었다.
**같은 날 Docker 를 켜고 재실행했다 — 결과는 §6.** 아래 표의 `[GA]` 는 그 재실행으로
오늘 다시 확인됐다.

## 1. 닫는 항목

| # | 요구 | 판정 근거 |
|---|---|---|
| 2 | `RawSpan.source_id=None` 소비 경로 보완 | **닫힘.** `[코드]` `publish/content.py:353` 이 `raw_spans=()` 를 고정으로 돌려주고, 블록 없는 판은 같은 함수가 `InvalidContent` 로 공개를 거절한다(`:332-335`). 점주 답변 RAW 경로가 없어져 요구 자체가 사라졌다. `W_OWNER_ANSWER_RAW_PUBLISH` 도 함께 닫힌다 |
| 5 | v1 즉시 공개를 worker·`approve_owner_proposal` 로 이전 | **닫힘.** `[코드]` `publish_new_proposal`·`publish_existing_proposal`·`prepare_proposal`·`create_owner_answer_card` 는 `api/app/` 어디에도 없다(grep 0건). W 가 지워도 R 이 깨지지 않는다 |
| 7 | 공개판 없는 매장은 빈 후보 | **닫힘.** `[코드]` `reg/owner_candidates.py:19-22` — 승인·공개된 카드가 하나도 없으면 색인을 읽기 전에 `[]` 를 돌려준다. 새 매장의 첫 점주 답변이 막히지 않는다 |
| 10-a | 카드 제목이 아니라 대상 이름·별칭으로 찾기 | **닫힘.** `[코드]` `learn/entity_names.py` 가 승인 snapshot 의 `subject` + 카드 제목을 대상 이름 집합으로 만들고, `planner.py:97·99·101·145` 가 그 집합으로 매칭한다. 제목에 ` 2/3` 이 붙은 분할 카드도 같은 대상으로 회수된다 `[GA-01]` |
| 10-b | 판마다 `entity_id` 가 바뀌는 상황 | **닫힘.** 레거시 RAW 카드와 `knowledge_apply` 의 블록 없는 판 공개가 모두 사라져 `entity_id` 가 카드 id 로 되돌아가는 경로가 없다 `[코드]` (2 번과 같은 가드). §3-2 와 함께 본다 |
| 10-c | 렌더러·색인·인용 검증이 사실 블록 snapshot 을 받는가 | **닫힘.** `[GA-01·GA-02]` 실제 W 원장→조립→공개로 만든 사실 카드로 검색·답변·인용 저장까지 통과. 규격 머리줄 중복과 D19 CLARIFY 뒤 해당 규격만 인용하는 것 포함 |
| 10-d | MESSAGE locator `line` 수용 | **닫힘.** `[코드]` 원장의 `MESSAGE` 를 공개 계약의 `LINE` 으로 옮긴다(`publish/content.py:82-84`). 옮기지 않으면 `WHOLE_SOURCE` 로 낮아져 줄 위치가 사라졌다. `learn/citation_origin.py` 가 그 locator 를 그대로 인용 상세에 싣는다 `[GA-04]` |
| 10-e | 과거 판 인용의 재현 | **닫힘.** `[GA-03]` 추가·정정·삭제·재정렬 → 재승인 뒤에도 새 질의는 새 판, 옛 인용은 당시 판을 가리킨다 |
| 11-a / 12-f | 점주 답변·직접 입력 출처 표시 | **닫힘.** `[코드]` `learn/citation_origin.py` 가 `source_kind` 를 `OWNER_ANSWER`(답변에서 온 것) / `OWNER_TEXT`(사장님 직접 입력) / `SOURCE`(파일) / `UNKNOWN` 으로 가른다. 자료 제목 문자열이 아니라 `owner_answer_sources` 관계와 사실 provenance 로 판정한다 |
| 11-b | 점주 편집 판이 실린 snapshot 소비 | **닫힘.** `[GA-03]` 10-c 와 같은 실행 범위 |
| 11-c | `OWNER_REMOVED` 제외가 R 계산에 영향 없음 | **닫힘.** `[코드]` 공개 내용은 `card_block_facts` 에 남은 사실만으로 만든다(`publish/content.py:325-333`). 제외된 occurrence 는 공개 snapshot 에 실리지 않으므로 R 계산 입력이 아니다. 과거 답변의 사실을 소급해 지우지도 않는다 `[GA-03]` |
| 12-a | 10 번을 Phase A 배포 전에 끝낼 것 | **닫힘, 다만 순서가 뒤집혔다.** Phase A 는 2026-10-11 에 이미 배포됐고(Deploy 기록 `770659b`) R 검토는 2026-10-13 에 끝났다. "배포 전" 조건은 지켜지지 않았다. 사후 검토 결과로 닫되 지켜진 것처럼 적지 않는다 |
| 12-c | `knowledge_loop` 가 R 에서 안 쓰이게 되는가 | **닫힘(부분 보존).** `[코드]` `build_knowledge_plan` 을 부르는 제품 경로는 0건이다(`app/` 안에서는 주석 한 줄뿐). 모듈 자체는 **지우지 않는다** — 같은 파일의 `find_owner_answer_candidates` 는 점주 답변 후보 검색에 지금도 쓰인다 |
| 12-d | v1 `/pending/{id}/answer` 가 옛 함수에 기대는가 | **닫힘.** 5 번과 같은 근거. 기대하지 않는다 |
| 12-e | 제안 화면이 바뀐 `relation_type` 값에 맞는가 | **닫힘.** P1 에서 제안 API 가 승인 가능 여부·차단 사유·영향 카드 목록을 주고, `NO_FACTS`·`FACTS_PENDING`·오류에 공개 버튼을 내보내지 않는다 `[GA-05]` |
| 12-g | 1회 삭제 뒤 ①빈 공개판 ②빈 상태 ③옛 채팅 ④빈 후보 | **닫힘.** `[GA-07]` 네 가지 모두 확인. ④는 `[코드]` 7 번과 같은 가드 |
| 14-a | v1 점주 답변·제안 화면 정리 | **닫힘.** `[코드]` `web/` 에 `answerPending`(v1 `/learn/pending/{id}/answer`) 호출부가 없다 — 목록은 상세로 보내고 상세가 v2 `rOwnerAnswer` 를 쓴다. **제안 승인은 v1 URL(`/learn/knowledge-proposals/{id}/approve`)을 그대로 쓴다** — 그 라우트의 내부가 이미 `approve_owner_proposal` + `finish_owner_review` 라서, URL 모양만 보고 새 API 를 중복으로 만들지 않기로 했다(P1 결정) |
| 14-b | 1회 삭제 뒤 `r_owner_knowledge_states` 잔여 | **닫힘.** `[코드]` `learn/knowledge_availability.py` 가 완료 이력은 보존한 채 현재 공개 여부를 `CURRENT`·`CHANGED`·`UNAVAILABLE`·`NOT_APPLICABLE` 로 따로 읽는다. 지워진 카드를 가리키는 상태 글은 `UNAVAILABLE` 로 나온다. 행을 지우는 migration 은 만들지 않는다 |
| 14-c | W 가 고친 R 검증 3개 확인 | **닫힘(읽기 확인까지).** `[코드]` `verify_r_legacy_publication.py`·`verify_r_w3_consumer.py`·`verify_r_owner_candidates.py` 가 모두 사실 카드 픽스처로 바뀐 것을 확인했다. `verify_r_owner_candidates.py` 의 "DB 연결이 모델·추출 호출 중에 풀려 있음" 으로 바뀐 의미도 타당하다. **세 스크립트를 2026-10-15 에 실제로 재실행해 통과를 확인했다**(§6) |
| 15 | 작업 완료 알림 문구 | **닫힘.** `[코드]` `notifications/service.py:126` — "자료가 반영된 카드 N개를 확인해 주세요. 공개 여부는 카드에서 확인할 수 있어요." `card_count` 의 새 의미와 맞고 승인 전 상태를 과장하지 않는다 |

## 2. 남기는 항목

| # | 요구 | 왜 아직 안 닫는가 |
|---|---|---|
| 3 | 옛 준비본 정리(5-2)의 보관 개수 N·일수 M | **W 와 함께 정할 값이다.** R 제안: 활성 공개판 + 직전 2판(N=3), 7일(M=7). 근거는 PARTIAL 재시도·롤백 창이 하루를 넘지 않는 현재 운영뿐이라 약하다. W 가 발행 빈도를 보고 맞춰 주면 그 값으로 켠다 |
| 6 | `card_embeddings` 읽는 옛 경로 정리 후 삭제 migration | 미착수. `/reg/retrieve` 와 평가 러너가 아직 읽는다. 표 삭제는 되돌리기 어려워 W 와 순서를 합의한 뒤 한다 |
| 13 | Phase B·C 확인 | W 가 아직 구현 전이다. 아래 §4 에 R 답을 미리 적어 둔다 |

## 3. R 결정 2건

### 3-1. RAW 공통 계약은 지금 지우지 않는다 (12-b)

**결정: 유지.** 새 RAW 생산은 이미 0이지만, 계약에서 `RAW`·`RawSpan` 을 빼는 것은 별개 작업이다.

근거:

1. **snapshot hash 가 전부 바뀐다.** `contracts/hashing.py` 의 `knowledge_content_payload` 는
   `raw_spans` 키를 **항상** payload 에 넣는다(빈 목록이어도 키가 들어간다). 계약에서 빼면
   같은 승인 내용의 hash 가 달라진다. "이 답변은 그때 그 지식으로 냈다" 를 증명하는 값이
   흔들리는 것은 인용·색인·멱등 재발행이 서로를 믿는 근거를 깨는 일이다.
2. **`contracts/*` 는 W·R 공동 변경이다**(CLAUDE.md). R 이 단독으로 줄일 수 없다.
3. 지금 지워서 얻는 것은 코드 몇 군데의 분기 제거뿐이고, **새 RAW 가 안 만들어지는 것은
   이미 공개 함수가 보장한다**(`raw_spans=()` 고정 + 블록 없는 판 거절).

따라오는 조치:

- `verify_r_owner_citations.py` 는 **지우지 않고 계약 호환 회귀로 남긴다.** 손으로 만든
  snapshot 으로 RAW 소비 경로를 검사하므로, 실제 W 산출물과 무관하게 계약이 살아 있는
  동안의 회귀 가치가 있다. 다만 "실제 W 흐름" 검증이 아니라는 표시를 유지한다.
- 삭제는 **hash 계약 변경을 동반하는 별도 공동 작업**으로 남긴다. 그때 DTO·schema·fixture·
  과거 이력 파싱을 함께 바꾸고 재발행 영향을 검토한다.

### 3-2. `entity_id` 이름공간은 나누지 않고 닫는다 (10-f / 12-h)

**결정: 계약 분리를 하지 않는다. 항목을 닫는다.**

근거:

1. 충돌의 조건은 "레거시 카드의 `entity_id`(= `card_id`)와 사실 대상 `entity_id` 가 같은 숫자
   공간을 쓰는 것" 이었다. Phase A 의 1회 삭제로 레거시 카드가 사라졌고,
2. 새로 생길 경로도 막혀 있다 — 블록 없는 판은 공개 단계에서 거절되므로(`InvalidContent`)
   `entity_id` 자리에 카드 id 가 들어오는 판이 만들어지지 않는다 `[코드]`.
3. 쓰지 않는 구분을 계약에 넣으면 `contracts/*` 와 `validate.py` 가 공동 변경 대상이 되고,
   W·R 양쪽의 검증기가 동시에 바뀌어야 한다. 얻는 안전은 이미 데이터와 가드가 준다.

되돌릴 조건(이게 생기면 다시 연다): 블록 없는 판을 공개하는 경로가 새로 생기거나,
카드 id 를 `entity_id` 로 싣는 다른 생산자가 들어올 때.

## 4. Phase B·C 에 대한 R 답 (13번, 미리)

| 소항목 | R 답 |
|---|---|
| (a) 점주 답변 화면 첨부 UI | **점주 답변 화면은 R 소유가 맞다**(`web/app/owner/questions/*` 를 R 이 P1 에서 고쳤다). W 가 업로드·첨부 API 를 준비하면 **R 이 UI 를 붙인다**: 파일 선택 → `POST /ingest/upload-url` → W 첨부 API → 업로드 완료 전에는 제출 버튼을 켜지 않는다 |
| (b) 모르는 자료 종류 표시 | **이미 안 깨진다.** `citation_origin` 이 아는 종류(VOICE·VIDEO·KAKAO·SCAN·OWNER_TEXT) 밖이면 `UNKNOWN` 으로 떨어뜨린다. docx·hwp·avi 가 `SCAN`·`VIDEO` 로 들어오면 기존 라벨을 그대로 쓴다. 다만 **사용자에게 보일 한국어 라벨은 web 에서 확인이 필요**하다 — Phase B 머지 시 함께 본다 |
| (c) 사실 `ext` | 지금 할 일 없음. 답변 근거로 쓰려면 그때 공개 계약을 검토한다 |
| (d) 공지 `store_notices` | 지금 할 일 없음. R 답변 근거로 자동 편입하지 않는다 |
| (e) 직원 화면 주 편집자 | **확인 필요.** 직원 채팅(`web/components/r-v2-chat.tsx`·`staff/ask-screen.tsx`)은 R 이 고쳐 왔다. 상단 공지 버튼·매장 지식 탭이 그 파일들을 건드리면 R 이 맡는 편이 낫다. Phase C 계획 때 W 가 범위를 주면 확정한다 |

## 5. 이번 턴에 한 것과 안 한 것

- 한 것: 위 판정에 쓴 소스 읽기, 인계 문서의 R 할 일 체크 갱신, 결정 2건 기록, §6 의 재실행
- 안 한 것: 제품 코드 변경 0, 운영 DB 변경 0, 유료 호출 0
- W 에게 전할 것: 10·11·12·14·15 가 닫혔으므로 **W3-4 를 완료로 표시할 수 있다.** 3·6 은
  W 와 함께 정할 값이 남아 있다

## 6. Docker 복구 뒤 재실행 (2026-10-15)

폐기용 `pgvector/pgvector:pg17` 컨테이너(55439·55440)에서 실행했다. 실행 뒤 DB·컨테이너는
정리했다. 운영 DB 는 건드리지 않았다.

| 실행 | 결과 | 이 기록의 어느 항목을 받치는가 |
|---|---|---|
| `verify_r_schema_rebuild.py` | **exit 0** — migration 50개, PostgreSQL 17.11, `PASS WA all scenarios`, 로그 1,242줄 | 아래 전부의 토대 |
| ├ `verify_r_owner_candidates` | `draft-only store has no approved candidates` / `provider sees no held pool connection` / `legacy embeddings are absent` | **7 번**(빈 후보)·**14-c** |
| ├ `verify_r_w3_consumer` | `initial empty publication → durable first pending` / `W ledger fact → search → answer → typed owner citation → history replay/detail` / `forged fact origin and referenced owner deletion blocked` | **10-c**·**14-c** |
| ├ `verify_r_legacy_publication` | `last exclusion publishes empty snapshot and restoration returns card` 외 2건 | **12-g**·**14-c** |
| ├ `verify_r_legacy_owner_flow` (P1) | `PASS P1` 22건 | **12-e**·**14-a** |
| ├ `verify_r_fact_consumption` (P2) | `PASS P2` 22건 — 분할 카드 3장, 제목이 아닌 subject 로 소비, ICE 선택 시 ICE 사실만 | **10-a**·**10-c**·**11-b** |
| ├ 1회 삭제 리허설(WA a) | 평가 기록이 있으면 migration 이 멈춤 / 완료 이력은 남고 현재 공개 상태는 `UNAVAILABLE` / 빈 공개판 생성 / 근거 없음 → ESCALATE / 초기화 뒤 첫 점주 답변이 새 사실 카드로 공개 | **12-g**·**14-b** |
| └ 카카오 DB 통합 | 6 passed | 회귀 |
| `verify_r_p4_case_context.py` | **exit 0**, `zero paid calls` | P4 회귀 |
| `run_r_operations_http.py` 24턴 | **exit 0** — 시나리오 12 / 턴 24 / HTTP 200 24 / receipt 24 / 필수 사실 후보 포함 24 / CLARIFY 24 / 기대 행동 일치 1. **2026-10-13 기록과 같은 수치** | 평가 입력 회귀 |

**이 재실행이 바꾸지 않는 것:** 12-a 의 "Phase A 배포 전" 순서는 여전히 지켜지지 않았고,
실제 모델 품질·운영 p95 는 여전히 미인수다. 24턴의 `CLARIFY 24` 는 일반 모델 OFF 상태의
배선 확인이지 품질 통과가 아니다.
