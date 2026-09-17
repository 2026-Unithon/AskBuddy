# R 단독 평가·조회 보완 및 잔여 범위 검토 — 2026-09-16

## 이번 구현

| 영역 | 구현 | 판정 경계 |
|---|---|---|
| 사람 관련성 판정 | `retrieval_review.py`: pool 원본 재구축 검증, hash+정확한 card/version/block에 판정 연결, 중복/외부/오래된 판정 거절 | hash는 내용 결속이며 검토자 인증/전자서명은 아니다 |
| 검색 지표 | precision@k, recall@k, 반환 목록 내 MRR, binary nDCG@k, 검토/미검토 개수 | 전체 모집단 판정 전 recall/MRR/nDCG는 null. relevant 0개 분모도 null. precision@k는 반환량이 k보다 적어도 분모 k |
| 사실 의미·근거 | `evidence_truth.py`: stable meaning_id→fact_id→fact_revision_id 매핑, 현재 승인판/대상 검사, requires 재귀 포함, 사실 재현율·완전 근거 회수 | 의미 ID/필수 사실 선택은 사람 제공. 카드가 있다는 이유로 의미 정답 인정하지 않음. typed 사실용이며 RAW 의미 매핑은 별도 |
| oracle 진단 | `oracle_diagnostics.py`: 검색 회수 검사, 정답 사실 블록 주입 전후 planner, 후보 검증 통과/거절 관찰 | 순수 격리 진단. 운영 저장/검증을 우회하지 않음. ANSWER나 validator 통과도 semantic_correct=null |
| 필수 비답변 | `Judgment.action_correct` 추가. 필수 CLARIFY/ESCALATE의 검토 누락/실패를 캠페인에서 차단 | action 이름만 일치하는 것을 적절한 되묻기/이관으로 간주하지 않음 |
| 다회 평가 | `dialogue_evaluation.py`: 서버 context ID/revision·허용 선택지만 연결, 실패 뒤 NOT_RUN도 고정 분모 유지, receipt·case/config/source 지문 보존 | 순서 일치는 의미 완료율이 아님. API snapshot ID/revision 대조이며 별도의 원본 snapshot hash 검증/실자료 의미 판정 필요 |
| 용어 검토 | `lexicon_review.py`: 수집 입력 중복 제거·출처/날짜/이용 근거 보존·상충 별칭/수량 문장 거절 | REVIEW_REQUIRED, 승인 버전 없음. 실제 웹 fetch/수집 사이트 선정 또는 새 용어 승인은 수행하지 않음 |
| R1 관측 | v2 receipt metadata에 usage operation/query/rerank logical call ID, 저장 전 경과 시간 추가 | 저장 전 시간은 종단 p95가 아니다. 실제 원가/모델 정보는 연결된 usage 원장으로 대조 |
| R5 내보내기 | `GET /learn/v2/knowledge/export`: 서버 회원 권한·점주 확인, 현재 승인 카드만 JSON, EXPORT 감사 기록, 요청 제한/timeout/no-store | 현재 승인 카드의 export 문서다. 일부 제외된 결과를 완전한 PublishedKnowledgeSnapshot으로 표시하지 않음 |

### 사용 접점

- 오프라인 CLI: `api`에서 `python scripts/report_r_retrieval.py --input review-input.json --output review-report.json`.
- 입력: `{ "pool": <build_retrieval_pool 결과>, "judgments": [...], "rankings": {"experiment": [["card","version","block"]]}, "k": 10 }`. rankings 생략 시 pool의 세 채널을 사용한다.
- 판정 행: `pool_hash`, `reference` 3문자열 배열, `relevance` (`RELEVANT/IRRELEVANT/UNDETERMINED`), `reviewer`, `reason`. 원본 pool 내부의 null 판정 칸을 고치지 않고 별도 파일로 작성한다.
- 사실 truth: `pool_hash`, `truth_version`, `reviewer`, `reason`, `required` 목록. 각 원소는 `meaning_id/fact_id/fact_revision_id`. `evidence_recall`과 `diagnose_oracle` 내부 평가 함수에 전달한다.
- `collect_dialogue`는 격리 API client, case/turn 목록, 인증 headers, 기대 snapshot ID/revision, provider_mode와 configuration을 받는다. 실제 실행 권한·평가 원가 귀속은 호출자가 별도 준비해야 한다.
- 내보내기 UI 연결은 release 작업이다. 기존 v2 rollout 기본 OFF를 변경하지 않았다.

## 검증과 수정

1. 초기 Docker 엔진이 내려가 있어 통합 시작 실패. 설치된 Docker Desktop을 시작한 뒤 일회용 PostgreSQL을 사용했다. 운영 DB/.env 연결을 사용하지 않았다.
2. 첫 통합에서 새 다회 fixture가 ICE 승인 사실에 HOT를 선택하도록 하드코딩한 오류를 발견했다. 실제 승인 규격을 선택하게 fixture를 수정했다. 제품/평가의 선택지 검사는 유지했다.
3. 재실행 통합 통과: PostgreSQL 17.11, 전체 migration **26개**, M2 40, reranker 13, 답변 저장 16, v2 API 92, 점주 전달 21 검사 및 선행 원가/보안/W/문맥 검사 통과. 새 다회 2턴은 각각 실제 DB receipt response와 대조했다.
4. 다회 산출물 provider/config/source 지문을 마지막으로 보강한 뒤 전체 단위 **575 tests / 119 subtests 통과**. DB 검증은 동일 문맥/저장 경로의 앞선 실행이고 마지막 산출물 metadata 추가는 단위에서 재확인했다.
5. 검색 평가 CLI 생성, 미판정 보존, 기존 출력 덮어쓰기 거절 smoke 통과. 변경 영역 24개 파일 매장 격리 정적 검사와 diff 공백 검사 통과.

기존 의존성 deprecation 경고 1개가 있다. 테스트 임베딩/SDK는 합성이며 실모델 성능·비용 개선을 입증한 것이 아니다. commit/push 및 운영 배포는 수행하지 않았다.

## 전체 계획 대조와 남은 작업

R0~R5의 목표/공동 계약을 바꾸지 않았다. 기존 보수적 planner가 지원하지 못하는 조건·RAW를 자동 승인하는 변경은 넣지 않았다. D18 캠페인 승격과 비용 미확인 차단도 유지한다.

| 항목 | 현재 상태 | 다음에 필요한 것 |
|---|---|---|
| R0 수집→관련성 검토→검색/사실 지표→반복 캠페인 | 실행 가능한 모듈 및 합성 회귀 확보 | 실제 승인판 30~50 질문과 의미 정답 검토, 현실적인 평가 실행 |
| R1 색인·현재 공개·stale·관측 연결 | 구현/DB 회귀. operation/call 연결 보완 | 실제 호출의 비용·지연 원장 대조 및 종단 p95 측정 |
| R2 사전·독립 검색·RRF | 구현/DB 검증, 공개 용어 검토 입력 준비 | 승인할 실제 별칭/STT 사례와 출처·이용 근거. 사전/검색 개별 효과 평가 |
| R3/R4 명시 슬롯·수치·문맥·참조 | 구현/반례. 필수 비답변 의미 검토와 다회 평가 추가 | 미확정 적용 범위 및 RAW/복합 절차의 충분성 판단 설계·검토 자료. 현재 안전하게 보류되는 기능을 답변 가능으로 넓히는 구현은 남아 있음 |
| R5 전달·알림·내보내기 | 기존 원문 전달 + 새 권한/감사 내보내기 검증 | W ApplyOwnerAnswer/공개 후 FAQ·학습·재질문 갱신 종단 연결 |
| 의미 pending 묶음 | 저장 서비스는 확정 문맥 묶음 지원, planner는 자동 의미 동치 추정하지 않음 | 안전한 의미 동치 판정 근거. 문구 유사도만으로 다른 질문을 합치지 않음 |
| 실자료 사전/hybrid/reranker 개별·통합 효과 | 하네스/어댑터 준비 | 동일 정답판·변경축 고정·실제 모델/원가/사람 판정 |
| W/사용자 공동 | 기존 계약·fixture 유지 | 적용 범위 확인 근거, 실제 발행·색인 전환·지식화 성공 인수 |
| release | 이번 dev에서 배포/UI 연결하지 않음 | 실제 Push/기기/운영 환경 및 사용감 검증 |

**R 전체 완료로 닫지 않는다.** 이번에 여러 R 단독 개발 단위를 진행했지만, 복합 의미 판단/자동 의미 묶음의 런타임 확장과 실자료 실행은 별도 미완료다. W가 없어서 모든 남은 작업이 막힌 것은 아니다. 검증된 평가 기반으로 먼저 실제 실패 사례를 확보하고, 의미를 추정 승인하지 않는 범위에서 후속 구현해야 한다.
