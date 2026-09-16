# R 순차 구현 현황 — 2026-09-15

> 후속 검증 완료: Docker 연결을 복구해 PostgreSQL 15.19에서 원장 14 + 보안 9 + W 임베딩/읽기 집계 6 = 29개를 통과했다. 전체 회귀 359 tests / 73 subtests 통과. 현재 인계 기준은 [W 착수 인계](../plan/C0_W_START_HANDOFF.md)이며, 아래 Docker 미가동 설명은 이전 실행 이력이다.

기준: C0 결정서 §6~8, 원가 계획 §7~8, 개발 TODO R0~R5. 사용자는 W의 추가 작업이 필요한 항목을 제외한 R 작업 전체의 순차 진행을 위임했다. 이 기록은 전체 완료 선언이 아니다.

## 순서와 현재 상태

| 순서 | R 작업 | 이번 구현·검증 상태 | 남은 인수/의존성 |
|---|---|---|---|
| 1 | CP-00B 답변 호출 계측 | 이전 답변 adapter/채팅·평가 연결 유지 | 기존 PG17 원장 검증 14/14 기록 유지 |
| 2 | CP-00B 검색 임베딩 | embed_texts 단일 공급자 진입점에 관측 추가, 비동기 recorded_embeddings adapter. 채팅·평가·reg 검색 연결, PG15 등록 EMBED 저장 검증 | W ingest 카드/관계 흐름의 adapter 주입은 W 편집 범위 |
| 3 | CP-00B 읽기 집계 | QUERY/ANSWER receipt를 PK별 한 번 집계. store/run/EVALUATION/OPERATING 한정. 종료 run 저장 트랜잭션의 metrics에 추가, PG15 필터·합계/미확정 검증 | 전체 W+R 비용 인수가 아닌 읽기 범위 |
| 4 | CP-00C 운영 계산 | LOW/BASE/HIGH × 1/3/6/12개월 × 추가 턴 3종 = 36개 가정. 관측 누락·요율/환율 버전 누락 시 UNDETERMINED | 추가자료 AI·Storage/전송비 등 W 입력과 관측된 요율/환율 필요. 숫자를 발명하지 않음 |
| 5 | CP-01/R0 인증·유입·시간 선행 | 기존 pending helper의 store_id 누락 수정. DB 원자 요청 제한 및 lease 만료, 30일 메타데이터 정리. 검색/답변/전체 deadline 연결 | 신규 migration의 PG15 임시 schema 적용·동시 요청·격리 9/9 통과. 운영 DB에는 미적용 |
| 6 | CP-05/R0 지표 산술 준비 | 다섯 action+ERROR 분리, 질문 미제공률/차단 정확도와 후보 검증 지표 분리. 고정 분모·3회 짝비교 median·D18 산술 테스트 | runtime v2 결과 수집·W manifest 교차 검토·CP-00C 인수 전 CP-05 완료 아님 |
| 7 | CP-04 M2/M3, R1~R5 본구현 | 아직 전체 구현하지 않음 | 2~5의 이번 DB 인수 차단은 해소. 공통 CP-00C 합류·후속 접점은 남음. R 작업 자체를 W 담당으로 넘긴 것은 아님 |

## 구현 세부와 원래 계획 대조

- 임베딩 공급자 호출은 기존 `reg/embeddings.py::embed_texts`만 사용한다. 비동기 adapter는 공통 recorder를 감싸는 용도이며 새 provider 구현이 아니다. 배치 1회에 receipt 1개, 모델 내부 retry 0, 요청·응답 모델과 원형 usage를 보존한다. 응답 인덱스 중복/누락·차원 오류도 호출 비용은 남긴다.
- 입력 token의 실제 0과 누락 null을 구별한다. total token을 prompt token에 더하지 않는다. 추가 billable 필드의 포함 관계가 미확정이면 PARTIAL이다. 새 cache를 구현하거나 cache 재사용을 무료 지출로 가정하지 않았다.
- 채팅의 QUERY/ANSWER는 같은 서버 operation ID, 평가는 같은 run/case ID로 귀속한다. 기존 자유 생성 답변 정책/검색 기준을 새 의미 검증 완료로 포장하지 않는다.
- 읽기 원장 집계는 기존 답변 추정 금액과 독립 필드다. 둘을 더하지 않는다. STARTED/UNKNOWN/미가격 receipt가 있으면 total=null이며 known 부분합만 보존한다. 종료 run의 결과·metrics 동시 저장과 freeze 흐름을 유지한다.
- 운영 계산은 질문 수에 추가 사용자 턴을 별도로 반영한다. 등록 비용은 월 운영비에 섞지 않는다. Storage/추가자료/환율/요율 입력 누락은 통과가 아니다. 이 함수는 가정 계산기이며 관측된 고객 비용 리포트가 아니다.
- 유입 제한은 결정서 초기값 회원 20/분·매장 120/분, 동시 회원 2·매장 8을 사용한다. store 단위 DB transaction advisory lock 안에서 검사·lease 삽입을 함께 수행한다. 모델 동안 DB 연결을 반환하며 죽은 worker는 lease 만료로 회수한다. 외부 호출 후 회원 자격도 다시 확인한다.
- 전체 chat 5초 내에서 검색 1초·전체 모델 3초, 최종 저장 0.5초를 예약한다. 시간 예산을 단계마다 새 5초로 만들지 않는다. SDK 동기 임베딩의 transport 종료와 coroutine 취소는 동일하지 않으므로 응답을 관측하지 못한 취소는 UNKNOWN 비용으로 남긴다.
- pending occurrence는 question/member/message의 매장·session 소속을 SQL에서 확인한다. 앞서 남긴 정적 위반 1건이 해소됐다.
- 지표 함수는 완전한 정답 여부의 사람 판정 입력을 소비한다. action 일치율이 의미 정확도라는 주장은 하지 않는다. 미판정 차단은 분모에서 삭제하지 않고 precision=null 및 미판정 수로 보고한다.

## 검증과 현재 차단

최종 오프라인 검증: 354 tests / 73 subtests 통과, 기존 Starlette/AnyIO deprecation warning 1건. 변경 API 12개 매장 격리 AST 검사 위반 0건 및 diff 형식 검사를 확인했다. 새 보안 실제 DB 검증 스크립트 `api/scripts/verify_r_security.py`는 독립 schema에서 migration, 회원/매장 rate·동시 실행, lease 만료, 별도 연결의 우회 차단, pending 교차 매장 거절을 재현하도록 작성했다.

이번 실행에서는 Docker default/desktop-linux 엔진 파이프가 모두 없었다. Docker Desktop 시작도 시도했으나 엔진 준비를 확인하지 못했다. PostgreSQL 15 이미지 pull은 엔진 연결 단계에서 실패했다. 따라서 신규 보안 migration을 적용했다거나 새 실제 DB 인수가 통과했다고 보고하지 않는다. 이미 성공했던 PG17 원장 14/14는 이전 버전의 근거다.

후속에서 `verify_r_handoff.ps1`로 일회용 PG15 시작 → 원장/보안/임베딩·읽기 집계 실제 DB 검증 → 전체 회귀 → 컨테이너 제거를 완료했다. 전체 업무 schema의 채팅 저장/publication 종단 인수는 별도이며 운영 DB에는 migration을 적용하지 않았다.

## W가 있어야 완료할 수 있는 항목

- W ingest/extract/STT/Storage 비용과 R QUERY/ANSWER 원가의 전체 대조, source/card 배치 기여 링크 및 등록 report 인수.
- W 발행 서비스의 PrepareIndex 토큰/기한/content hash·준비 결과를 실제 원자 공개에 연결하는 접점. 현재 서비스는 prepared_id 소비 경로가 없으므로 R이 공개 포인터를 별도로 바꾸지 않는다.
- W snapshot의 규격 적용 범위/조건·예외 등 의미 메타데이터 계약 합의와 실제 producer 출력 검증. null을 공통 적용으로 바꾸지 않는다.
- M4 이관/backfill, OWNER_ANSWER의 W 지식화 완료, 실제 source truth·W snapshot 기반 J1/J2 통합과 승격.

M2/M3·R1~R5의 R 자체 구현은 W 작업으로 일괄 제외하지 않는다. 다만 위 실제 접점의 합의/공통 원가 선행과 현재 로컬 DB 인수 없이 뒤 단계를 완료 처리하지 않는다. 배포·유료 평가·커밋·푸시는 수행하지 않았다.
