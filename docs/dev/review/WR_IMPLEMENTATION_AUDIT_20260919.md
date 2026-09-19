# W/R 전체 구현 현황 재대조 — 2026-09-19

## 결론과 확인 기준

W는 **사실 추출·원장 선저장과 기존 카드 검수 경로를 구현한 상태**다. 새 계약의 불변 revision·참조 전용 카드 조립·snapshot 생산/발행·점주 답변 소비자는 제품 호출 경로에 아직 연결되지 않았다. W0/W1 일부 진행을 W1~W5 완료로 볼 수 없다.

R은 **R0~R5의 주요 서버·화면·평가 도구와 일반 의미 제안 런타임을 구현하고 합성/DB/브라우저 회귀를 통과한 상태**다. 일반 의미 경로는 기본 OFF이며 실자료 의미 정확성 인수는 없다. 자유 표현의 자동 질문 병합, 범용 명확화에는 구현 범위가 남아 있고, W 실제 발행·점주 답변 왕복도 미완료다. 따라서 “R 전체 완료, 회의만 남음”도 정확하지 않다.

정본은 [MVP §30~31](../ASKBUDDY_MVP_CURRENT.md), [DEV TODO W0~W5/R0~R5/J0~J3](../DEV_TODO_CURRENT.md), [C0 결정서](../C0_DECISIONS_AND_PLAN.md)다. [W1 측정 계획](../plan/W1_MEASUREMENT_PLAN.md), [R 구현 계획](../plan/R_IMPLEMENTATION_PLAN.md), [원가 계획](../plan/C0_COST_MEASUREMENT_PLAN.md)과 최신 검증 기록을 함께 대조했다. 과거 체크박스와 과거 검증 결과는 현재 코드 완료 판정으로 그대로 사용하지 않았다.

## Git·검증 범위

- 현재 브랜치: `codex/r-semantic-support-boundaries`, HEAD `45c3ea277acc9c616407fcf2bc47ff345167cd08`.
- `git fetch origin` 후 `git pull --no-rebase origin main`: **Already up to date**. 원격 main은 `1d49133`이며 현재 브랜치가 9개 커밋 앞선다. 이 R 후속 구현들은 원격 작업 브랜치에 있고 main에는 아직 없다.
- 원격 `dev_mvp`는 `44a6a9d`; 현재 HEAD와 비교하면 `12 ahead / 0 behind`다. 이 브랜치에만 있는 추가 커밋은 없다. 다른 사람의 미push 로컬 작업은 이 감사로 알 수 없다.
- 별도 로컬 미커밋 W 변경: `ingest/job_repository.py`, `job_worker.py`, `pipeline.py`, `preprocess/storage.py`, `router.py`, `main.py`, `preflight.py`; 새 `job_recovery.py`, lease migration과 테스트 등이 있다. 기존 작업을 보존했다. 별도 release 문서는 내용 검토·수정하지 않았다.
- 원격 HEAD [CI 35424777311](https://github.com/2026-Unithon/AskBuddy/actions/runs/35424777311)의 `contracts-unit`, `database`, `browser`, `r-required`가 모두 성공한 것을 재확인했다. 최신 R 기록의 범위는 단위 833개·119 subtests·4 xfailed, migration 28개, v2 API 117 checks, 브라우저 40 checks다.
- 이번 로컬 전체 `pytest tests -q --basetemp=tmp/wr-audit-full-20260919 -p no:cacheprovider`: **839 passed, 4 xfailed, 119 subtests passed**. 추가 W 복구/preflight 테스트 6개도 개별 통과했다. 이 숫자는 미커밋 W 변경을 포함하므로 원격 CI 숫자와 구분한다. 4 xfailed를 정상 통과로 더하지 않는다.
- 이번에는 DB 재구축·브라우저 검증을 다시 실행하지 않았다. 원격 CI가 로컬의 새 lease migration/복구 코드를 검증했다고 주장하지 않는다. 실제 모델 호출, 사람 정답 확정, 운영 배포도 수행하지 않았다.

## W 단계별 판정

| 단계 | 현재 구현/근거 | 남은 구현 또는 인수 |
|---|---|---|
| W0 기준선·채점 | 원시 사실/최종 카드 분리 채점, 고정 분모, scorer v3, 반복/A-A·캠페인 강제·재채점 도구 구현. TEST 정답 278건(dev 180/holdout 98) 감사 기록 존재 | 세부 자료·조건/예외/충돌 커버리지와 독립 사람 판정, 과거 16개 미복구 입력 복원 또는 새 승인 dev 캠페인, 교정 후 기준선 확정. 기존 점수로 현재 품질 향상 선언 불가 |
| W1 분할·원장 선저장 | `extract_facts → _persist_ledger → assemble_assertions → _persist` 연결. 영상 구간·STT 시각, 주장/조건/예외/assembly_state 보존 | 페이지/표/메시지/구간의 서버 locator·hash·attempt, 원시 응답/잘림 복구, 구간별 즉시 checkpoint, occurrence 보존, 완전한 재사용 키와 추출 호출 한도. PDF 페이지별 판독/이미지 보완 필요 |
| W2 revision·대상·충돌 | 기존 `source_facts`, 관계 제안과 카드 검수/수정 경로 존재. 새 계약의 타입·DB 기반 존재 | 서버 entity/variant 확정, 불변 fact_revision 작성·교정 이력, 다중 자료 통합과 충돌 보존, OWNER_ANSWER provenance, 영향 카드만 재조립, 대상 분리/연결 수정. 실제 W 경로에서 새 revision 계약 생산 필요 |
| W3 참조 카드·검수 | 기존 모델 `ExtractionResult` 카드 생성, 원장 참조 연결·미배치 표시, 카드 검수 UI/API 존재 | 모델의 자유 `content` 대신 `CardPlan` 참조 제안→서버 검증/렌더링, 조건/예외/순서 closure, occurrence별 처분, 사실 변경 편집의 새 revision·재승인. 타입 정의만으로 제품 연결 완료 아님 |
| W4 snapshot·발행 | `publish/service.py`의 트랜잭션 기반과 R `index_preparation.py`의 준비/활성화 구현. 기존 approve API에는 임베딩 사전 준비와 카드 변경 재검사 존재 | 실제 승인에서 snapshot 구성→R 색인 준비→공개 포인터/색인/참조/knowledge_revision 원자 전환 연결. 제외·복원·자료 tombstone·legacy RAW와 과거 인용을 같은 계약으로 연결·검증 |
| W5 쓰기 평가 | 평가 실행/반복 비교/오류 분해/원가 기록 도구 기반 존재 | W1~W4 후보의 축별·통합 실험, 원장 재현/정밀도·조립 손실·충돌·대기/제외·검수 시간 보고, 실제 승인 snapshot과 교정된 사람 정답으로 품질/원가 인수 |

### 구현 검토에서 확인한 구체적 간극

1. **동일 값에 붙은 조건·부정·근거가 합쳐질 수 있다.** `ingest/repository.py:insert_source_facts`의 중복 hash는 subject/variant/attribute/value로 계산하고 `(source_id, content_hash)` 충돌 시 기존 ID를 재사용한다. unit/polarity/conditions/exceptions와 evidence occurrence는 이 식별에 포함되지 않는다. 같은 값이라도 조건·부정·시각이 다른 두 주장이 독립적으로 보존되도록 W1/W2에서 바꿔야 한다.
2. **일부 구간 실패가 source 성공으로 끝날 수 있다.** `_extract_facts_all`은 구간 오류를 로그로 남기고 성공 결과를 메모리에서 합쳐 반환한다. 실패 구간 상태를 반환하지 않고 뒤의 `_persist`가 source를 `DONE`으로 설정한다. 성공 구간도 전체 추출 호출이 끝난 뒤 원장에 저장한다. 부분 성공의 명시적 상태와 구간별 저장/재시도가 필요하다.
3. **혼합 PDF의 이미지 정보가 빠질 수 있다.** `preprocess/document.py:read_pdf`는 전체 텍스트를 합쳐 판독하고, `_preprocess_scan`은 텍스트가 있으면 PDF/이미지를 모델에 보내지 않는다. 일부 페이지의 텍스트만 양호한 문서·표/이미지 페이지를 따로 처리해야 한다.
4. **프롬프트의 “새 사실을 만들지 않는다”가 서버 제약은 아니다.** `ingest/schemas.py:ExtractedCard.content`를 모델이 생성하고 `extract/gemini.py:assemble`가 이를 파싱한다. 제품 ingest/cards 경로에서 `CardPlan`/`ExtractionEnvelope` 소비 호출은 확인되지 않는다. 미리보기와 최종 저장을 동일한 검증 renderer로 연결해야 한다.
5. **승인과 v2 검색의 공개판 연결이 없다.** `cards/router.py:approve_card`는 `published_version_id`와 기존 `embed_card`를 갱신한다. 앱 호출부에서 `publish_knowledge`, `prepare_index`, `activate_prepared_index`를 조합하는 W 발행 조정자는 확인되지 않는다. 기존 카드 승인 성공만으로 R v2 snapshot 갱신 성공을 표시하면 안 된다.
6. **점주 원문 전달 이후 지식 반영 소비자가 없다.** R의 `owner_handoff.py:claim_owner_event/heartbeat_owner_event/finish_owner_event`와 재시도 상태는 구현돼 있다. 실제 앱에서 이를 호출해 새 W 발행까지 완료하는 소비자는 확인되지 않는다. 기존 `knowledge_apply.py`의 카드 갱신 경로를 새 outbox 연결 완료로 세지 않는다.

위 1~6은 소스 호출 경로의 정적 검토 결과이며 실제 매장 데이터에 오류가 발생했다고 측정한 결과는 아니다. 각 변경의 인수 테스트로 반례를 고정해야 한다.

## R 단계별 판정

| 단계 | 현재 구현/근거 | 남은 구현 또는 인수 |
|---|---|---|
| R0 인증·평가 | JWT/매장 격리·요청 제한, v2 API/DB 평가, 행동·오류·인용·과차단 지표, pooling/oracle/사람 판정 수입, 반복/A-A·원가 예산 도구 구현 | 매장별 40개 초안(서로 다른 문구 37개) 사람 검토 0개. 실제 E0/후보 반복 비교와 전체 필수 질문 평가 대기 |
| R1 snapshot·색인 | 승인 snapshot 소비, 색인 준비/활성화, 현재 공개/권한 재검사, 멱등·이벤트 회귀, 진단 metadata 보존/정리 구현. 검색 결과 캐시 미사용 | W 발행 접점 연결·실제 snapshot 교체/제외/복구 인수. 운영 로그 원문 중복 OFF·접근 통제·30일 정리 실행의 호스팅 설정 확인 |
| R2 질문·사전·hybrid | 명시 슬롯/검증 문맥, 승인 사전·용어 수입, lexical/vector 독립 회수·RRF 구현. 검토 catalog와 미등록 표현 모델 제안 경로 추가 | 실제 별칭·오타·STT 검토와 효과 비교, 검색 질문 추가 확장의 필요성 판단. 모델 제안의 자유 표현 질문 자동 병합은 미구현 |
| R3 충분성·행동 | 조건·예외·수치 범위·RAW 검증, 5종 행동, 후보 제한 reranker와 fallback, 일반 의미 제안+별도 모델 검증 구현 | 실제 의미 오답/과차단·조건/예외 판정, 사전/hybrid/reranker 단독·조합 효과와 비용/지연 인수. 일반 조건/대상 명확화 범위 확정·구현 |
| R4 답변·인용·명확화 | 승인 참조 서버 렌더링, 현재판 재검사와 답변/인용 저장, TTL·멱등·슬롯 문맥, pending 원문/해석 저장, RAW 제한 경로 구현 | 범용 명확화와 일반 의미 동치 병합은 제한. 제목 없는 RAW·복합 논리도 실제 품질 확인 없이 보편적 지원으로 선언 불가 |
| R5 점주 루프·UX | 점주 원문/occurrence 전달·알림·lease/backoff/재처리 UI, FAQ 현재판 소비·내보내기 권한/감사·v2 화면 구현 | W 지식 반영 완료 소비자와 발행 결과 왕복, 점주 1명·직원 2명의 실제 업로드/질문/답변/재질문 인수, 실기기 Push/fallback |

### R에 남은 순수 구현과 승격의 구분

- **자유 표현의 의미 동치 질문 병합:** 현재 결정론적 의미키/확정 문맥 기반 병합은 있다. `general_semantics.py`와 `reviewed_semantics.py`는 모델의 `equivalent_question_ids`를 거절한다. 제안·평가 도구와 제품 자동 병합은 다르다. 추가하려면 동일 대상/규격/조건/후속 문맥의 서버 검사, occurrence 보존, 오병합 반례와 사람 쌍 판정이 필요하다.
- **대상·조건까지 묻는 범용 명확화:** 일반 모델 경로가 새로 허용하는 선택지는 승인 facts의 temperature/size이며 최대 2회다. 임의 entity·조건/예외의 자유 질문/답변을 검증된 문맥으로 전환하는 전체 경로는 없다. 어떤 슬롯을 제품 지원 대상으로 삼을지 먼저 확정하고 해당 범위를 구현한다. 현재 보수적 ESCALATE는 이 기능 완료를 의미하지 않는다.
- **일반 의미 모델 경로 자체는 이미 구현:** `general_semantics.py`, `general_provider.py`, `v2_router.py`와 저장 연결을 다시 만드는 작업은 필요 없다. 현재 기본 OFF. 코드/모델/store/snapshot에 고정된 인수 release와 사람 정답·오답/과차단·비용/지연 합격 결과가 있어야 활성화한다. 두 모델 호출의 동의가 독립 검증 또는 의미 정확성 보장은 아니다.
- **검색 확장·튜닝은 필요성 확인 후:** 사전·hybrid·reranker는 이미 존재한다. 추가 query variants와 새 용어를 근거 없이 늘리는 작업으로 완료율을 높이지 않는다. 실제 검토 자료와 비교 실험으로 필요한 범위만 정한다.

## C0·공동·운영 단계

| 범위 | 구현된 기반 | 남은 것 |
|---|---|---|
| CP-00A~C 원가 | durable 호출 원장, EXTRACT/ASSEMBLE/STT/EMBED/CLASSIFY/RELATION 및 R 호출 계측, phase/purpose 구분, Storage 목록·운영 시나리오, 결측 UNKNOWN 처리 | `config/rate_card.json` 요율은 null. 실제 rate/FX 확정, object/version별 존재시간과 생성/삭제 이력·전송/직접 조회 billing 수입·미귀속 대조, W 추가자료 비용을 포함한 D21 실측 필요 |
| CP-01~04 계약·DB | DTO/JSON schema/hash/합성 fixture, 발행·참조·outbox·원자성 서비스와 DB 회귀 기반 | 실제 W producer 연결과 공동 경합/삭제/구신판 전환 인수. 계약 기반 구현과 W 제품 전체 완료를 구분 |
| CP-05 평가 | 고정 분모·필수 악화·미판정·반복/A-A·원가 게이트·campaign 연결 구현 | 실제 W/R truth·snapshot·전체 원가 관측으로 인수. 합성 PASS를 실자료 품질 PASS로 전환하지 않음 |
| J0 조기 통합 | synthetic producer/consumer, DB/API/계약 자동 검증 | 실제 W 코드가 만든 snapshot으로 입력→검수→발행→검색→인용 관통 |
| J1 종단 품질 | 비교·보고 하네스와 판정 도구 | 원본/truth/snapshot/설정 동결, W만/R만/W+R 비교, 원본 누락·조립·검색·답변·과차단 분리, 반복/A-A 후 승격 |
| J2 CI·worker·E2E | `r-validation.yml`: unit/schema/fixture, DB 재구축, lint/typecheck/build 및 브라우저, 실패 집계 `r-required` | 실제 W 업로드·점주 답변 E2E, 별도 worker 배치/운영, 단계 checkpoint·프로세스 강제 종료/lease 경합·알림 복구 인수 |
| J3 운영 | 안전한 v1 새 질문 차단/v2 진입, R 플래그·인수 파일·보존 기반 | 배포 버전/마이그레이션/환경 동결, 백업/복구·운영 로그·모바일 PWA·Push/QR·경보/담당과 운영 smoke. 현재 감사는 운영 상태를 확인하지 않음 |

Storage의 현재 `storage_inventory.py:storage_cost`는 관측된 총 bytes×전달받은 months 계산이다. object별 생성·삭제 이력의 실제 시간 적분이나 전체 egress 정산 완료로 볼 수 없다. 목록 API 실패 시 일부 목록만 반환하는 경로도 있어, 관측 누락을 전체 원가로 오인하지 않는 completeness 보강을 포함해야 한다.

로컬 W worker 변경에는 QUEUED claim, 90초 lease, 20초 heartbeat, 만료 작업 회수, 동시 작업 2개 제한, `ShortSession`을 통한 짧은 DB 점유가 있다. 다만 `main.py`에서 API 내부 recovery task를 시작하고 ingest route도 `BackgroundTasks`를 사용한다. **별도 영속 worker 프로세스 완성으로 판정하지 않는다.** 우선 기존 미커밋 작업의 소유 범위를 보존하고 최신 migration 포함 DB·중단/경합 테스트를 통과시킨 후 통합해야 한다.

## 남은 작업의 권장 순서

1. **통합 기준 고정:** R 9개 후속 커밋의 main 합류 검토, 별도 로컬 W 변경의 범위/commit·DB 검증을 구분한다. 이번 pull은 main 병합 완료나 로컬 W 검증 완료가 아니다.
2. **W1/W2 보존 결함 우선:** 조건/부정/occurrence 중복 손실, 구간 부분 실패·checkpoint, 원시 응답/잘림, 혼합 PDF를 고친다. 이 작업은 실제 유료 평가 승인 없이 합성 자료로 진행 가능하다.
3. **W2/W3 새 계약 제품화:** entity·revision·provenance→참조 CardPlan→서버 렌더링/검수→수정 재승인. 기존 타입과 DB 기반을 재사용한다.
4. **W4·R1·R5 실제 연결:** 승인 snapshot 생산/원자 색인 발행과 OWNER_ANSWER 소비자를 연결한다. 먼저 합성 자료로 점주 1명·직원 2명 왕복을 검증한다. 실제 정답 검토 완료를 기다릴 필요는 없다.
5. **R 남은 의미 범위:** 자유 표현 병합과 범용 명확화의 지원 슬롯·판정 계약을 정하고 해당 구현/반례를 추가한다. 현재 일반 의미 경로의 구현 완료와 혼동하지 않는다.
6. **공통 원가/worker:** Storage 수명·전송·완전성 및 원가 귀속, 독립 worker·단계 복구·공동 E2E/CI를 완성한다.
7. **회의 후 실제 평가:** 사람 정답·요율/예산·승격 기준 확정→승인 snapshot→dev 반복/A-A·조합 비교→사전 등록 holdout→허용 범위 활성화.
8. **운영 인수:** 통합 버전으로 배포/복구·실기기·로그/접근 통제·알림/경보를 확인한다.

## 팀 인계 책임과 최종 연결 파이프라인

아래는 남은 구현을 합친 **목표 흐름**이며 현재 전체 연결 완료를 뜻하지 않는다. 각 담당자는 자신의 API·DB·프롬프트·관련 UI·평가까지 맡는다.

| 접점 | 주 구현자 | 상대가 받는 산출물/검토 |
|---|---|---|
| 원본→추출→원장/revision→카드 검수 | W | R은 승인에 필요한 대상·규격·조건·예외·근거 보존을 검토 |
| 공통 사실/RAW renderer | W | R은 질문별 참조 선택과 답변 연결을 담당 |
| snapshot 생산·최종 발행/제외 | W | R은 매장·hash·버전·승인 참조를 검사하고 소비 |
| 색인 준비/활성화 어댑터 | R | W가 준비 결과를 받아 최종 공개 트랜잭션 안에서 활성화; R이 독립 발행하지 않음 |
| 질문·명확화·답변/인용·질문 병합 | R | W는 실제 승인 지식의 적용 범위·조건 보존을 검토 |
| 점주 원문·질문 occurrence·outbox | R | W가 답변 ID와 검증된 질문 문맥을 멱등 소비 |
| ApplyOwnerAnswer·검수/발행·처리 결과 | W | R이 상태·FAQ·학습·재질문·알림을 갱신 |
| worker·공통 원가/등록·Storage 계측 | W | R은 읽기 호출·운영 원가 집계와 공동 E2E/알림을 담당 |

등록→공개:

```text
[W] 업로드 → 자료 분할·위치/시각 보존 → 사실 추출·구간별 저장
 → 대상/규격·불변 revision·충돌 처리 → CardPlan 참조 제안
 → 서버 검사·공통 렌더링 → 점주 검수·승인 → snapshot 구성
 → [R] 색인 준비 → [W] 공개판·색인·참조 원자 발행
 → [R] 현재 승인 지식 검색 가능
```

질문→답변:

```text
[R] 질문 + 인증 + 검증된 문맥 → 해석·사전·hybrid·선택적 reranker
 → 근거 충분성 판단
   ├─ 충분: AnswerPlan → 서버 검사·렌더 → 저장 직전 공개판 재검사 → 답변·인용
   ├─ 모호: CLARIFY → 사용자 답변·문맥 검증 → 다시 판단
   ├─ 부족: 질문 저장 성공 → ESCALATE·점주 알림
   └─ 정책 대상: REFUSE / SAFE_ROUTE
```

점주 답변→지식 갱신:

```text
[R] 점주 원문 저장·직원 전달 + outbox
 → [W] 이벤트 claim·지식화·NEW/IDENTICAL/SUPPLEMENT/CONFLICT 처리
 → 필요한 검수 → snapshot·색인 발행 → 처리 결과
 → [R] 반영 상태·FAQ·학습·알림 갱신 → 재질문에 새 승인 지식 사용
```

순서는 공통 기준 브랜치 반영 → 실제 W 코드의 합성 snapshot 연결 → 점주 1명/직원 2명 왕복 → 장애·동시성·재시작 검증/CI → 회의 후 실자료 반복·A/A 평가 → 운영 인수다. 계약 변경에는 schema·정상/거절 fixture·양쪽 테스트를 함께 제출하고, 공통 파일은 변경 묶음마다 주 편집자 한 명을 정한다.

## 회의에서 확정할 항목 — 기존 대기 유지

- 사람 정답 담당자와 검토 일정: 두 매장 질문의 기대 행동·필수 facts/RAW·금지 주장·적용 범위·조건/예외. W TEST 라벨의 실제 매장 사실 확인과 세부 커버리지도 구분한다.
- 유료 평가: 모델/자료 범위, 최대 금액·호출 수, 요율/환율 기준, 반복/A-A·holdout 계획과 중단 기준. 현재 R 통합 예산 도구를 W 추출/Storage까지의 전체 예산으로 해석하지 않는다.
- 제품 범위: 범용 명확화 슬롯과 자유 표현 병합 채택 여부, 의미 오답/오병합·과차단·비용/지연 승격 기준. 기준을 먼저 정하고 결과에 맞춰 바꾸지 않는다.
- 담당/인계: W producer·발행 조정·OWNER_ANSWER consumer·worker의 담당과 인계 버전, R 소비 검토·공동 E2E 일정, 운영 인수 담당.
- W 과거 실행: 미복구 16개 입력 확보 가능 여부와 불가할 때 새 기준선 캠페인 승인.

사용자가 이미 대기로 정한 사람 검토·유료 평가를 이 감사로 재개하지 않는다. 상세 결정 목록은 [R 회의 대기 문서](../plan/R_MEETING_DECISIONS_20260918.md)를 따른다.
