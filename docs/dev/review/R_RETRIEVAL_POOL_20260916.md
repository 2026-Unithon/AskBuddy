# R0 검색 후보 검토 준비와 잔여 작업 — 2026-09-16

## 이번 범위

DEV_TODO R0의 vector·lexical·oracle pooling과 미검색 표본 검토 중 **오프라인 검토 자료 생성**을 구현했다. W의 발행 코드와 제품 검색 경로를 변경하지 않는다. 정답 라벨과 실자료 성능은 생성하지 않는다.

- `api/app/team/retrieval_pool.py`: 승인 snapshot 계약/hash 검사, card/version/block의 정확한 참조 검사, 채널별 순위 보존 및 합집합. 중복·다른 버전 참조 거절.
- 합집합에 없는 승인 블록을 seed/question/snapshot hash 기반 순서로 선택한다. 요청량·가능량·실제 표본량·검토 밖 잔여량을 기록한다. 재현 가능한 표본이며 모집단 재현율 추정 도구는 아니다.
- snapshot 전체를 보존하므로 사실·조건·예외·RAW 원문을 대조할 수 있다. oracle도 미판정이다. `relevance/reviewer/reason=null`, `truth_status=UNREVIEWED`.
- pool hash는 생성 원본의 내용 지문이다. 검토자가 출력 내용을 편집하면 원본 hash와 달라진다. 검토 결과의 별도 저장/검증 계약은 후속 작업이며 현재 출력으로 캠페인을 승격하지 않는다.
- CLI는 기존 파일을 덮어쓰지 않는다. 내부 평가 자료이므로 승인 매장 원문을 포함한 출력은 제한된 평가 저장소에 보관한다.

## 사용

`api`에서 `python scripts/build_r_retrieval_pool.py --input input.json --output pool.json`.

입력 키는 `snapshot`(전체 PublishedKnowledgeSnapshot), `question_id`, `question`, `channels`, `sample_size`(0 이상 정수), `seed`(사전 고정 문자열)다. channels는 `lexical/vector/oracle` 세 키를 모두 포함하며 값은 순위대로 `[card_id, card_version_id, block_id]` 문자열 배열의 목록이다. 후보가 없으면 빈 목록을 명시한다.

현재 실제 SQL의 독립 채널 결과를 자동 수집하지 않는다. 합성 fixture 또는 별도로 수집한 정확한 승인판 후보를 입력한다. `unpooled_sample`은 세 입력 목록 어디에도 없는 후보이며, lexical/vector에서 빠졌어도 oracle에 있으면 이미 pool에 포함된다.

## 검증

- 신규 반례/합집합/표본 테스트 7개 통과.
- 전체 API 단위 회귀 **542 tests / 116 subtests 통과**. 기존 의존성 deprecation 경고 1개.
- CLI 생성과 동일 출력 경로 재실행 시 덮어쓰기 거절 확인.
- 변경 모듈 store-isolation 정적 검사 통과. DB/라우터/migration 변경 없음. 이번 작업에서 Docker 통합 검증은 재실행하지 않았다.

## 이어갈 일과 담당

| 순서/담당 | 남은 일 | 완료 근거 |
|---|---|---|
| 다음 R 단독 | 같은 공개판에서 lexical/vector 독립 순위 수집을 이 도구에 연결 | 검색 상위 융합 후보에만 갇히지 않는 재현 자료 |
| R 단독 | pool hash에 묶인 관련성 검토 수입, 안정적 사실 의미 ID·snapshot별 근거 매핑 | 외부/오래된 판정 거절, 미판정 보존 |
| R 단독 | recall@k/MRR/nDCG와 완전한 근거 집합, oracle 검색/주입/검증 전후 분해 | 정답 공간의 검토 범위 명시, 운영 검증 우회 없음 |
| R 단독 | 다회 대화 평가, 필수 비답변 의미 검토, 복잡한 조건/절차·RAW 적합성 보완 | 보류를 임의 성공으로 바꾸지 않는 반례·평가 |
| R 단독/자료 필요 | 사전·hybrid·reranker 개별 및 통합 평가, 관측/원가 연결, 내보내기 권한·감사 범위 점검 | 합성 계약 검증과 실제 품질·비용 결과 구분 |
| 사용자·팀 | 실제 매장 질문 30~50개와 기대 행동/필수 사실/금지 주장 검토 | 매장 사실은 점주, 검색 관련성은 팀. 기존 라벨은 재사용하되 출처·버전/범위 확인 |
| 사용자·W/R | 규격 축·적용 범위 미확정 사례, 별칭/STT 변형 승인 | null이나 한 규격만 관측됐다는 이유로 적용 범위 확정 금지 |
| W 후 공동 | 실제 승인 발행→PrepareIndex 소비→공개/색인 전환, 승인 취소/재시도/경합 | W 생산 snapshot으로 공동 DB/API 인수 |
| W 후 공동 | OWNER_ANSWER→ApplyOwnerAnswer→공개→FAQ/학습/재질문 | 원문 전달 성공과 지식화 성공을 각각 확인 |
| release | 실제 Push/기기·배포 환경 연결과 사용감 개선 | dev 계약 검증과 별도 인수 |

사용자에게 미래 사용량을 다시 확정해 달라고 요구하지 않는다. C0에서 합의한 첫 달/안정기 시나리오와 실제 계측을 유지한다. W 대기 중에도 위 R 작업을 진행할 수 있으므로 R 전체 완료 또는 W만 남았다고 선언하지 않는다. R0 pooling TODO는 실제 수집·사람 검토가 남아 있어 닫지 않는다.
