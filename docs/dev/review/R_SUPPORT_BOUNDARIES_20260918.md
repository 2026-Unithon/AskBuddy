# R 지원 경계와 다음 구현 범위 — 2026-09-18

기준: `44a6a9d`에서 만든 `codex/r-semantic-support-boundaries`. 시작 시 존재한 ingest/release 미커밋 변경은 이 작업의 산출물이 아니다. 실자료·외부 모델 호출 없이 합성 입력으로 확인했다.

## 먼저 바로잡을 전제

사용자가 제공한 작업표는 결정론적 planner, chat v2, 신규 migration 5개, 매장별 질문 초안 40개가 존재하는 상태를 전제한다. 현재 체크아웃에는 해당 planner/chat v2 실행 경로가 없다. `AnswerPlan`, `QuestionContext`, snapshot 타입과 검증 접점은 있지만 실제 `/learn/chat`은 `retrieve_question` → `compose_grounded_answer` 경로다. 로컬 브랜치 목록에서도 별도 R 브랜치를 찾지 못했다. 원격 최신 상태는 조회하지 않았으며, 해당 구현의 부재를 저장소 전체 이력의 부재로 확대하지 않는다.

따라서 아래는 **현재 체크아웃**의 경계다. 이전 구현 기준의 1번 완료, 최신 migration 인수, 질문 40/37/0 현황을 재확인했다고 주장하지 않는다. 기준 R 커밋을 받은 뒤 같은 사례를 다시 실행해야 한다.

## 지원 / 미지원 / 검증 필요

지원은 해당 좁은 동작에 한정한다. 검색 hit 또는 원문 출력 가능은 질문에 충분한 답변이라는 뜻이 아니다.

| 항목 | 판정·지원 예제 | 차단해야 할 반례와 현재 결과 | 검증 방법 |
|---|---|---|---|
| 명시적 일반 질문 | 제한 지원: 질문 대상 낱말·vector 임계값을 만족한 승인 카드 검색 | `우유 가격 얼마?`에 보관 위치 카드가 hit: 충분성 미지원 | `test_r_semantic_boundaries.py` R-B01; 기존 `test_grounded_answer.py`의 대상 불일치 차단 |
| 자유 표현 일반 질문 | 검증 필요: 의미가 같아도 같은 낱말이 없으면 탈락 가능 | 동의 표현으로 정답이 누락되거나 공통 단어로 다른 속성이 통과 | 승인 snapshot별 동의 표현/무관 속성 짝을 사람 라벨로 평가; 현재 합성 테스트는 품질 증거 아님 |
| 제목 없는 서술형 RAW | 원문 출력 자체는 지원; 질문 적합성은 미지원 | 후보 첫 원문을 무조건 반환하는 `_fallback`; 승인 원문이어도 무관 질문에 답하면 오류 | 기존 원문 폴백 테스트 + `test_wr_answer_boundary.py::test_raw_approval_alone_is_not_question_suitability` |
| 수량·연결 | 새 숫자 차단 지원 | A 100ml/B 200ml를 A 200ml/B 100ml로 교환해도 통과 | R-B02와 unknown quantity 정상 차단 테스트 |
| 조건·예외 | 접점에서 판단 누락 차단 지원; 일반 적용성 판단 미지원 | `주말에만 재료 A 100ml`에서 `주말에만` 삭제해도 legacy 검증 통과 | R-B03; 기존 접점의 missing condition/exception 테스트 |
| 중첩 조건·수치 예외 | 미지원 | 요일 AND 수량 상한 OR 예외를 미확정 슬롯으로부터 추론하면 안 됨 | 후속 fixture에 경계값 전/일치/후, 미확정, 모순을 추가; 현재 의미 실행기 없음 |
| 후속 문맥 | 미지원: 현재 ChatAskRequest는 question만 수신 | 서로 다른 음료를 논의한 직원의 `그럼 따뜻한 건?`에 동일 문자열 키 생성 | R-B04; 실제 저장 병합은 DB 문맥 구현과 별도 검증 필요 |
| 의미 묶음 | 대소문자·공백 정규화만 지원 | `우유 어디?`와 `우유 보관 위치?`는 다른 키; 같은 후속 문장이 다른 대상을 가리켜도 같은 키 | 정상 문자열 테스트 + R-B04. 의미 동일성/차이를 각각 라벨링 |
| 승인·참조·버전 | 계약 접점에서 지원 | 다른 매장·오래된 판·미승인 참조·필수 dependency 누락 차단 | `test_wr_answer_boundary.py`, `test_contracts_cp02.py`; legacy와 계약 접점 연결 여부 별도 |

자동 검증의 `xfail(strict=True)` 네 개는 **열린 결함**이다. 통과 수에 포함하지 않는다. 수정되어 XPASS가 되면 테스트가 실패하므로 해당 사유·표를 갱신하고 xfail을 제거해야 한다. 제품 승인에서는 xfail을 포함해 결함 수 0을 요구한다.

## 2번 구현 범위

기존 결정론적 구현의 기준 커밋 확보가 우선이다. 없는 planner를 임의로 새로 만들거나 legacy 단어 검증을 결정론적 의미 planner라고 부르지 않는다.

1. 기준 planner를 유지한 별도 `OFF/SHADOW` 모델 제안 경로를 둔다. SHADOW는 사용자 답변·pending·사전·승인을 바꾸지 않는다. 동일 입력의 기존 결정과 제안을 함께 평가한다.
2. 입력은 서버가 인증한 현재 승인 후보, 원 질문, 소유권·TTL을 검증한 사용자 확정 슬롯이다. 모델 출력은 행동·후보 참조·슬롯 제안·불확실성으로 제한한다. 자유 생성 답변, 모델 발급 assessment, 임의 DB ID를 허용하지 않는다.
3. 서버는 schema, 후보 포함 여부, 매장/판/hash, 대상/속성/규격, 필수 dependency와 문맥을 재검사한다. 슬롯 제안만으로 사용자 확인 상태를 만들지 않는다. 미확정 조건은 명확화 또는 이관한다.
4. 일반 RAW와 중첩 조건의 의미 적합성은 참조 검사만으로 승인하지 않는다. 허용 문법 확대와 일반 의미 판단의 평가 결과를 분리한다. 제목 없는 RAW, 조건 누락, 숫자 연결, 자유 표현, 후속 문맥을 독립 분모로 둔다.
5. 의미 묶음 모델은 후보 관계만 제안한다. 확정 대상·속성·규격·조건이 다르거나 불확실하면 자동 병합하지 않는다. 요청 멱등키와 의미 중복키를 분리한다.
6. timeout/잘못된 JSON/후보 밖 참조/오래된 snapshot/문맥 소유권 실패를 합성 계약으로 검증한다. 모델 장애는 지식 없음과 구분하고 기존 안전 경로를 따른다. 사용량·지연·실패 비용도 기록한다.
7. 활성 채택은 검토 완료 사람 정답, 고정 snapshot, 기존/제안 짝비교·A/A·반복 평가 이후다. 잘못된 ANSWER, 과차단, 잘못된 병합을 별도 집계한다. 합성 계약 통과로 의미 품질 인수를 대신하지 않는다.

## 3~9번 후속 상태

| 순서 | 이번 확인 / 다음 의존성 |
|---|---|
| 3 사전·검색 확장 | 현재 retrieve는 vector+낱말 필터다. 실제 별칭/STT 검토 자료와 출처·승인·버전이 먼저다. 별도 query expansion 필요성이 입증되지 않아 기능을 추가하지 않았다. |
| 4 캐시·로그 | 현재 `retrieve_question`에 검색 결과 캐시는 없다. 설정의 lru_cache는 검색 캐시가 아니다. 일반 로그 전체의 원문 OFF·30일 정리·접근 통제는 미검증; lease 30일 삭제를 로그 보존 계약으로 간주하지 않는다. |
| 5 자동화 | 아래 로컬 검증을 추가했다. 공통 CI·필수 상태 검사·브라우저 자동화 연결은 W 조율 및 기준 R 구현 확보 후 진행한다. |
| 6 실자료 정답 | 실제 데이터는 읽거나 반출하지 않았다. 매장별 40개/37문구/검토 0개는 사용자 제공 현황이며 이번 재계수 결과가 아니다. 검토 자료의 위치와 기준 버전 확보 필요. |
| 7 DB | Docker 29.7.2 접근 확인. 기존 `verify_r_handoff.ps1`을 일회용 PostgreSQL에서 실행한다. 이 검사는 원장/보안/embedding 일부이며 표의 최신 migration 5개·v2 문맥·FAQ 인수를 대신하지 않는다. |
| 8 성능 | 승인 snapshot·검토 완료 정답 확보 전 미실행. |
| 9 공동 인수 | 실제 W producer/worker와 연결한 점주 1명·직원 2명 검증 미실행. |

## 재현

api 디렉터리에서 실행한다. 유료 API 및 실제 DB 없이 합성 검증한다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_r_semantic_boundaries.py tests/test_grounded_answer.py tests/test_wr_answer_boundary.py -q -p no:cacheprovider
```

결과: **24 passed, 4 xfailed, 24 subtests passed**. xfail 네 개가 위의 legacy 의미 결함을 재현했다.

추가 계약 검증: `tests/test_contracts.py tests/test_contracts_cp02.py` **95 passed**.

저장소 루트에서 기존 DB 검증을 실행했다.

```powershell
& .\api\scripts\verify_r_handoff.ps1 -Python 'C:\project\AskBuddy\api\.venv\Scripts\python.exe'
```

PostgreSQL 15.19: 답변 원장 14/14, R 보안 9/9, embedding 계측/집계 6/6, W embedding 인계 6/6, W score migration 4/4 — **39/39 통과**. 이 실행이 생성한 일회용 컨테이너 정리 완료. 모델 응답·오류는 fake로 주입했다. 전체 migration 재구축이나 운영 DB 검증은 아니다.
