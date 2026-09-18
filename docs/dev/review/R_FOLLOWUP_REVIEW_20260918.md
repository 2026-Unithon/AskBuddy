# R 잔여 구현 후속과 검토 — 2026-09-18

기준: `30c863b` 이후, `codex/r-semantic-support-boundaries`. 사용자의 전체 진행 요청에 따라 계획의 A01~A15와 B/C 의존성을 다시 대조했다. 기존 W/release 미커밋 파일은 이번 R 변경에 포함하지 않는다.

## 구현 및 검토 결과

| 계획 | 현재 산출물 | 완료의 한계 |
|---|---|---|
| A01~A05 일반 의미·RAW·조건·문맥·묶음 | 기존 명시 planner 유지. v2의 실제 검색/검증 문맥/최종 baseline을 관찰하는 `semantic_shadow_scope` 추가. 모델 제안은 행동·승인 후보·사용자 턴·조건/예외·묶음 후보를 입력받고 hash/참조 검증. 일반 요청은 provider를 호출하지 않음 | 모델 의미 판단을 제품 답변/병합에 승격하지 않음. 일반 표현 전체의 운영 지원은 미완료이며, 검토 정답과 평가 통과 후 서버 suitability adapter 및 활성화를 별도로 인수해야 함 |
| A06 FAQ | 기존 v2 FAQ의 승인/현재판 필터와 실제 DB 검사 유지 | 실제 W 발행 자료로 인수 필요 |
| A07 발행 후 갱신 | 직원 이력에서 PENDING 지식 상태도 polling. PUBLISHED/LINKED 결과 조회 시 FAQ·학습 query 무효화 | 실제 W producer/worker 발행 성공 E2E는 별도 |
| A08 재처리 | 기존 10회/backoff/lease/fencing 서버에 점주 UI 연결. 최신 종료 FAILED만 사유 입력 후 같은 event 재처리. 장애 재시도는 같은 request_id와 body 사용 | 실제 worker 실행은 W 의존 |
| A09 용어 공급 | `collect_r_lexicon.py`: 매장 내부 수동 관찰 자료 입력, 출처 검증, content-addressed 불변 수입/재수입. `approve_lexicon_review`는 고정 검토 hash와 기존 점주 권한 검사를 거쳐 버전 생성 | 자동 웹 수집은 이번 범위에서 제외. 관찰 별칭/STT 변형·공개 URL/일자/이용 근거를 사람이 제공해야 하며 자동 생성하지 않음 |
| A10 검색 질문 확장 | 별도 생성형 query expansion 미도입으로 명시. 승인 사전의 lexical 후보 확장만 유지 | 실제 누락 사례와 짝비교 효과가 확인될 때만 추가 |
| A11 캐시 | 검색 결과 cache 미사용. 기존 요청 멱등 재생과 구분 | cache를 추후 도입하면 권한/판 무효화 계약 추가 필요 |
| A12 로그·보존 | 앞선 커밋의 일반 예외 원문 제거·metadata 30일 정리·DB 권한/불변 원문 보존 유지 | 호스팅 stdout 보존 설정은 배포자 확인 필요 |
| A13 평가 귀속 | 기존 ContextVar 평가 sink에 shadow 결합. local isolated DB+RUNNING run을 요구하는 live CLI, 최대 20회/회당 3초, SDK retry 1회, durable usage 유지 | 이번 검증은 합성 공급자. 실제 모델 호출/비용 효과 미측정 |
| A14 평가 보고 | shadow JSONL의 정확한 row hash에 사람 판정 결합. 미검토·실패·오답·과차단·오병합·인용 오류·지연을 분리. 비용은 원장 미확인 상태 유지 | 기존 v2 campaign/A-A와 실자료 비교 인수는 미완료. shadow 보고 단독은 승격 허가가 아님 |
| A15 자동화 | 기존 GitHub Actions unit/DB/browser/r-required 유지. 신규 테스트와 확장 브라우저 검사가 자동 포함 | 아래 실행 근거와 원격 상태로 확인 |
| C04 v1 안전 전환 | `POST /learn/chat`, `POST /learn/pending`은 JWT/매장 회원 확인 후 `409 V2_REQUIRED`. 생성·신규 문의 저장 없음. legacy 회귀 함수는 라우팅하지 않음. GET 이력은 유지 | v2 기본 flag OFF일 때 안전하게 이용 불가 안내. v1 자유 생성으로 rollback 금지 |
| R 화면 진입 | 직원 Buddy·점주 질문 메뉴와 점주 bootstrap을 v2로 변경. 이전 대화 페이지는 읽기 전용, v2 미활성 시 새 대화 버튼 차단 | v2 활성화는 승인 snapshot 준비/제품 인수와 함께 결정 |

## 사용 방법

- 오프라인 입력 준비/재생: 기존 `compare_r_semantic_proposal.py`.
- 격리 live 비교: `R_EVALUATION_DATABASE_URL`에 로컬 평가 DB를 지정하고 `run_r_semantic_evaluation.py --input <매장내입력> --output <매장내새JSONL> --run-id <RUNNING평가ID> --repeat 3 --isolated-live`. 유료 provider를 호출한다. 이번 작업에서는 실행하지 않았다.
- 판정 집계: `report_r_semantic_evaluation.py --observations <JSONL> --judgments <사람판정JSON> --output <새보고서>`. 판단 누락을 성공으로 채우지 않는다.
- 실제 HTTP 비교: 같은 비운영 ASGI 하네스에서 `evaluation_usage_scope` 안에 `semantic_shadow_scope(record=비공개저장함수)`를 중첩. HTTP 헤더/요청 본문으로 켤 수 없다. 실제 baseline만 저장하고 모델 제안은 sidecar에 남긴다. 동일 요청 재생은 다시 제안하지 않는다.
- 용어 수입: `collect_r_lexicon.py --store-directory <매장내부디렉터리> --input <그안의관찰JSON>`. 입력은 `entries`와 `collection_reference`. 공개 자료는 기존 `LexiconEntry`의 URL/수집일/이용 근거 필요. 수입은 승인이 아니다.

## 검증

- 순수 R stage 트리: **780 passed, 4 xfailed, 119 subtests**. PG17 **27개 migration** 재구축과 DB/API 전체 회귀 통과. v2 API **104 checks**에는 실제 HTTP shadow baseline 보존·동일 요청 재생이 포함된다. `pnpm check`도 통과했다.
- 브라우저: 기존 27개에 재처리 실패/중복 차단/동일 body/새로고침, legacy 읽기 전용, v2 OFF 차단을 추가해 34개 통과.
- 기존 legacy strict xfail 4개는 평가용 생성기의 알려진 한계이며 제거하지 않았다. 제품 POST 차단은 별도 통과 테스트로 검증한다.
- 기존 W 미커밋 파일 포함 worktree와 순수 R 커밋을 구분한다. DB worktree에는 W lease migration을 포함해 28개가 있다.
- main 보호 설정: `r-required`를 필수 검사로 지정하고 최신 base 요구(`strict=true`)를 켰다. 관리자의 우회 권한은 유지하며 관리자 강제·리뷰 인원 제한은 추가하지 않았다.
- shadow sidecar에는 사람 검토에 필요한 질문·후속 턴·승인 후보·비교 문맥이 포함된다. 일반 로그가 아니며 실제 자료는 반드시 해당 매장 내부 디렉터리에 저장한다.

## 외부 자료와 공동 인수가 필요한 항목

B01~B08: 두 매장 각각 40개 초안/37개 서로 다른 문구, 사람 검토 0개 상태. 승인 snapshot·질문별 행동/필수 fact·RAW/금지 주장·조건/예외의 정답을 자동으로 만들지 않았다. 검색 pooling, 일반 의미 오답/과차단, 사전·hybrid·reranker 조합 효과, 실제 비용/지연, 반복 A/A는 이 자료가 있어야 실행·인수할 수 있다.

C02/C03/C05/C06: 실제 W producer·owner-answer worker 및 점주 1명/직원 2명 종단 연결은 없다. R 인계 계약 검증을 실제 W E2E 완료라고 표시하지 않는다. C01의 최신 R 회귀와 C04의 R 소비부 전환을 먼저 검증한다.

**판정: R의 이번 독립 구현·검증 묶음은 수행했지만, 일반 의미 판단의 제품 채택까지 포함한 R 전체 완료는 아니다.** 미검증 의미를 자동 답변으로 승격하는 구현은 추가하지 않았다.
