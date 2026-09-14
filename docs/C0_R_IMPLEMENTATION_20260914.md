# C0 R 구현 기록

기준: `C0_DECISIONS_AND_PLAN.md` §2·8. 이번 변경의 주 편집자는 R이다.
CP-00A 공통 usage 원장/MC0와 W의 보강 snapshot·RAW/provenance가 현재 저장소에 없으므로,
계획이 선행 작업과 병행하도록 허용한 CP-01·R 인증 및 기존 읽기 계측 결함을 구현했다.
**R 전체나 C0 전체 완료가 아니다.** W 영역의 대체 원장·임의 DB 계약을 만들지 않았다.

후속 R 자체 결함 수정까지 반영했다. 개발 토큰 exp, 질문별 dependency 선택, 조건·예외 미지원 거절,
Decimal 합계/보고서 정밀도 보존, 답변 미호출 상태, CLI/Markdown 누락 표시의 상세 근거는
[엄밀 검토의 수정 결과](C0_R_REVIEW_20260914.md#r-자체-수정-결과)를 따른다.

## R 담당 범위와 상태

| 계획 항목 | R 책임 | 이번 결과 / 남은 선행 |
|---|---|---|
| CP-00A | 공통 receipt 읽기 소비 검토 | W UsageContext/receipt/rate/MC0 산출물 미존재, 검토 대기 |
| CP-00B | embed/answer/runner/metrics 계측 | answer 파싱 실패 시 usage 보존, 부분 토큰·단가 누락/0 구별, Decimal 계산, 부분합/전체 분리 수정. durable receipt·임베딩·시도별 계측은 CP-00A 대기 |
| CP-00C | 운영 report·질문 시나리오 | CP-00A/B와 Storage inventory·rate manifest 대기. 현 평가 answer 비용을 전체 운영 원가로 사용하지 않음 |
| CP-01 | action 배타성·참조 검증 | R shape·typed 참조 검증과 합성 회귀 테스트 구현. W RAW/규격 적용 범위·provenance 계약 이후 확장 필요 |
| R 인증 병행 | JWT·현재 membership·검색 매장 격리 | `/reg` JWT 필수, 현재 회원/역할 확인, 요청 slug는 JWT 매장 안에서 대조, 타 매장 404, 공개 version 본문만 목록 표시 |
| CP-02 | chat/event/error DTO·schema | R AnswerPlan schema/fixture만 최초 동결 전 export. 전체 CP-02는 CP-00C·W CP-01 선행 필요 |
| CP-03 | 소비 fixture·fake index/outbox | typed 참조 unit fixture만 구현. 공동 snapshot fixture·5 action/ERROR 종단 검증은 CP-02 대기 |
| CP-04 | M2/M3·DB 접점·경합 | W M0/M1 및 동결 publication 계약 대기. migration/원자 저장 미구현 |
| CP-05 | runner/metrics D18/D21 | 기존 nearest-rank p95 오류 수정. 품질 manifest·승격 통합은 CP-03·CP-00C 대기 |
| R-A/B/C | snapshot 소비·문맥/hybrid/충분성·답변/인용/점주 루프 | 위 CP 선행 후 진행. 기존 자유 생성 경로를 v2 완료로 간주하지 않음 |
| J1~J3 | 종단 평가·E2E·알림·복구/운영 인수 | 양쪽 C와 실제 관측, 격리 DB 및 별도 배포 권한 필요 |

## 구현 경계

- `AnswerPlan`: 양의 bigint ID, 0 이상 revision을 decimal string으로 검증한다. 최초 동결 전 `answer_plan/v1` 보강이며 기존 runtime은 해당 DTO를 사용하지 않는다. 기존 Python int revision fixture는 string으로 변경했다. `common.py`의 W ID 타입과 snapshot int revision은 미변경이며 동결 시 통일해야 한다.
- JSON schema 변경: revision `integer → string`, context `string → uuid`, R ID는 선행 0 금지·19자리 제한. 실제 bigint 최댓값, action 간 배타성, 중복 등은 Pydantic 실행 검증도 필요하다. JSON schema만으로 모든 의미 검증이 끝났다고 주장하지 않는다.
- R DTO는 frozen 및 tuple이며 중복 사실/블록과 빈 선택지를 거절한다. citation_count는 사실 개수가 아닌 블록 인용 개수다.
- `validate_answer_plan`: trusted store, snapshot/revision, 카드/버전/블록/사실 소속, 중복/orphan/순환, 승인 전체 블록 선택, 확정 대상·속성·규격, 단위, 선행 집합과 순서를 검증한다. HOT/ICE 비교는 둘을 확정한 요청에만 허용한다.
- 현 snapshot의 RAW는 fact-only 구조라 승인 RAW 증명이 불가능하므로 `UNSUPPORTED_SCHEMA`로 거절한다. 조건·예외가 있는 선택도 적용성을 확인할 계약이 없으므로 같은 오류로 거절한다. 미확정 규격·단위를 임의 추정하지 않는다. entity 간 dependency·조건 적용성·예외의 의미적 적합성은 W의 후속 계약과 R 충분성 검증을 필요로 한다.
- 위 validator는 DB 저장도, renderer도 아니다. context UUID의 소유권/TTL·현재 공개 CAS·hash 검증·메시지 저장은 미연결이다. 제품 경로에 연결하지 않았으므로 TOCTOU 해결이나 v2 답변 정확성 완료로 해석하지 않는다.
- `/reg` 응답 형식은 유지하지만 이제 인증이 필수다. 요청 매장은 권한 근거가 아니다. `CurrentStoreId`를 쓰는 기존 API도 매 요청 DB 회원/역할을 확인하며 삭제·역할 변경된 JWT는 403이다. `exp` 없는 JWT는 401이다.
- answer 모델 실패 로그에서 예외 본문과 unsupported 원문 단어를 제거했다. 기존 v1 원문 fallback 정책은 유지하며 v2의 ERROR 처리 구현으로 간주하지 않는다.
- `cost_usd_total`·token total은 하나라도 누락되면 null이다. `*_known_total`과 관측 건수를 함께 제공한다. 답변 미호출이 확인된 경우만 0이다. COMPLETE는 **평가 answer 비용 필드** 관측 완전성을 뜻하며 임베딩/Storage/재시도까지 포함한 D21 완전성이 아니다. 보고서에 ANSWER_MODEL_ONLY/ESTIMATED/전체 원가 UNKNOWN을 표시한다. 실제 요율은 사용하지 않았다.

## 검증

- 전체 API pytest: 후속 수정 포함 **179 passed, 30 subtests passed**, Starlette/AnyIO deprecation warning 1건. 유료 모델 호출 없이 fake provider·가상 요율을 사용했다.
- JWT/FastAPI 테스트: 무인증·만료/exp 누락, 부정확 ID, 회원 삭제/역할 변경, 두 매장 목록 분리, 타 매장 조회 404, 검색 호출 전 매장 거절, 422.
- 순수 계약 테스트: 5 action·거절 fixture 왕복과 schema 일치, bigint 경계/불변성/중복, 교차 store·stale·허위 참조, RAW 거절, dependency/규격/단위.
- usage 테스트: 응답 JSON parsing 실패 비용 메타데이터 보존, partial/0, 누락·음수·비정상 단가, known subtotal, p95 100개 표본에서 정확히 95번째.
- `store-isolation-check`: 변경한 application 파일 7개에서 위반 0건.
- 기존 C0 감사: PASS 4 / GAP 15 / ERROR 0. W 공통 타입의 미구현을 숨기지 않으며 shape-only 임의 참조 probe도 여전히 GAP로 남는다. R 별도 validator 거절은 신규 테스트로 입증한다.
- 로컬 Docker 엔진이 실행되지 않아 실제 PostgreSQL/매장 격리·경합 시험은 미실행이다. API 테스트의 DB는 fake다. 운영 DB·배포·실제 API 원가·p95·UI 검증은 하지 않았다.

재현: `api`의 requirements와 pytest가 설치된 Python에서 `python -B -m pytest tests -q`.
이번 환경에서는 bundled Python과 Git 제외 `api/tmp/test-deps`에 설치한 패키지를 사용했고,
pytest 자동 외부 plugin 로딩을 껐다. schema 재생성은 `python -B scripts/export_r_answer_contract.py`다.

W 인계 요청: UsageContext·durable receipt API/실제 시도 계약과 MC0, 동결 snapshot/typed-RAW union·규격 적용 범위·provenance·renderer, M0/M1 및 publication 잠금/CAS 접점을 제공하면 CP-00B/C → CP-02~05 순서로 연결한다. 이 기록은 독립 W 검토 승인이 아니다.
