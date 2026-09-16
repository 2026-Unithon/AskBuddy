# AI 개선 계획 엄밀 검토 결과

검토일: 2026-09-14 · 코드 대조 기준: `0b8e1c4` · 대상: MVP 정본, 개발 TODO, 이관 경계·실험설계

## 1. 결론과 범위

기존 계획의 원장 우선·점주 승인·유연한 카드 양식·쓰기/읽기 분리는 유지했다. 반면 최신 수정값의 무조건 사용, 자유 생성 뒤 숫자/낱말 검사만으로 안전성 주장, 읽기 개발 전체의 직렬 대기, 불안정 사실 제외는 수정했다.

갱신안은 **C0에서 공통 계약을 구체화한 뒤 두 사람이 병렬 구현할 수 있는 계획**이다. 독립 재검토에서 검토 범위 내 잔여 P0/P1은 발견되지 않았고, 마지막 실험 ID 별칭 불일치도 수정했다. 계획 검토 완료는 새 구조의 구현 완료·실측 성능 개선·운영 배포 승인을 뜻하지 않는다. 모든 입력에서 절대 성능 개선을 보장하지 않으며, 구조적으로 막는 오류와 사람 평가가 필요한 의미 오류를 분리한다.

검토 방법은 세 문서 전체 대조, 관련 코드·migration·평가 스크립트 확인, 독립 검토자의 반례 검토, 지적 사항 반영 후 재검토, Markdown/JSON/링크/변경 범위 검사다. 운영 DB·외부 모델 호출·holdout 내용 열람·실험 데이터 변경은 하지 않았다.

## 2. 계획에서 발견하고 반영한 결함

| 중요도 | 발견 사항 | 계획에 반영한 해결 | 정본 위치 |
|---|---|---|---|
| P0 | 최신 `effective_facts`를 사용하면 승인 전 정정이 공개 답변에 섞이거나 과거 인용이 변함 | 작업용 view와 승인 card_version→불변 fact_revision 분리 | MVP 7·31-4, TODO W2/W4/R1 |
| P0 | 숫자·단어 부분집합 검사는 HOT/ICE 교환·부정 삭제·선행조건 삭제를 허용 | 모델은 ID 선택·배치, 서버는 대상·규격·조건·의존성을 보존해 렌더링. 의미 평가는 별도 | MVP 15·31-3/5, TODO W3/R3/R4 |
| P0 | CLARIFY가 기존 NO_ANSWER로 처리되면 불필요한 WAITING·알림 발생 | chat v2의 5개 action과 별도 ERROR, v1 호환·이력·UI 전환 | MVP 13·31-5, TODO C0/R4 |
| P0 | 자유본문 카드 수정·점주 답변 카드화가 새 사실 계약을 우회 | W가 OWNER_EDIT·knowledge_apply·공개 서비스를 소유. 원문 RAW 호환, 모델 파생 사실에 승인 상속 금지 | MVP 13-2·30·31-6, TODO W2/W4/R5 |
| P1 | 원장이 이미 있어도 reduce 후 적재하면 map 누락·손실을 분리할 수 없음 | 구간별 raw/assertion/occurrence를 조립 전에 저장하고 단계별 측정 | MVP 22-4·31-2, TODO W0/W1 |
| P1 | 미연결 사실 전부를 손실로 세거나 숫자만 검수하면 보류·부정·예외를 숨김 | LINKED/REVIEW_PENDING/EXCLUDED(reason), 미처리·오연결·렌더링 누락·제외율을 분리 | MVP 31-3, TODO W3, 실험 5절 |
| P1 | 13 완료 전 14 착수 금지가 2인 병렬 개발을 막음 | C0 합성 승인 fixture 이후 W/R 병렬, 실제 W snapshot으로 종단 검증 | MVP 23·30, TODO 실행 순서 |
| P1 | RRF 앞 공통 vector 하한으로 lexical-only 정답 탈락 | 매장/공개 필터는 공통, 후보는 채널별 회수·융합 후 충분성 검사 | MVP 31-5, TODO R2/R3 |
| P1 | 같은 원문의 문맥 질문이 잘못된 pending으로 합쳐질 수 있음 | 원문+확정 대상/규격/조건/context snapshot 보존, 의미 중복키와 요청 멱등키 분리 | MVP 19-3·31-5, TODO C0/R4 |
| P1 | 플래그 해제만으로 schema·색인·공개 데이터·v1이 안전하게 돌아가지 않음 | 가산형 migration·호환 content·조합별 검증, 모든 운영 legacy reader에 안전 shim 요구 | MVP 31-7, TODO J0/J3 |
| P1 | 불안정·실패·교집합 밖 사실 제외로 어려운 사례가 분모에서 사라짐 | 전체 T/Q 고정 분모, A/B 반복·A/A·실패 보존·사전 holdout 캠페인 | 실험 4~7절, TODO W0/J1 |
| P1 | 질문 차단과 후보 답변 검증에 같은 false_block 이름 사용 | 최종 false_abstention_rate/block_precision과 validator_* 분리 | MVP 20-4, 실험 6절 |
| P1 | W 누락 뒤 올바른 ESCALATE를 종단 성공으로 집계할 수 있음 | 원본 기준 Q_source_A·e2e_grounded_answer_rate 고정, R 정책 성공과 종단 ANSWER 실패 분리 | MVP 20-4, 실험 4·6절, TODO J1 |
| P1 | 실험 W/R 번호와 TODO W/R 번호가 다른 작업을 지칭 | 실험 X-* namespace와 TODO 연결 열로 분리 | 실험 8절 |
| P1 | 기존 하네스가 새 지표·상태·전체 분모를 측정하지 못함 | 비교/변동/추출/읽기/holdout 하네스 이관을 C0/W0/R0 완료 조건에 포함 | 실험 7-1, TODO W0/R0 |
| P2 | 과거 합계·샘플·지연·손실률이 현재 재현값처럼 보임 | dev 180 TEST·8개 고유 읽기 smoke·추출 실행 artifact 부재를 구별, 과거 수치는 역사 기록 | MVP 22-4, 실험 2·10절 |
| P2 | binary 흐름도·상태표 이탈·fixture 없는 hit 라벨·WAITING 오류 문구 | 새 분기와 표 정리, 예시 라벨은 fixture 전제, 기존 pending 저장 실패로 한정 | MVP 2·6·19·20절 |

P0/P1은 발견 당시 영향도다. 이 표의 ‘해결’은 **계획 계약의 보강**이며 애플리케이션 취약점이 이미 수정됐다는 뜻이 아니다.

## 3. 코드 근거와 국소 재현

| 근거 | 확인 내용 | 계획상 대응 |
|---|---|---|
| [ingest/pipeline.py](../../../api/app/ingest/pipeline.py) 67·95·133·166·416·475행 | 추출/선택적 reduce 뒤 최종 결과의 사실 적재, 2패스는 구간 경로에 한정 | raw map 선저장과 유형별 구간 계약 |
| [source_fact_ledger migration](../../../supabase/migrations/20260914140000_source_fact_ledger.sql) 21·55행, [fact_correction migration](../../../supabase/migrations/20260914190000_fact_correction.sql) 31행 | 사실 테이블·현재 연결·최신 수정 view 기반은 존재 | ‘원장 미구현’ 대신 기반 존재/런타임 미완료 구분, immutable publication 추가 |
| [learn/answering.py](../../../api/app/learn/answering.py) 77행 | 화이트리스트·숫자 집합·낱말 집합 검증 | 값-대상 결합·부정·조건 보존과 참조 렌더링 |
| [reg/retrieve.py](../../../api/app/reg/retrieve.py) 69·74행, [reg/router.py](../../../api/app/reg/router.py) 28행 | 일부 anchor 일치와 vector 검색, 레거시 store ID 입력 | R0 인증 정리와 채널별 후보/충분성 계약 |
| [cards/repository.py](../../../api/app/cards/repository.py) 167행, [learn/knowledge_apply.py](../../../api/app/learn/knowledge_apply.py) 35·145행 | 본문 초안·점주 답변 카드 버전 생성 경로 | W의 공통 revision/publication 서비스로 수렴 |
| [learn/router.py](../../../api/app/learn/router.py) 95·1028행 | 원문 question_key 기반 pending 묶음 | 문맥을 포함하는 의미 중복키 |
| [team/metrics.py](../../../api/app/team/metrics.py) 167행, [run_eval.py](../../../api/scripts/run_eval.py) 139행 | citation 없는 HIT 위주 무근거 집계, 제한적 종료 코드 | 새 의미 오류/정책/종단 지표와 명시적 승격 게이트 |
| [compare_runs.py](../../../api/scripts/compare_runs.py) 47·102·109행 | 성공 run·교집합·안정 사실 중심 비교 | 전체 시도/고정 분모/비교 가능성 검사 |

현재 답변 검증기의 순수 함수만 AST로 분리해 다음 세 반례를 실제 실행했다. 모델·DB·앱 서버를 호출하지 않았고 소스 파일도 수정하지 않았다.

| 원문 대비 잘못된 후보 답변 | 현재 검증 결과 |
|---|---|
| HOT 물 275ml / ICE 물 225ml → HOT 225ml / ICE 275ml | accepted=true, reason=null |
| ‘실온에 보관하면 안 됩니다’ → ‘실온에 보관하면 됩니다’ | accepted=true, reason=null |
| ‘전원을 끈 뒤 세척’ → ‘기계 세척’ | accepted=true, reason=null |

이 재현은 **후보가 주어졌을 때 현재 검증기가 잘못된 문장을 허용함**을 증명한다. 실제 모델이 이 문장을 생성하는 빈도나 운영 오답률을 측정한 결과는 아니다.

## 4. 두 사람의 인계와 검토 책임

W가 인계할 것은 임의 최신 JSON이 아니라 승인 card_version·fact revision·근거·블록이 고정된 PublishedKnowledgeSnapshot이다. R은 이를 검색·답변에 소비하고 공개/제외 경합을 저장 직전에 다시 검사한다.

- W: 업로드·원장·조립·렌더러·검수·공개·점주 답변의 지식 반영, 자신의 화면과 쓰기 평가.
- R: 인증·질문/문맥·검색·AnswerPlan·답변/명확화/이관·원문 전달·알림, 자신의 화면과 읽기 평가.
- 공동: C0 schema/fixture·공유 파일 주 편집자, migration/색인 준비, 실제 종단 평가, CI·롤백·운영 인수.

자기 파이프라인만 통과했다고 완료하지 않는다. W는 R의 권한·인용·조건 보존을, R은 W의 원장 보존·승인 snapshot·충돌 처리를 교차 검토한다. 실패 증거·수정 책임·재검증 결과를 남긴다.

## 5. 검증한 것과 아직 검증하지 않은 것

문서 검증 결과: 5개 변경 문서의 UTF-8·코드 fence 짝·표 열 수, JSON 예제 1개 파싱, 로컬 링크 16개 존재 검사와 `git diff --check`가 통과했다. 섹션/작업 ID, 5개 action·ERROR 구분, 지표 분모·병렬 의존성·공개/레거시 계약도 교차 검토했다. CLAUDE.md는 이전 단독 담당·검색/평가 규칙이 새 정본과 충돌하지 않도록 요약을 동기화했다. Markdown 렌더 이미지나 앱 전체 테스트를 수행한 것으로 해석하지 않는다.

아직 수행하지 않은 것:

- 새 schema/API/DB/renderer/worker 구현과 통합 테스트.
- 실제 Gemini 호출·동일 모델 A/B·비용/지연 측정·운영 성능 검증.
- 운영 migration 적용 상태·배포·실기기 E2E.
- holdout 내용 검토·개봉·평가, 점주 미확인 TEST 정답지의 실제 점주 승인.

## 6. 착수 조건과 남겨둔 판단

계획 수준에서 구조는 정리됐으나 아래 항목은 구현 또는 실험 전에 명시적으로 확정한다.

| 시점 | 담당 | 남은 산출물 | 미확정 시 처리 |
|---|---|---|---|
| C0 | W/R | 실행 가능한 schema·정상/거절 fixture·정책 문구·파일 주 편집자·migration 순서 | 계약 의존 구현의 완료 판정 보류. R0 보안 정리는 병행 가능 |
| W0/R0 | 각 담당 | 원본/질문 truth·판정자·split/hash·새 지표 하네스 | 기존 CLI exit 0이나 과거 smoke로 승격하지 않음 |
| 실험 사전 | 공동 | 최소 의미 효과·비열등 마진·비용/지연 예산·반복/중단 조건 | 탐색·개발은 가능, 기본값 승격 금지 |
| 실 API 실행 | 각 담당 | 실제 가용 모델/응답 식별자·설정·토큰/비용 관측 | 설정 문자열을 호출 성공 또는 성능 증거로 쓰지 않음 |
| J1/J2/J3 | 공동 | 실제 원본 종단·회귀·복구·롤백·운영 검증 결과 | 문서 완료와 제품 출시 완료를 구분 |

표본 0오류는 무오류 보장이 아니다. 반복 3회는 통계적 충분성 보장이 아니다. 서버 렌더링은 원장과 표현의 결합을 강제하지만 잘못 추출·승인·선택한 사실을 자동으로 참으로 만들지는 못한다. 이 제한을 숨기지 않는 것을 최종 검토 기준으로 유지한다.
