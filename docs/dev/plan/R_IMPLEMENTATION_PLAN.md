# R 항목별 구현 계획

2026-09-19: [R 단독 후속](../review/R_SOLO_FOLLOWUP_20260919.md)에서 R v2의 단계 간 공통 예산 연결과 사람 판정→검토 catalog 도구를 구현했다. 실제 일반화 범위·품질 기준 결정과 실자료/W 공동 인수는 남는다.

2026-09-18 최신: [검토된 의미 제안 adapter·예산 사전 예약](../review/R_ADAPTER_BUDGET_20260918.md) 구현. 아래 adapter 미완료는 이전 시점 기록이다. 현재 정확한 검토 입력의 제품 연결은 구현했고 기본 OFF이며, 미검토 자유 표현 일반화·실제 품질 인수는 완료하지 않았다. 예산 강제는 의미 제안 runner 범위이며 전체 HTTP 유료 평가의 다른 공급자 단계는 실행 전 별도 연결해야 한다.

2026-09-18 사용자 회신: 질문 정답 확정과 유료 평가는 [회의 결정 대기 목록](R_MEETING_DECISIONS_20260918.md)으로 분리했다. 사람 판단 수입 도구는 준비했으나 대기 항목을 자동 실행하지 않는다. 일반 의미 제품 adapter와 실제 W 연결·종단 인수도 미완료로 유지한다.

2026-09-18 추가 구현·검토: [R 후속 현재 판정](../review/R_FOLLOWUP_REVIEW_20260918.md). v1 새 질문 차단·v2 진입, 점주 재처리 UI·발행 갱신, 실제 v2 격리 모델 비교·사람 판정 보고, 용어 불변 수입을 추가했다. 일반 의미 판단의 제품 승격·실자료 품질·실제 W 종단 인수는 미완료다. 아래는 이전 시점 기록이다.

2026-09-16 수치 범위 후속: [수치 적용 범위·모순 조건·검토 초안](../review/R_NUMERIC_SCOPE_AND_COVERAGE_20260916.md). 같은 속성/단위의 Decimal 구간 포함·배타성, 모순 조건 거절과 실제 질문 범위별 묶음을 추가했다. dev 두 매장 각각 40개 초안(서로 다른 문구 37개)을 배타 생성했다. 전체 735 tests/119 subtests 및 AST 통과. 사람 검토 0개이며 snapshot 커버리지·실자료 성능은 아직 미인수다.

2026-09-16 권장 순서 후속: [재시도·평가·문맥·조건·RAW·FAQ 구현](../review/R_NEXT_SEQUENCE_20260916.md). 자동 인계 10회/backoff/종료·수동 재처리, 격리 평가 sink/RAW 필수 인용 보고, 저장 context 재대조, 명시 OR/배타 조건, 의미키 v3, 승인 절차 RAW와 v2 FAQ를 연결했다. 전체 704 tests/119 subtests, 최종 지표 버전 관련 63 tests/13 subtests 및 AST 통과. Docker/W 인수와 범용 의미 판단 전체 완료는 아니다.

현재 잔여 범위 대조: [R_REMAINING_AUDIT_20260916.md](../review/R_REMAINING_AUDIT_20260916.md). R 단독 구현·설계 15개 작업군, 실자료 평가 8개 작업군, DB/W 공동 인수 6개 작업군으로 구분했다. 아래 누적 기록의 과거 미완료 문구와 현재 코드 상태를 구별하며, 일반 RAW·복합 조건·의미 묶음만을 전체 잔여로 보지 않는다.

기준: 2026-09-15 pull c73549a. 정본은 MVP §31, C0 결정서 §4/§6/§10, DEV_TODO R0~R5이며 W1_MEASUREMENT_PLAN ③⑤를 R 평가에 반영한다. 이 문서는 항목별 실행 계획이고 R 전체 완료 기록이 아니다.

2026-09-16 동기화 기준은 `4212fec`다. 기존 R 작업을 보존해 W 변경과 통합했다. 개발 정본·계획·검증은 모두 `docs/dev/`에서 관리한다. 검증 기록: [R_PULL_DEV_RELEASE_20260916.md](../review/R_PULL_DEV_RELEASE_20260916.md).

## dev와 release의 실행 경계

| 범위 | 기록·진행 기준 |
|---|---|
| R0 평가 결과 수집·고정 분모·미판정·보고, R2/R3 검색/충분성/문맥 및 서버 계약 | dev의 R0~R5. 단일 질문 수집·보고와 반복 캠페인 대조/paired gate 연결 완료. 실제 정답 검토·비용/원장 인수·후보 pooling/oracle은 별도 |
| 알림/FAQ/worker의 미구현 서버 계약·정합성 | dev에서 구현 여부를 추적. 사용성 작업으로 개발 완료 조건을 지우지 않음 |
| 실제 출시 환경의 Push/worker 연결, 기기·네트워크·브라우저 종단 인수, 버튼/페이지 체감 개선 | release의 REL-00 기준선 및 REL-03/05에 연결. dev 검증과 출시 인수는 별도 |
| 실제 W 공개·ApplyOwnerAnswer 연결과 의미 truth | dev 공동 인수. release의 실제 사용 검증도 필요하며 어느 한쪽 체크로 대체하지 않음 |

앞선 보고의 'R 단독 미완료'에는 개발 구현과 출시 인수가 섞여 있었다. 위처럼 분리하되 미완료를 완료로 바꾸지 않는다. 이미 구현한 정책 확인·앱 알림은 유지하며 실제 사용감 개선은 release 범위에 따라 진행한다.

최신 구현 상태(2026-09-16): [R_RUNTIME_IMPLEMENTATION_20260916.md](../review/R_RUNTIME_IMPLEMENTATION_20260916.md). M2 준비/활성화, 실제 hybrid와 승인 사전, 명시 슬롯 planner와 선택형 reranker, M3 v2 저장/API, 점주 원문 전달/lease 인계, 별도 v2 화면을 구현했다. 아래 과거 상태의 'M2·v2 미구현'은 당시 기록이며 최신 상태는 이 검증 기록을 따른다. R 전체 완료 조건 중 실제 사전/효과 평가·정책 후속/알림·FAQ·DB UI E2E와 W 공동 발행 연결은 남아 있다.

후속 완료(2026-09-16): [R_RERANK_USAGE_20260916.md](../review/R_RERANK_USAGE_20260916.md). R3 SDK 경로의 호출 전 원장·오류 출력·timeout/취소·정리 지연과 v2 API 계측 실패를 검증했다. API 434 tests/95 subtests, 실제 DB/API 172 PASS. SDK 응답은 합성이므로 실제 모델 품질·비용·지연 평가는 남아 있다. 선택형 reranker 기본 OFF는 유지한다.

## 실행 순서와 완료 기준

2026-09-16 단독 평가 보강: [RAW 정답/근거 회수·의미 묶음 평가](../review/R_RAW_GROUPING_EVALUATION_20260916.md). RAW-only ANSWER truth 수입의 typed 강제 결함을 수정하고 RAW oracle·혼합 근거 complete 판정, 고정 쌍 분모와 미판정 보존의 grouping 평가 CLI를 추가했다. 685 tests/119 subtests 및 AST 통과. Docker/W/외부 모델 호출 없음. 합성 실제 planner→CLI에서 미지원 동일 의도 쌍의 분리도 miss로 보고했으며 실자료 성능으로 확대하지 않는다.

2026-09-16 Docker/W 제외 후속: [예외·승인 Q/A RAW·의미 묶음 확장](../review/R_EXCEPTION_QA_GROUPING_20260916.md). 명시 제외 예외의 부적용 확인, 질문과 일치하는 승인 Q/A 원문, 속성/크기/조건/예외를 포함한 의미키 v2를 구현했다. 전체 660 tests/119 subtests 및 AST 통과. 사용자 요청대로 Docker는 실행하지 않았다. 자유 서술 RAW·임의 복합 논리·일반 의미 동치와 실제 평가를 완료했다고 표시하지 않는다.

2026-09-16 재개 후속: [명시 복합 조건·RAW 수량·실자료 표본](../review/R_CONDITIONAL_RAW_RESUME_20260916.md). 조건 전체/선행 closure 대조와 단일 원자 RAW 수량 답변을 추가했다. dev 2매장 대표 질문 초안 40개(각 자료 유형 5개/매장)를 고정했다. 단위 646/119 subtests 및 AST 통과. Docker 엔진 연결 실패로 이번 DB 통합은 미완료이고, 실제 승인 snapshot·질문 truth 부재로 성능 평가는 미측정이다. 일반 의미 판단 전체 완료가 아니다.

2026-09-16 실자료 수입 후: [질문 조건·의미 묶음·실자료 검토 접점](../review/R_SOLO_DEV_DATA_AND_GROUPING_20260916.md). 180건 dev 사실을 원본 hash에 고정해 R 검토 초안으로 준비했고 사람 검토→승인 snapshot 매핑→기존 평가 manifest 수입을 구현했다. 수량/위치/가격/개수의 미지원 조건 누락을 차단하고 명시적 단순 질문의 의미 묶음을 실제 API까지 연결했다. 619 tests/119 subtests, v2 API 101 및 DB 재구축 통과. 실자료 부재는 해소됐지만 R 질문/행동/적용 범위 검토와 실제 승인 snapshot은 아직 없으며 일반 RAW·복합 의미 판단과 W 공동 인수는 미완료다.

2026-09-16 실자료 대기 중 후속: [RAW·평가 원가](../review/R_SOLO_RAW_USAGE_20260916.md). 명시적으로 특정 카드의 승인 RAW 원문을 요청한 경우만 서버 assessment와 기존 검증/저장을 거쳐 제공한다. 평가 전용 명시적 원가 sink도 추가했다. 전체 단위 582/119 subtests, v2 API 94 포함 DB 통합 통과. 사용자는 실자료 경로를 확인 후 제공하기로 했으며 일반 RAW 의미 판단이나 전체 R 완료로 확대하지 않는다.

2026-09-16 R 단독 후속 묶음: [구현·검증·잔여 범위](../review/R_SOLO_EVALUATION_AND_ACCESS_20260916.md). 사람 관련성 판정 수입/검색 지표/사실 의미 매핑과 선행 근거 회수/oracle 진단/필수 비답변 검토/다회 HTTP 평가/용어 검토 묶음/usage 연결/점주 내보내기 권한·감사를 구현했다. 단위 575/119 subtests 및 실제 DB 통합 검증. R 전체 완료는 아니며 복합 의미·RAW 런타임 확장, 자동 의미 묶음, 실자료 효과 평가와 W 공동 연결은 별도다.

2026-09-16 R0 모집단 대조: [검증 기록](../review/R_INDEX_UNIVERSE_AUDIT_20260916.md). 승인 snapshot의 전체 블록과 색인 참조를 독립 대조하고 누락/추가/중복에서 평가를 중단한다. 현재 승인 제외 필터와 불변 대응 검사 분모를 분리했다. 다음은 pool hash에 묶인 사람 관련성 판정 수입이다.

2026-09-16 R0 독립 채널 수집: [실제 DB 검증](../review/R_RETRIEVAL_COLLECTION_20260916.md). 제품과 동일한 lexical/vector SQL 결과를 융합 전 수집하고 현재 승인 색인 문서에서 표본을 만든다. 546 tests/116 subtests 및 일회용 DB 통합 통과. 다음은 승인 블록/색인 모집단 대응, hash에 묶인 관련성 검토, 검색 지표/oracle 분해다.

2026-09-16 R 재개: [후보 검토 준비·담당별 잔여 작업](../review/R_RETRIEVAL_POOL_20260916.md). R0 승인판의 lexical/vector/oracle 합집합·미검색 표본 생성 도구를 추가했다. 실제 검색 채널 수집 → hash에 묶인 사람 검토 → 검색 지표/oracle 분해 순서로 이어간다. W 실제 발행 연결 및 사용자 사실 판정과 구분하며 R0 전체 완료로 표시하지 않는다.

2026-09-16 R0 반복 연결: [R_V2_CAMPAIGN_20260916.md](../review/R_V2_CAMPAIGN_20260916.md). manifest 동일성·arm별 버전 고정·독립 실행 중복 차단·A/A 변동 폭·필수 악화·외부 인수 미확인을 기존 paired gate와 결합했다. 실자료 평가/출시 승격을 자동 확정하지 않는다.

2026-09-16 R0 후속: [R_V2_EVALUATION_20260916.md](../review/R_V2_EVALUATION_20260916.md). 독립 세션의 v2 HTTP 결과·오류·receipt 수집, 출력 hash에 고정된 검토 입력, 고정 분모 보고와 paired gate 입력을 구현했다. 실제 DB/API 합성 6문항으로 확인했다. 30~50문항 품질 평가·pooling/oracle·다회 대화·반복 캠페인 승격·평가 비용 귀속은 별도이며 R0 전체 checkbox를 닫지 않는다.

2026-09-16 추가 진행: R4/R5 정책 후속 명시 확인과 직원 알림 화면을 연결했다. SAFE_ROUTE만 서버 원문에 연결해 이관하며 REFUSE는 제외한다. 중복·권한·rollback과 화면 복원을 검증한다. 상세 결과와 남은 범위는 [R_POLICY_NOTIFICATIONS_20260916.md](../review/R_POLICY_NOTIFICATIONS_20260916.md)를 따른다.

| 순서 | 항목 | 구현 범위 | 완료 기준/의존성 |
|---|---|---|---|
| 1 | R0 반복 평가 안전성 | 대표 순증 중앙값 유지, 질문별 반복 안정성 보고, 필수 질문 모든 짝의 성공→실패 직접 검출, 미판정/필수 목록 누락 차단 | 합성 반례 및 전체 회귀. **산술 모듈 구현 완료**, 실제 v2 결과 수집·캠페인 승격은 별도 |
| 2 | R0 E0 기준선 동결 | C0 승인 fixture·질문/필수 사실·금지 주장·5행동을 고정하고 기존 읽기 출력 보존. 입력/정답/채점기/코드/모델 버전과 전체 분모 기록 | 재생 가능한 오프라인 기준선, 부분 실패/미판정 보존. 사람 사실 truth는 점주 확인, 합성은 합성으로 명시 |
| 3 | R1/R4 stale 처리·저장 경합 | 동일 absolute deadline 내 최대 1회 재검색. 기존 pending 우회 제거. publication→card→session 잠금 순서로 재검사와 저장 결합 | 공개 변경/제외/교차 매장/기한 소진/반복 경합 반례. STALE_KNOWLEDGE에서 pending·알림 없음. W 실제 공개 잠금 접점 확인 필요 |
| 4 | M2 및 R1 색인 준비 | 불변 snapshot만 소비, durable staging·hash·TTL·operation 멱등성, PrepareIndex 결과 제공 | 중복/역순/실패 복구, 모델 중 연결 미보유. 공개 포인터는 W 소유; 실제 W 조정 연결은 공동 인수 |
| 5 | M3 및 R4 v2 저장 기반 | 가산 migration, contract_version 세션 고정, context 소유권/TTL·요청 멱등성·당시 인용 저장 | v1 격리·재시도·동시 요청·commit 경합 실제 DB 검증. 기존 이력 변조 없음 |
| 6 | R2 질문/후보 | 확정 슬롯과 추정 분리, 별칭/오타, lexical/vector 독립 회수 및 융합 | 서로 다른 속성·규격, lexical-only 정답, 무관 후보. 자동 규격 확정 금지 |
| 7 | R3 충분성·reranker | 대상/속성/적용 범위/조건·예외 검사, 행동 결정, 후보 밖 ID 차단 | ANSWER/CLARIFY/ESCALATE/정책/ERROR 구분. RRF·유사도만으로 답변 허용하지 않음 |
| 8 | R4 참조 답변·되묻기 | AnswerPlan→검증→승인 블록 렌더, 필수 dependency, v2 API와 평가 하네스 연결 | 오연결·조건 삭제·부정·RAW 부적합·문맥 반례 및 원자 저장 검증 |
| 9 | R5 점주 루프 | occurrence/원문 답변/outbox 원자 저장, W knowledge_apply와 별도 상태, FAQ·알림 | 동일/상이 문맥 전파, 중복 이벤트·실패 복구. 실제 W 발행은 공동 종단 인수 |
| 10 | J0/J1/J2 및 원가 | 실제 W snapshot 교체, 전체 비용·지연·품질 인수 | 합성/실자료 구분, 누락 비용은 UNKNOWN. 운영 배포·유료 실험은 별도 실행 범위 |

각 항목은 구현→반례 테스트→필요한 실제 DB 검증→새 review 기록 순서로 닫는다. 실패한 검증은 다음 항목 완료 선언으로 덮지 않는다. 보안 결함은 순서와 무관하게 우선 보완할 수 있다. 항목 2의 모델 기준선 재생은 제품 호출이 아닌 격리 평가이며 paid 호출 없이는 실제 모델 성능으로 표시하지 않는다.

## 전체 계획과의 대조

- 이전 R 제안은 적용 범위 확정을 먼저 두었으나 새 W 계획은 재현된 채점기 오통과를 먼저 고친다. 재현된 오류 수정을 공통 schema 합의와 독립적으로 진행하는 편이 타당하다. R은 W 채점기 파일을 중복 수정하지 않는다.
- 중앙값 대 만장일치의 단일 선택 문제는 새 W 계획 ⑤에서 역할 분리로 정리됐다. R은 기존 D18의 중앙값·ceil 문턱·2/3 방향·비용 조건을 유지하고 반복 안전성을 추가한다.
- 적용 범위 4상태의 방향에는 동의하되 W 계획의 '대상 축 없음→자동 NOT_APPLICABLE'은 **확인된 축 부재**와 누락/null의 구별이 필요하다. COMMON의 확인 근거·범위, 축의 출처/버전을 공동 계약에서 확정하기 전 런타임에 추정 승인을 넣지 않는다.
- 필수 질문이 아닌 ALL_SUCCESS→MIXED도 전부 보고하되, 이번 산술 모듈의 자동 안전 차단은 정본의 must_have/safety 집합에 적용한다. 모든 일반 질문의 흔들림을 새로운 전역 차단 조건으로 확대하지 않는다.
- W의 MISSING/PARTIAL/COVERED 순위를 R 성공 개수로 변환하지 않는다. R 입력의 True는 사람이 확인한 grounded complete ANSWER, False는 비성공, None은 미판정이다. action 일치만으로 True를 만들지 않는다.

## 항목 1 호출 계약

`app.team.answer_metrics.paired_gate` 결과는 `r_paired_gate/v2`다. 각 짝은 동일 문자열 질문 ID를 갖는 baseline/candidate mapping이며 모든 반복에서 전체 ID 집합이 일치해야 한다. 키 삭제는 오류이고 값 None은 미판정이다. 오류/timeout이 확정된 제품 실패는 False이며 평가자 장애로 정답 여부를 모르는 것은 None이다.

- `must_have_ids`: 사전 고정한 필수/safety 질문 ID. None은 목록 미제공이므로 통과 불가, 빈 목록은 명시적 필수 0개인 합성 등에서만 사용한다. 중복/분모 밖 ID를 거절한다. 이 함수는 실제 캠페인의 사전등록 여부까지 검증하지 않는다.
- `must_have_regressions`: 외부의 추가 안전 검사 결과. 0을 보내도 실제 반복에서 찾은 악화를 덮지 못한다.
- `must_have_passed`: True/False/None. 관측 악화가 하나라도 있으면 False, 목록 또는 필수 판정이 누락되면 None이다.
- `stability_transitions`: ALL_SUCCESS/ALL_FAILURE/MIXED/UNJUDGED 사이 변화별 질문 ID. 안정성 개선을 대표 순증에 별도 가산하지 않는다.
- `deltas`, `median_delta`: 미판정이 있는 짝은 null, 미판정이 하나라도 있으면 대표 중앙값은 null이다. 판정된 짝만 남겨 분모를 줄이지 않는다.
- `blocking_reasons`: 필수 목록 누락, 미판정, 관측/외부 필수 악화, 원장 회귀, 비용 미통과, 효과/방향 미달을 구분한다.
- 기존 호출의 산술 입력은 유지하지만 must_have_ids 없이 eligible=True로 나오던 동작은 안전하게 보류로 바뀐다. 저장된 과거 결과는 덮어쓰지 않고 새 버전으로 재평가한다.

이 모듈은 결과 판정의 기반이지 실제 v2 실행·정답 라벨링·원장 동일성 검증·운영 승격 전체가 아니다. CP-05와 R0 전체 완료를 의미하지 않는다.

## 2026-09-15 후속 실행 상태

검증 기록: [R_E0_STALE_CONTEXT_20260915.md](../review/R_E0_STALE_CONTEXT_20260915.md).

| 항목 | 이번 산출물 | 남은 완료 조건 |
|---|---|---|
| 2 E0 | 승인 fixture를 실제 기존 retrieve/compose 함수에 연결한 **고정 후보·extractive** 기준선. 37행/실제 질문 16개, 5행동 기대값, 코드/입력 hash와 미판정 보존 | 실제 lexical/vector 회수·모델·v2 API 평가와 사람 의미 판정. 합성 후보 score=1을 검색 품질로 해석하지 않는다 |
| 3 stale | 실제 v1 채팅에서 동일 deadline 안 1회 재검색, 반복 경합/근거 소실/시간 부족은 STALE_KNOWLEDGE, publication→card 잠금 | PG15 경합 실측 및 W 실제 공개·제외 경로 인수. v2의 exact snapshot 저장과 동일하다고 하지 않는다 |
| 5 M3 첫 단위 | 가산 session/context migration, 서버 문맥 생성/조회/사용자 선택 수락/두 번째 되묻기 저장 서비스, v1 session 필터 | migration 실제 적용·FK/잠금 검증, 요청 멱등성+답변/인용+context의 원자 저장, v2 API 연결. M3 전체 미완료 |
| 공통 응답 계약 보강 | ChatResponse action 필드 배타성·중복 인용/선택지 차단, QuestionContext 원문 공백 보존 | W와 공동 계약 변경 검토. 기존 정상 payload 형식은 유지 |

순서 조정: Docker 엔진 장애 때문에 항목 3의 DB 인수를 닫지 못한 동안 M2와 작성 병렬이 허용된 M3 문맥 단위를 구현했다. 아직 미검증 migration을 운영에 적용하거나 v2 endpoint를 활성화하지 않았다. 기존 v1 코드도 새 contract_version 열을 읽으므로 **M3 migration 검증·적용이 코드 배포보다 먼저**다.

다음 실행 순서는 (1) Docker 복구 후 `verify_r_handoff.ps1`로 기존 29개+문맥/stale 새 시나리오 검증, (2) 실제 전체 schema의 migration 재구축, (3) M2 준비 데이터 접점 확정 및 실제 adapter, (4) M3 요청 멱등성/메시지/인용과 v2 실행 연결, (5) R2→R3→R4→R5다. 새 문맥 저장 함수는 내부 서비스이며 공개 API 요청을 직접 받지 않는다. 호출자는 trusted scope, publication 잠금, 요청 멱등 receipt 및 답변 저장을 같은 transaction에 결합해야 한다.

### M2를 추측으로 구현하지 않기 위한 구체 접점

현 `PrepareIndexRequest`에는 card ID·expected_card_revisions·content_hash만 있고 준비할 불변 승인 payload가 없다. `expected_card_revisions`의 대응도 명시적 card/version mapping이 아니다. 반면 W의 현 `publish()` DB 서비스는 snapshot payload를 별도로 받고 prepared_id 소비·만료 확인·색인 pointer 전환까지 연결하지 않았다. FakeIndexer의 성공을 실제 색인 준비 완료로 대신할 수 없다.

권장안은 W가 승인 변경 묶음의 불변 manifest를 먼저 저장하고, R이 **trusted store + manifest ID/hash + 명시적 card ID/version/revision mapping**으로 그 정확한 내용을 조회·검증해 staging을 만드는 것이다. 외부 임베딩 동안 연결/잠금을 놓고, 완료 저장 시 같은 manifest/config/hash인지 재검사한다. W 공개 transaction은 prepared_id의 매장·payload/config hash·TTL·미소비 상태를 확인하고 승인 pointer와 색인 pointer를 함께 전환한다. 이 manifest는 발행 전 준비 산출물이며 현재 공개 snapshot인 척 노출하지 않는다. wire DTO 확장과 저장 소유권은 W/R 공동 변경이며 이번에 임의로 확정하지 않았다.

## 2026-09-16 검증 환경 정정

현재 `supabase/config.toml`의 `db.major_version`은 **17**이고 초기 remote schema에 PG17의 MAINTAIN 권한이 있다. 앞선 PG15 기록은 R 단위 DB 호환성 검증이며 전체 앱 schema의 기준 DB 버전으로 확대하면 안 된다. migration 원문과 설정은 바꾸지 않고, 전체 재구축 runner를 PG17 pgvector로 맞추고 설정 major 불일치 시 실패하도록 했다. 기존 경량 runner의 PG15 검증은 호환성 확인으로 유지한다.

재개 결과: [R_DB_RESUME_20260916.md](../review/R_DB_RESUME_20260916.md). PG15/17 각각 DB 50/50, PG17 전체 migration 21/21, 단위 406/하위 사례 95 통과. 위 9월 15일 기록의 DB 장애와 migration/FK/잠금 미검증은 해소됐다. 다음 실행 항목은 M2 준비 데이터 접점·adapter이며 M3 전체와 v2 runtime은 아직 미완료다.
