# R P3 — 실제 W 사실 카드 평가 입력 전환

2026-10-13 로컬 검증. 운영 배포·유료 모델 호출·품질 승격은 수행하지 않았다.

## 변경

- `run_r_operations_http.py`의 직접 카드 INSERT·자동 draft·RAW snapshot 전제를 제거했다. 새 `r_fact_evaluation.seed`가 OWNER_TEXT 자료 → W 원장 → mock 조립 → 초안 → 실제 공개 coordinator → 불변 snapshot을 사용한다.
- 기존 합성 정책 26개·12개 시나리오·24턴을 복제해 `w-fact-ledger/v1` 입력으로 동결했다. 원래 정책 문장과 질문·기대 답변을 유지하며, 정책별 고유 predicate를 부여했다. 이는 합성 추출 결과를 주입하는 fixture이며 실제 추출기의 정확도를 검증한 것이 아니다. 복합 문장을 임의로 원자화하거나 조건을 추정하지 않았다.
- 평가 fact ID마다 공개 fact revision, entity, card/version/block 참조와 provenance를 저장한다. 검색 후보는 정확한 card/version/block, 답변 인용은 추가로 fact revision까지 일치해야 해당 사실이 포함된 것으로 센다. 같은 카드의 다른 블록을 검색해도 정답 근거를 찾았다고 세지 않는다.
- 기본·일반 의미 경로의 양성/음성 대조는 별도 매장에서 실행한다. 대조용 사실은 채점 대상 snapshot에 들어가지 않는다. 일반 경로는 외부 제안·검증 응답만 합성 대역이며 서버 참조 검사·렌더링·HTTP·저장·인용 상세는 실제 코드다.
- 새 입력 hash, W/R 전체 Python·프롬프트·migration·fixture recipe의 source manifest/hash, 공개 snapshot/fixture hash를 기록한다. 유료 계획은 새 표현 및 evaluator source hash도 고정해야 실행된다. 합성 일반 경로 release는 별도 매장·snapshot·현재 runtime source에 결속되며 운영 승인 자료가 아니다.
- 대조 실패 시 채점 실행을 중단하고 결과를 남긴 뒤 비정상 종료한다. 미실행 시나리오/턴은 계획 분모에서 제거하지 않고, 선택지를 받지 못한 빈 대화는 성공으로 집계하지 않는다.
- 최신 live 보고서는 RAW↔사실 표현 또는 서로 다른 사실 입력 hash의 비교를 거절한다. 과거 전용 HTTP/live 보고서는 새 사실 캠페인을 거절한다. 과거 출력·점수 파일은 수정하지 않았다.

## 실행 결과

정본 증거: `output/r-fact-evaluation-20261013/no-provider-02/`.

| 검사 | 관찰 |
|---|---|
| 폐기용 PostgreSQL 17 | migration 50개를 빈 DB에 적용하고 실행 후 DB 삭제 |
| 실제 W 공개 | 정책 fact revision 26개, RAW span 0개 |
| 별도 대조 5건 | HOT 사실 답변, 온도 CLARIFY, 실제 ICE 선택 후 답변, 일반 의미 사실 답변, 잘못된 참조 거절 모두 통과 |
| 일반 의미 양성 | 합성 proposal 1회+verification 1회, 실제 receipt/원질문/OWNER_TEXT 인용 확인 |
| 일반 의미 음성 | 잘못된 revision → 503 GENERAL_INVALID_PROPOSAL, receipt/pending 생성 0건, verification 미호출 |
| 운영 질문 | 12개 시나리오·24/24턴 HTTP 200 및 receipt/원질문 일치, 세션 이력 조회 |
| 근거 후보 포함 | 필수 평가 fact가 정확한 블록 후보에 들어옴 24/24; 합성 고정 벡터이므로 검색 모델 정확도가 아님 |
| 답변 행동 | CLARIFY 24건, 기대 행동 일치 1/24. 일반 모델 OFF의 배선 확인이며 품질 통과가 아님 |
| 실제 외부 모델 | 0회. 합성 provider adapter 호출은 별도 표시 |
| 전체 API 회귀 | UTF-8 실행에서 2,385 passed / 6 skipped / 4 xfailed / 188 subtests passed. 기존 collector 호출부 2건 실패를 새 필수 controls 인자로 수정한 뒤 관련 39개 테스트 모두 통과 |

전체 로그는 `pytest-utf8.log`, 수정 후 관련 회귀는 `pytest-final-focused.log`다. 최초 기본 CP949 실행의 한글 문서 decoding 실패는 `pytest-full.log`에 별도 보존했다. 수정 후 전체 suite를 다시 통과했다고 합산 표기하지 않는다. 최종 evaluator source manifest가 실행 당시 코드와 일치함을 확인했고 임시 Docker 컨테이너도 종료했다. 이번 턴은 평가 scripts/tests/docs 변경이며 제품 API·DB schema·web 동작을 추가 변경하지 않았다.

입력 hash: `51120efe5c9adab89981eac5ab2e1ef3684c01987af44fe206d7f39d1f5c2835`.

`frozen-challenge.json`, `fact-card-map.json`, `published-snapshot.json`, `fixture-manifest.json`, `evaluator-sources.json`, `controls.json`, `control-snapshot.json`, `control-fact-map.json`, `synthetic-control-release.json`, `run.json`으로 입력부터 출력까지 추적할 수 있다. 첫 실행 `no-provider-01`은 source manifest 확장 전 확인 기록으로 보존했다.

재현 명령(api 디렉터리, 로컬 55440 포트의 폐기용 PG17 필요; 출력은 새 경로):

```powershell
.venv/Scripts/python.exe scripts/run_r_operations_http.py --input ../output/r-fact-evaluation-20261013/fact-challenge.json --output ../output/r-fact-evaluation-20261013/new-run
```

## RAW·knowledge_loop 보존 결정

| 사용처 | 현재 역할·결정 |
|---|---|
| `contracts/card.py`, `snapshot.py`, `answer.py`, `chat.py`, `hashing.py`, `validate.py` | 과거 snapshot·AnswerPlan·인용의 RAW 참조를 파싱하고 hash/참조를 검증한다. 삭제 시 과거 응답 계약이 깨지므로 유지 |
| `reg/index_preparation.py`, `reranker.py` | 호환 content의 RAW 색인 문장/후보를 읽는다. 새 W 공개가 RAW를 생산한다는 의미가 아님. 호환 검증과 함께 유지 |
| `learn/planner.py`, `approved_renderer.py`, `answer_validation.py`, 일반 의미/계산/검증 모듈 | 고정 snapshot의 RAW 선택·적합성·원문 렌더링을 지원한다. typed 사실 경로로 새 평가를 옮겼지만 과거 테스트를 폐기하지 않음 |
| `learn/answer_storage.py`, `v2_router.py` | 과거 receipt·원문 인용을 읽는다. 새 OWNER_TEXT fact provenance와 별개로 과거 불변 참조 보존 |
| `publish/content.py` | 새 생산 경계는 사실 전용. 이번 실제 W snapshot도 RAW 0건 확인 |
| `learn/knowledge_loop.py` | v1 router 및 W worker의 제품 호출 없음. 정의와 과거 unit/DB 검증만 남음. 평가 전환과 함께 무조건 삭제하지 않고 호환 검증을 별도 정리할 때 제거 |
| `test_knowledge_loop.py`, `test_r_owner_candidates.py`, `test_w_classify_relation_usage.py`, `verify_r_owner_candidates.py`, `verify_w_classify_relation_usage.py` | 과거 관계 분석/비용·후보 계약의 검증 호출. 현재 제품 처리의 근거로 해석하지 않음 |

검색 목록은 같은 output 폴더의 `raw-consumer-inventory.txt`, `knowledge-loop-inventory.txt`에 보존했다. 이번에 제거한 RAW 생산 전제는 HTTP 평가 러너의 old seed이며, 공통 enum·과거 hash 계약·인용 컬럼·migration은 삭제하지 않았다.

## 다음 P4

사건별 적용성, 사용자 원문과 결론 표현의 과도한 문자 일치 검사를 새 사실 fixture 기준으로 회귀 검증한다. 일반 의미 해석에서 분할 카드의 표시 제목과 확정 entity 이름을 비교하는 잔여 경로도 확인한다. 이번 대조는 모든 복합 정책·분할 카드의 일반 대화 품질을 보장하지 않는다.

그 뒤 사람 검토 truth·실제 검색·예산·반복·holdout을 고정한 별도 유료 캠페인이 필요하다. 현재 24건 CLARIFY를 개선율·정답률·운영 인수로 사용하지 않는다.
