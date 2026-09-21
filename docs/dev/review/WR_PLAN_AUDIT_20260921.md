# W/R 전체 계획 대비 구현 감사 — 2026-09-21

## 판정

**전체 완료가 아니다. R은 핵심 소비·답변·검증 경로가 구현되어 있고, W는 추출/원장 선저장 이후의 새 revision·참조 카드·snapshot 생산 경로가 남아 있다. 두 파이프라인의 실제 발행·점주 답변 왕복도 아직 연결되지 않았다.** 또한 최신 W 부분 실패 처리에서 API 응답 오류와 성공 오표시/재시도 누락을 재현했다.

계획의 방향과 맞는 구현은 많지만, 현재 코드를 “계획대로 모두 구현·검증됐다” 또는 “회의만 하면 끝난다”고 전달하면 부정확하다. 아래는 코드 존재, 제품 연결, 실자료/운영 인수를 구분한 판정이다. 체크박스 수나 테스트 수를 구현률로 환산하지 않았다. 사전에 가중치가 정해진 구현률 지표가 없어 단일 백분율은 산출하지 않는다.

## 기준과 확인 범위

- 코드: `codex/r-sequential-handoff`, `7f0e461fbfd42f94d4219c2934c6cd33728f5001`. 통합된 원격 main은 `db40813`이다. 이 감사 시작 시 추적 파일 변경은 없었다.
- [PR #19](https://github.com/2026-Unithon/AskBuddy/pull/19)는 조회 시 **OPEN**이며 같은 HEAD다. R 후속 구현의 main 병합/운영 배포까지 완료됐다는 뜻이 아니다.
- 정본: [MVP](../ASKBUDDY_MVP_CURRENT.md) §30~31, [전체 TODO](../DEV_TODO_CURRENT.md)의 C0/W0~W5/R0~R5/J0~J3, [C0 결정서](../C0_DECISIONS_AND_PLAN.md), [R 계획](../plan/R_IMPLEMENTATION_PLAN.md), [W 측정 계획](../plan/W1_MEASUREMENT_PLAN.md), [원가 계획](../plan/C0_COST_MEASUREMENT_PLAN.md).
- W 업로드/추출/원장/조립/승인 호출부, R 검색/계획/저장/문맥/인계 호출부, 공통 발행·migration·원가, 관련 화면·CI·평가 도구를 대조했다. 단위 함수 존재만으로 제품 연결 완료로 세지 않았다.
- 실제 매장 원본·holdout을 열거나 유료 모델 호출을 하지 않았다. 운영 DB/호스팅 설정, 다른 개발자의 미push 작업은 이 감사 범위에 없다. 따라서 운영 데이터에서 실제 피해가 발생했다고 단정하지 않는다.
- 과거 감사는 당시 기록으로 보존한다. 특히 9/19 문서의 미커밋 W worker 복구 구현은 현재 브랜치 구현으로 세지 않는다.

## 먼저 수정할 재현 결함

### F01 — P1: 부분 실패 자료의 작업 상세 조회가 응답 검증에서 실패

- 위치: `api/app/ingest/schemas.py:190`, `api/app/ingest/router.py:364`, `api/app/ingest/job_worker.py:121`.
- worker는 일부 구간 실패 자료를 `PARTIAL`로 저장한다. 하지만 `IngestJobSourceStatus`는 이 값을 허용하지 않는다. `_job_detail`이 해당 행을 `IngestJobSource`로 변환할 때 `ValidationError(status, literal_error)`가 발생한다.
- DB 반환을 합성 `PARTIAL` 행으로 대체하고 **실제 `_job_detail`을 호출해 재현**했다. HTTP 전체 요청은 이 감사에서 새로 실행하지 않았으나, 상세 응답 생성 자체가 실패하는 것은 확인했다.
- 영향: 일부 결과를 검토해야 할 작업에서 상세 화면이 정상 데이터를 받지 못한다.
- 담당/완료 기준: W가 DB 상태·API 타입·화면 표시를 일치시키고, 부분 실패 job 상세 GET의 정상 응답을 API 회귀로 고정한다.

### F02 — P1: 부분 실패가 전체 성공으로 집계되며 정상 재시도 대상에서 제외

- 위치: `api/app/ingest/job_worker.py:183`, `api/app/ingest/job_repository.py:183`, `web/app/owner/jobs/[jobId]/page.tsx:44`.
- `_refresh_job`은 `PARTIAL` 자료 수를 집계하지 않고 `final_job_status`의 `partial` 인자도 전달하지 않는다. 자료 1개가 PARTIAL, 카드 3개, FAILED 0개이면 전체 상태가 **SUCCEEDED**다.
- `reset_retryable_sources(include_no_result=True)`의 대상은 `FAILED`, `NO_RESULT`뿐이다. 작업 상세 재시도 버튼도 PARTIAL을 포함하지 않는다.
- 합성 집계 결과를 실제 `_refresh_job`에 주입해 `SUCCEEDED`를 확인했고, 실제 재시도 함수의 SQL 인자에서 PARTIAL 제외를 확인했다.
- 영향: 누락된 구간이 있는 작업을 완료로 인식하게 하고 정상 재처리 경로도 막는다. `final_job_status(partial=True)` 단독 테스트 통과로 이 연결 누락을 찾을 수 없다.
- 담당/완료 기준: W가 부분 실패 집계→상세 표시→실패 구간 재시도→성공 시 오류/실패 구간 초기화까지 연결한다. 재시도에서 기존 카드·원장 중복 및 남은 실패 상태도 검사해야 한다.

### F03 — P2: W 외부 처리 동안 DB 연결을 계속 보유

- 위치: `api/app/ingest/pipeline.py:45`, `:102`, `:136`; 추가 연결 사용은 `api/app/usage/repository.py:40`.
- `process_source`의 `pool.acquire()` 범위가 전처리·추출·조립 전체를 감싼다. 구간 checkpoint에서 transaction을 짧게 열어도 바깥 연결은 반환되지 않는다.
- 외부 함수만 합성 대체하고 실제 `process_source`를 호출하여 전처리·추출 진입 시 연결 보유가 모두 `true`임을 확인했다. 조립은 같은 acquire 블록 안에 있음을 정적으로 확인했다.
- 영향: 오래 걸리는 외부 호출이 풀 용량을 점유한다. 원가 receipt는 별도 연결을 요구하므로 동시 작업이 풀을 채우면 연결 대기가 겹칠 위험이 있다. **운영 교착/부하 장애 자체를 재현한 것은 아니다.**
- 담당/완료 기준: W가 읽기→연결 반환→외부 호출→짧은 checkpoint/저장으로 분리하고, 재획득 후 상태·권한·revision을 확인한다. 작은 풀에서도 모델/receipt 경로가 진행되는 회귀가 필요하다.

재현 도구: `api/scripts/audit_wr_plan_20260921.py`. DB·provider 함수는 대체하며 실제 네트워크, 유료 호출, 파일 삭제를 하지 않는다. 현재 관찰을 출력하는 감사 도구이고 정상 동작을 보증하는 통과 테스트가 아니다.

```powershell
cd C:\project\AskBuddy\api
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe scripts/audit_wr_plan_20260921.py
```

관찰 출력 요약:

```text
partial_job_detail: ValidationError, status, literal_error
one_partial_source_with_cards: expected PARTIAL, actual SUCCEEDED
partial_retry: eligible FAILED/NO_RESULT, partial_eligible false
connection_during_external_stages: preprocess true, extract true
```

## W 진행도 — 기존 업로드 기능과 새 계획 이행을 구분

| 단계 | 현재 확인된 구현 | 계획 대비 남은 것 / 판정 |
|---|---|---|
| W0 정답 감사·기준선 | 고정 분모, 원시 사실/최종 카드 분리 채점, 반복/A-A, 캠페인 잠금·재채점 도구와 과거 측정 기록 | 독립 사람 전체 검토·세부 커버리지, 교정 후 기준선 인수. 기존 문서의 과거 16개 입력 미복구도 해소 근거 없음. **도구 구현, 실자료 인수 미완료** |
| W1 분할·원장 선저장 | 사실 추출→구간별 checkpoint→원장→카드 연결. 조건/예외/부정/단위 포함 hash, 실패 구간 ID 기록, 혼합 PDF 페이지 판독과 HYBRID 입력 | F01~F03. 페이지/표/구간 위치·hash·attempt, 원시 응답/잘림 복구, evidence occurrence, 완전한 재사용 키가 미완성. **제품 구현 진행 중, 결함 있음** |
| W2 revision·대상·충돌 | 기존 source_facts·관계 제안·검수/수정, 새 revision/provenance DB·계약 기반 | 실제 W 흐름의 불변 fact revision 생산, 서버 entity/variant, 정정·분리 이력, 다중 자료 충돌·OWNER_ANSWER 출처, 영향 카드 재조립. **기반과 기존 경로만 있음** |
| W3 참조 카드·검수 | 기존 카드 생성·사실 연결·검수 UI. `CardPlan` 타입 있음 | 실제 조립은 자유 `ExtractedCard.content`를 생성. CardPlan 참조 선택→서버 검사/렌더 호출이 없음. dependencies/처분·의미 변경 편집의 revision/재승인 필요. **새 목표 경로 미연결** |
| W4 snapshot·발행 | `publish/service.py` transaction 서비스와 R 준비/활성화 어댑터. 기존 approve는 embedding 사전 준비·변경 재검사 | 실제 승인→불변 preview/snapshot→R prepare→W CAS/공개→R activate 조정자가 없음. 제외/복구·legacy RAW 이관도 같은 경로로 필요. **기반 구현, 제품 발행 미연결** |
| W5 쓰기 품질 인수 | 실행·비교·원가·오류 분해 도구 | W1~W4 실제 후보와 검토 정답으로 축별/조합·반복/A-A, 지식 손실·충돌·검수 시간·비용 측정. **완료 조건 대기** |

9/19 감사 이후 개선은 분명하다. 조건/단위/부정 hash 누락은 수정됐고, 구간별 선저장과 PDF 페이지 판독도 추가됐다. 다만 source의 PARTIAL 도입이 job/API/retry까지 연결되지 않았다. PDF 기본은 HYBRID이며 필요한 경우 문서 전체를 함께 전달하지만, 충분한 텍스트와 그림이 같은 페이지에 있는 경우의 그림 정보 판별·페이지 위치 보존까지 보장하지 않는다.

중복 사실 hash 강화도 occurrence 완료와 다르다. 현재 `(source_id, content_hash)` 충돌은 기존 fact를 재사용하므로 같은 사실이 다른 근거 위치에서 반복된 기록을 별도 occurrence로 보존하는 구현이 필요하다. `_persist_ledger`의 locator는 timestamp 또는 WHOLE_SOURCE이고, extract version은 모델/온도/mode다. 전체 prompt/schema/segment hash 키가 아니다.

## R 진행도 — 핵심 구현은 갖춰졌고 실제 생산자·품질 인수가 남음

| 단계 | 현재 확인된 구현 | 계획 대비 남은 것 / 판정 |
|---|---|---|
| R0 인증·평가 | JWT/매장 권한·요청 제한, v2 API/DB 평가, 행동·오류·인용·과차단, pooling/oracle·반복/A-A·원가 예산·판정 수입 | 실제 snapshot에 묶인 정답·E0/후보 비교. 기존 기록의 매장별 40개 초안/검토 0개는 새 검토 완료 증거가 없다. **핵심 도구 검증, 실자료 인수 대기** |
| R1 snapshot·색인·관측 | 현재 승인판 소비, prepare/activate, 멱등·상태/권한 재검사, metadata 보존/정리. 검색 결과 캐시 미사용 | W 호출 연결, 카드별 expected revision 계약, 실제 전환·철회·복구. 호스팅 로그 접근/보존 증거. **소비 구현, 실제 생산자 연결 대기** |
| R2 질문·사전·hybrid | 명시 슬롯/확정 문맥, 사전 검토·버전 수입, lexical/vector 독립 검색·RRF, 검토 입력 및 일반 의미 제안 경로 | 실제 별칭·오타/STT 효과, 범용 질문 품질. 별도 query expansion은 필요성·효과가 확인된 범위만 채택. **핵심 경로 구현, 품질 판단 대기** |
| R3 충분성·행동 | 조건/예외/수치/RAW 검증, ANSWER/CLARIFY/ESCALATE/REFUSE/SAFE_ROUTE, 후보 제한 reranker·fallback | 실제 오답/과차단, 사전/hybrid/reranker 단독·조합 성능·비용·지연 인수. **합성 계약 검증, 의미 품질 미인수** |
| R4 답변·인용·명확화 | 승인 참조 서버 렌더, 저장 직전 현재판 검사·답변/인용 원자 저장, TTL/멱등·선택 문맥, 확정 범위의 병합/선택형 명확화 | 실제 질문군의 충분성·인용·명확화 완료율 검증과 승격. **승인된 한정 범위 구현, 범용 지원 아님** |
| R5 점주 루프·직원 UX | occurrence·점주 원문·outbox, claim/heartbeat/finish·재처리, 상태/FAQ·학습 갱신·알림·내보내기 권한/감사·v2 UI | 실제 W consumer/worker가 finish까지 호출하는 왕복, 점주 1명/직원 2명 종단·실기기 Push/fallback. **R 수신/표시 구현, 실제 왕복 미완료** |

R 구현 근거: `api/app/learn/v2_router.py`, `planner.py`, `approved_renderer.py`, `answer_storage.py`, `general_semantics.py`, `reviewed_semantics.py`, `reviewed_grouping.py`; `api/app/reg/hybrid.py`, `index_preparation.py`, `reranker.py`; `api/app/team/v2_evaluation.py`, `v2_campaign.py`; `web/components/r-v2-chat.tsx`, `web/lib/query.ts`, `r-publication-refresh.ts`.

사용자가 확정한 의미 범위는 유지된다. 검토된 정확한 입력의 대상·속성·규격·조건/예외/수치/부정 범위가 일치할 때만 추가 병합하며, 새 모델/reviewed 명확화는 승인 후보의 대상·온도·크기 선택형이다. 아무 자유 표현이나 의미가 같다고 자동 병합하는 기능의 완료를 뜻하지 않는다. reviewed/general semantics와 reranker는 코드 기본 OFF이며, `r_v2_enabled`도 기본 OFF다. 실제 배포 Variables는 확인하지 않았으므로 운영 활성화 상태는 별도 확인해야 한다.

## C0·원가·이관·공동 단계

| 구간 | 확인 결과 | 미완료 조건 |
|---|---|---|
| C0 계약/fixture·CP-01~04 | schema·정상/거절 fixture, publication/멱등·R 접점, M0~M3 DB 기반 및 격리 검증 있음 | 카드별 draft revision 매핑, 전체 manifest/변경 카드 범위와 실제 W producer 연결 |
| CP-00A~C·CP-05 | usage receipt·phase/purpose·UNKNOWN 보존, 계산/시나리오·원가/평가 예산 도구·회귀 있음 | 실제 전체 Storage/요율·청구 대조·동결 workload와 운영 상한 인수. 계측 통과는 원가 목표 달성 증거가 아님 |
| M4 legacy 이관 | R RAW 소비와 legacy 새 질문 차단 있음 | 기존 승인 카드의 immutable RAW adapter/backfill, 건수·누락·재실행·롤백 검증. 제품 생산/이관 경로 확인 안 됨 |
| J0 조기 통합 | 합성 fixture와 R DB/API·계약 CI | 실제 W 원장→검수→발행→v2 검색/인용 관통 |
| J1 실자료 평가 | 반복·A/A·고정 분모·판정 도구 | 실제 W snapshot+검토 정답+예산, 기준선/W만/R만/W+R 비교·오류 분해 |
| J2 E2E·worker·CI | unit/DB/browser 및 `r-required` 집계 검사 구성·성공 | 실제 W/R 종단, ingest 영속 worker·claim/lease/heartbeat/중단 회수. 현재 업로드는 BackgroundTasks. CI 성공과 branch protection/운영 배포 차단 설정은 별도 |
| J3 운영 인수 | 점검/증거 양식·metadata 30일 정리 코드 | 실제 Railway 배포 SHA/Variables·로그 원문/권한/보존, DB 적용·정리 기록, 백업/복구·장애/실기기 인수 |

제품 호출 검색에서 `publish_knowledge`, `activate_prepared_index`, `claim_owner_event`, `finish_owner_event`를 실제 W 승인/worker가 조합해 호출하는 경로는 확인되지 않았다. 정의·테스트가 존재하는 것과 운영 루프가 존재하는 것은 다르다. 기존 `knowledge_apply` 호출은 legacy 카드 갱신이며 새 v2 outbox 소비 완료 근거가 아니다.

## 검증 결과와 한계

- 이번 감사의 집중 회귀: W hash/checkpoint/부분 실패/PDF + R bounded semantics/W index/external review/logging evidence **80 passed**.
- 위 회귀와 별도로 F01~F03을 합성 대역으로 재현했다. 기존 테스트에 실제 집계/상세 응답/재시도 연결의 검증 공백이 있음을 뜻한다.
- 동일 제품 코드의 [통합 검증 기록](R_SHARE_VERIFICATION_20260921.md): **913 passed, 4 xfailed, 119 subtests**, schema 15/fixture 3, migration 29 재구축과 R DB/API runner 통과. 이번 감사에서는 전체 DB/브라우저를 다시 실행하지 않았다.
- PR HEAD의 `contracts-unit`, `database`, `browser`, `r-required` 성공을 GitHub에서 재확인했다. production branch protection/배포 gate 설정까지 확인한 것은 아니다.
- 4 xfailed는 legacy 의미 취약성 회귀이며 통과로 더하지 않는다. `/learn/chat`은 새 질문을 `V2_REQUIRED`로 차단하고 취약 legacy fixture는 라우트에 연결되지 않는다. 이를 v2에서 재현된 결함 4개라고 보고하지 않는다.
- 실제 의미 정확도, 유료 비용, 운영 로그 삭제/권한, 최신 배포 상태는 위 숫자로 입증되지 않는다. 공개 URL만으로도 확인할 수 없다.

## 다음 작업 순서와 선행 조건

| 순서 | 담당 | 진행할 일 | 지금 가능한지 / 완료 조건 |
|---|---|---|---|
| 1 | W | F01/F02 상태·집계·재시도 계약과 F03 연결 보유 수정 | **즉시 가능.** 실제 상세 API/재시도/작은 풀 회귀 추가 |
| 2 | W+R | 카드별 expected revision 구조, 변경 카드/전체 manifest, activate/finish transaction 계약 확정 | **코드/PR 공동 검토 가능.** W draft CAS를 immutable version ID로 대체하지 않음. 현재 wrapper는 비어 있지 않은 모호한 expected_card_revisions를 거절 |
| 3 | W | W1 잔여와 W2/W3 revision·occurrence·참조 renderer 생산 | 합성 자료로 구현 가능. 원시 데이터/정답 품질 인수는 별도 |
| 4 | W 구현, R 검토 | 실제 승인에서 snapshot/prepare/publication/activate와 M4 연결 | 2·3 선행. 활성화 실패 시 공개 변경 전체 rollback, 중복·stale·철회 검사 |
| 5 | W 구현, R 검토 | ingest 영속 worker와 OWNER_ANSWER 소비·지식화·공개/finish 연결 | worker 기반은 병행 가능. 지식 공개 성공까지는 4 선행. finish는 공개 transaction에 포함 |
| 6 | W+R | 점주 1명/직원 2명의 업로드·질문·점주 답변·FAQ/학습·재질문 종단/복구 | 4·5 선행. 공개 준비 실패·중단·중복·역순·재시작 포함 |
| 7 | 회의/검토자, W/R | RD-01 판정 방식·사람 정답, RD-02 유료 예산 확정 후 실제 반복 평가 | **사용자 결정대로 대기.** AI 참조 생성/AI 판정/사람 최종 정답을 구분 |
| 8 | 운영 담당+R | 실제 호스팅 로그·배포·DB 보존 증거와 J3 인수 | 접근 권한/대상 환경 필요. 설정 확인은 개발과 병행 가능, 최종 운영 인수는 연결·배포 후 |

최종 흐름은 **W 원본→불변 사실/참조 카드→점주 승인→R 색인 준비→W 원자 발행+R 활성화→R 질문/답변→점주 답변 outbox→W 지식화/발행+R 완료 수신→FAQ·학습·알림·재질문 갱신**이다. 현재 끊긴 핵심 지점은 실제 W 생산·공개 조정자와 owner-answer 소비 worker다.

이번 변경은 감사 문서와 재현 도구만 추가한다. 결함 수정·PR 병합·운영 배포를 수행한 결과가 아니다.
