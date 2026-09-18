# main 통합 후 R 잔여 작업 — 2026-09-18

2026-09-18 추가 구현·검토: [R 후속 현재 판정](R_FOLLOWUP_REVIEW_20260918.md). v1 새 질문 차단·v2 진입, 점주 재처리 UI·발행 갱신, 실제 v2 격리 모델 비교·사람 판정 보고, 용어 불변 수입을 추가했다. 일반 의미 판단의 제품 승격·실자료 품질·실제 W 종단 인수는 미완료다. 아래는 이전 시점 기록이다.

## 기준과 판정

`codex/r-semantic-support-boundaries`에서 `git pull --no-rebase origin main`을 실행해 `44a6a9d` → `1d49133`으로 fast-forward했다. 기존 미커밋 파일은 stash에 보존 후 복원했다. TODO 충돌은 양쪽 기록을 보존해 해결했다. stash 백업은 삭제하지 않았다.

앞선 `R_SUPPORT_BOUNDARIES_20260918.md`는 pull 전 legacy 관찰이다. 이제 `r-explicit-slots/v7`, chat v2, hybrid, 사전, 의미 묶음, R migration 5개가 존재한다. 아래가 현재 판정이다. 사용자는 승인 snapshot·사람 정답·W worker가 별도로 없는 것으로 회신했다. 그 의존성이 있는 품질·공동 인수는 미완료다.

| 순서 | 이번 산출물 / 상태 | 남은 외부 조건 |
|---|---|---|
| 1 지원 경계 | 아래 표와 기존/신규 합성 테스트로 현재 경계 고정 | 실자료 일반화는 별도 |
| 2 일반 의미 판단 | `semantic_proposals.py`: 자유 질문·사용자 턴·서술형 RAW·조건/예외·묶음 후보를 받는 모델 제안 경로와 오프라인 비교 CLI 구현. 기존 planner 유지, 평가 전용 | 사람 평가 전 제품 활성화 금지. 모델의 의미 정확도 미검증 |
| 3 사전·검색 | 두 매장 내부에 출처 사실과 연결된 용어 검토 틀 생성, 실제 관찰 변형 입력칸 준비. query expansion은 효과 근거가 없어 보류 | 실제 별칭/오타/STT 관찰과 승인, 짝비교 |
| 4 캐시·로그 | 검색 캐시 없음 확인. 별칭 원문 메타데이터를 hash로 교체, 예외 로그 원문 제거. 30일 메타데이터 삭제·DB 접근 제어·서버 정리 루프·CLI 구현 | 호스팅 stdout 보존/접근 설정은 배포 환경에서 확인 |
| 5 자동화 | `.github/workflows/r-validation.yml`: unit/계약, PG17 전체 재구축·DB, 프론트 check·브라우저와 실패 집계 `r-required` 연결 | 초기 push Actions 35311008713 전 job 통과. 후속에서 main 필수 r-required/strict 설정 완료 |
| 6 실자료 정답 | 두 매장 각 40개 초안/37개 서로 다른 문구 재확인. 읽기 쉬운 worksheet와 검토 JSON 준비 | 각 매장 사람 검토 0개. 매장 사실을 자동 승인하지 않음 |
| 7 최신 DB | 최신 R migration 포함 28개 재구축, 기존 DB/API 검사와 보존 검사 13개 통과 | 운영 DB 적용은 하지 않음 |
| 8 실제 성능 | 기존 고정 snapshot·정답·반복·A/A 평가 하네스 보존, 합성 회귀 재검증 | 승인 snapshot/정답 부재로 실제 검색·의미·비용/지연 성능 평가 미실행 |
| 9 W 공동 연결 | R prepare/activate·원자 발행·실제 DB claim/fencing/FAQ/직원 전달 계약 재검증 | `claim_owner_event`/`finish_owner_event`를 실제로 연결하는 W worker 부재. 공동 종단 완료 아님 |

## 현재 지원 경계

지원은 명시된 제한 범위에만 적용한다. 높은 검색 점수 또는 모델 참조 검증 통과를 의미적 충분성으로 보지 않는다.

| 범위 | 지원 예 | 미지원/차단 반례 | 검증 |
|---|---|---|---|
| 일반 질문 | `HOT 라테 우유 얼마나?` 같은 전체 문법의 대상·속성·규격 | `HOT 라테 우유 몇일 보관해?`를 우유량으로 답변 금지; 자유 동의 표현은 검증 필요 | `test_r_planner.py`, `test_r_remaining_sequence.py` |
| RAW | 단일 원자 수량, 명시적 승인 Q/A, 절차 제목이 있는 전체 RAW, 명시적 승인 원문 열람 | 제목 없는 일반 서술을 업무 답변으로 자동 승인 금지; 원문 열람과 업무 적합성 분리 | `test_r_raw_quantity.py`, `test_r_raw_evidence.py`, `test_r_raw_original.py` |
| 조건/예외 | 승인된 명시 조건의 결합, 제한된 괄호 OR, 같은 단위 수치 범위/예외 | 누락 조건, 모순 조건, 임의 중첩·단위 추론·자유 표현은 자동 통과하지 않음 | `test_r_conditional_scope.py`, `test_r_numeric_scope.py`, `test_r_exception_and_grouping.py` |
| 후속 문맥 | 서버 발급 문맥의 확인된 옵션 선택, 매장/회원/세션/TTL/판 검사 | 자유 후속 문장의 대상 추론, 타인 문맥, 만료·stale 선택 차단 | `test_r_question_contexts.py`, `verify_r_context_stale.py`, `verify_r_v2_api.py` |
| 의미 묶음 | 완전히 해석된 명시 대상/속성/규격/조건/예외 키 | 불확실한 후속 문장·다른 조건·규격은 병합 금지 | `test_r_semantic_grouping.py`, `test_r_remaining_sequence.py`, 실제 DB occurrence 검사 |
| 모델 제안 | 승인 후보 참조·행동·인용된 사용자 표현·동일 의미 질문 ID 제안 | 후보 밖/오래된 참조, 다른 매장·입력 hash, 임의 assessment, 사용자 입력 밖 인용, 후보 밖 묶음 ID 차단 | `test_r_semantic_proposals.py` |

`test_r_semantic_boundaries.py`의 4개 strict xfail은 pull 전 legacy helper의 한계 기록이다. 현재 v2 planner가 그 helper를 의미 검증기로 사용한다는 주장이 아니다. xfail은 통과나 제품 품질 증거에 포함하지 않는다.

## 모델 제안 경로의 계약

`proposal_input`은 승인 snapshot hash와 후보 version을 검증하고, 질문·최대 10개 사용자 턴·최대 20개 비교 질문·승인 후보를 전체 입력 hash에 결속한다. 후보 RAW는 제목 없이도 입력에 포함된다. 모델이 해석을 제안할 수 있지만 값/조건/슬롯을 사용자 확정으로 바꾸지는 않는다.

`SemanticProposal`은 `AnswerPlan`과 슬롯 근거 인용·불확실성·비교 질문 ID만 받는다. 자유 답변/assessment 필드는 거부한다. 공통 승인 참조·dependency 검증과 검색 후보 포함 검사 뒤에도 결과는 항상 `REVIEW_REQUIRED`, `production_eligible=false`다. `Decision`이나 저장 가능한 `ResolvedSelection`을 반환하지 않는다. 묶음 제안도 pending 키가 되지 않는다.

실제 SDK 어댑터는 기존 모델 설정을 사용하고 재시도 1회 설정, 입력 상한, 제한 시간, 정리 기한을 갖는다. ANSWER/EVALUATION 원장과 evaluation_run_id가 필수다. 호출 전 저장 실패는 provider를 호출하지 않고, timeout/잘못된 응답은 별도 상태다. 실제 provider 호출은 이번 작업에서 실행하지 않았다. SDK는 합성 응답으로 계측 순서를 검증했다.

오프라인 비교는 사용자 질문·승인 snapshot·검색 후보가 담긴 JSON으로 실행한다. `--proposal`을 생략하면 모델 입력을 준비한다. 출력은 overwrite하지 않는다. 실제 매장 입력/출력은 반드시 해당 `api/eval/data/store-*/r-review/` 내부에 둔다.

```powershell
# api 디렉터리, 아래는 합성 재현 파일
.\.venv\Scripts\python.exe scripts/compare_r_semantic_proposal.py --input tmp/r-semantic-replay/input.json --proposal tmp/r-semantic-replay/proposal.json --output tmp/r-semantic-replay/comparison-new.json
```

비교 결과에는 기존 plan과 제안 plan이 함께 남는다. 자유 표현, 제목 없는 RAW, 중첩/수치 예외, 후속 문맥, 잘못된 병합을 각각 사람 라벨로 판정해야 한다. 모델이 낸 `unresolved`나 구조 유효성으로 정답 라벨을 만들지 않는다. 검색 누락/충분성 오판/과차단/인용/병합 오류를 나눠 같은 고정 분모로 반복 평가한 뒤에만 활성화 범위를 다시 결정한다.

## 사전와 검색 확장 결정

현재 승인 사전은 불변 glossary_version에 고정되며, lexical/vector 독립 회수 뒤 융합한다. 검색용 조사 토큰 OR 확장은 이미 있다. 추가 모델 query variants는 이번에 활성화하지 않았다. 용어 검토의 실제 관찰 변형을 채운 뒤 무사전/사전, lexical/vector/hybrid, reranker on/off를 같은 정답·snapshot으로 비교한다. 별도 확장은 남은 검색 누락에서 필요성이 확인된 범위에만 추가한다. 사전 승인 전 용어는 검색·슬롯 확정에 사용하지 않는다.

## 보존·접근·migration

`hybrid.py`의 검색 결과는 캐시하지 않는다. `answer_storage._receipt`의 24시간 재전송은 요청 멱등성으로, 새 질문의 검색 캐시가 아니다. 회원/세션 scope와 body hash를 검사하는 기존 경로를 유지한다.

`execution_metadata`는 30일이 지나면 제거한다. `policy_receipt_id`는 정책 확인의 중복 방지 관계이므로 남긴다. 원래 질문·응답·인용·문맥·원가 원장은 대화/감사 계약이며 일반 진단 로그가 아니다. 이 migration은 이들을 삭제하지 않는다. 30일 지난 평가의 진단 누락을 0 비용이나 성공으로 취급하지 않는다.

서버 기동 직후 및 매시간 `retention_loop`가 비활성 매장까지 정리하고, 답변 저장 시에도 해당 매장을 정리한다. 따라서 정상 실행 중 최대 한 sweep 간격의 지연이 있다. 중단 기간에는 정리되지 않으며 재기동 때 다시 시도한다. 실패 로그는 예외 타입만 남긴다. DB trigger는 오래된 메타데이터 제거만 허용하며 답변 내용 변경, 신선한 metadata 변경, 인용 변경을 계속 거부한다. 브라우저 anon/authenticated는 receipt와 인용 원장 직접 접근 및 purge 실행을 할 수 없다. 서버 API의 매장/회원 검사는 그대로다.

수동 점검/복구는 `R_MAINTENANCE_DSN`을 명시한 환경에서 `python scripts/purge_r_metadata.py --store-id <id>`로 dry-run, `--apply`로 정리한다. 실제 운영에서는 신규 migration 적용 후 API를 올린다. API 중단 시 운영 스케줄러에 같은 명령을 연결할 수 있다. 호스팅 stdout의 접근·30일 보존은 이 저장소만으로 입증하지 못한다.

기존 로컬 신규 W migration과 R migration이 `20260917110000`으로 충돌해 W 파일을 `20260917150000_ingest_job_lease.sql`로 이동했다. 본문은 변경하지 않았다. 보존 migration은 `20260918090000_r_metadata_retention.sql`이다. 과거 외부 DB에 옛 W 번호를 적용했다면 이력 대조가 필요하며 이번에는 운영 DB에 접근하지 않았다.

## 검토 자료와 남은 입력

`prepare_r_review_queue.py`, `prepare_r_review_materials.py`를 store-a/store-b 각각 실행했다. 초안 각 40개/서로 다른 문구 37개/검토 완료 0개. 용어 검토 행은 각각 58/27개다. 이 수치는 실제 별칭 수가 아니라 원본 사실의 대상별 검토 행 수다. 관찰한 변형·출처·검토자·승인 버전은 아직 비어 있다.

각 private r-review 디렉터리에 worksheet, queue, term-review가 있다. `judgments.json`과 `approved_snapshot.json`을 사람이 완성하면 `finalize_r_dev_review.py`가 완전성·참조·hash를 검증한다. 실제 평가와 W worker 종단은 이 입력이 없는 것으로 사용자도 확인했으므로 완료 체크하지 않는다. holdout은 열지 않았다.

## 검증 결과

- 단위/API: **779 passed, 4 xfailed, 119 subtests passed**. 최종 실행 결과는 `api/tmp/r-unit-20260918.log`에 보관. 기존 legacy xfail은 별도 집계한다. Starlette/AnyIO deprecation warning 1개가 있으며 실패는 아니다.
- schema 15개·공유 fixture 3개 최신 확인.
- PG17.11/pgvector: migration 28개 재구축. 원장14, 보안9, embedding6, W 인계6, score4, 문맥21, 색인40, reranker13, 답변저장16, v2 API101, 점주전달45, 보존13개 검사 통과. 원본 보존·정책 링크 유지·다른 매장·브라우저 권한·재정리 멱등성 포함.
- `pnpm check`: lint 경고 0, typecheck, production build 통과.
- 실제 Edge 브라우저 + 합성 API: 27 checks 통과. DB와 W worker를 연결한 브라우저 E2E는 아니다.
- 합성 snapshot의 모델 제안 비교 CLI 실제 실행: `REVIEW_REQUIRED`, `production_eligible=false`; 기존/제안 plan 출력 확인.
- CI 세 job의 결과가 모두 success여야 `r-required`가 통과한다. 초기 원격 실행 35311008713 전 job 통과, 후속에서 main 필수 r-required/strict 설정 완료. 최신 결과는 후속 기록 참조.
- 유료 모델 호출·실자료 품질 실험·운영 DB 변경·원격 push는 하지 않았다.

## Push 대상 분리 검증

후속 push 요청에서 기존 W/릴리스 미커밋 변경을 제외하고 R 파일과 main.py의 retention 수명주기만 스테이징했다. 그 Git 트리를 별도 디렉터리에 추출하여 **773 passed, 4 xfailed, 119 subtests passed**, PG17 **27개 migration 재구축 및 전체 DB/API 검사 통과**를 확인했다. 위의 779/28은 W 로컬 작업까지 포함한 결과이며 push되는 R 변경의 수치와 구분한다. W ingest lease 파일과 복구·릴리스 변경은 로컬에 보존한다. 깨끗한 체크아웃의 CI가 pytest 임시 디렉터리를 먼저 생성하도록 보완했다. 원격 Actions 결과와 필수 상태 검사 지정은 push 후 별도 확인한다.
