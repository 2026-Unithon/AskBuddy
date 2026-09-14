# C0 W/R 답변 검증 접점 인수 기록

작성일: 2026-09-14. 기준: W/R 병합 `6dcf112` 이후 작업 트리.
범위: 사용자가 요청한 다음 작업 1번, 답변 검증 접점 통합. 전체 C0·실제 R3·DB 종단 인수를 완료한 기록은 아니다.

## 구현 계획과 결과

1. 공통 승인 참조 검사를 단일 함수로 모은다 → `app/contracts/validate.py::validate_answer_references` 구현. 기존 W `validate_answer_plan`은 호환 wrapper로 유지한다.
2. R은 공통 검사 결과에 질문 적합성을 검사한다 → `app/learn/answer_validation.py::validate_answer_for_question` 구현. 기존 R 이름도 호환 wrapper로 유지한다.
3. 기존 W snapshot/manifest의 기대값을 바꾸지 않고 합성 R3 입력을 별도 정의한다 → `tests/fixtures/contracts/v1/r_suitability.json`과 `tests/test_wr_answer_boundary.py` 추가.
4. 승인 참조 → R 질문 적합성 → 공통 fake renderer를 연결하고 반례·전체 회귀를 검증한다 → 아래 검증 통과.

## 책임과 신뢰 경계

| 계층 | 책임 | 이 계층이 완료하지 않는 것 |
|---|---|---|
| 공통 참조 | shape 재검사, store/snapshot/revision, card/version/block/fact/raw 소속, 원자적 사실 부분 선택, 중복, 선행 closure·순서, 대상 일치 | 질문 의미 적합성, DB 현재 승인·회원 권한 |
| R 질문 적합성 | 확정 entity/predicate/variant, 목표 사실과 선행 사실만 선택, 조건·예외 판정의 누락, RAW 판정의 결속 검사 | 실제 R3 의미 판정 생성, action 결정, context 소유권, pending 저장 |
| 서버 렌더러 | 선택된 승인 사실과 조건·예외 및 RAW 원문 출력 | 검색 품질·의미 정확성의 독립 증명 |
| 최종 저장 | 현재 권한·공개 판 재검사와 CAS/원자 저장 | 이번 접점 작업에서 구현하지 않음 |

`SuitabilityAssessment`는 신뢰하는 서버 R3 또는 별도 검토 절차가 생성할 내부 입력이다. HTTP/모델 출력 DTO로 공개하지 않는다. 모델의 선택을 그대로 복사해 승인하는 adapter를 연결해서는 안 된다. store·snapshot ID/revision/hash·원문 질문 hash·확정 대상/속성/규격에 결속한다. 조건·예외 목록 일치는 판정 누락 검사이며 문자열 일치로 의미 적합성을 알아냈다는 뜻이 아니다.

이번 fixture는 별도로 명시한 **합성 판정 입력**이다. 실제 사람 평가 완료나 실제 R3 추론 정확성의 증거가 아니다. 입력은 기존 W 질문·원문에 맞춰 작성했으며 manifest의 기대 출력을 바꿔 통과시키지 않았다. 운영 R3 생성기는 이후 R 작업이다.

공통 함수는 서버 manifest 로더가 hash/출처를 확인한 snapshot을 받는다. R assessment 경로는 실제 hash도 재검사한다. 이 함수에 클라이언트가 공급한 snapshot이나 임의 assessment를 직접 연결해서는 안 된다. 회원·session 권한과 DB의 현재 공개 여부는 별도 저장 경계 책임이다.

## 전체 계획 대조와 결정

| 기존 불일치 | 계획 근거 | 이번 결정 |
|---|---|---|
| R은 typed 블록 전체만 허용해 혼합 규격 일부 선택을 거절 | 결정서 §5.2는 필수 closure를 보존하는 부분 선택 허용 | fact를 원자 단위로 선택하고 필수 선행 사실·순서를 검사 |
| 공통 기존 테스트는 선행 사실이 뒤에 있어도 허용 | §5.2 dependency closure 및 승인 순서 보존 | 선행 사실이 먼저 오도록 테스트 기대를 바로잡고 역전 반례 추가 |
| R은 승인 RAW도 무조건 거절 | §5.2 충분성이 별도 확인된 RAW 허용 | 질문에 결속된 서버 판정이 있을 때 허용; 승인만으로는 거절 |
| 응답 DTO가 RAW 앞뒤 공백·끝 줄바꿈 제거 | 승인 원문 보존 원칙 | `ChatResponse.message`에 기존 `RawText` 타입 사용; JSON schema 변경 없음 |
| W snapshot의 null 규격을 업무상 비적용과 구별할 수 없음 | null은 미확정이며 범용 근거로 추정하지 않음 | null만으로 허용하지 않음. 내부 판정의 명시적 NOT_APPLICABLE만 허용 |

W snapshot에는 아직 완전한 규격 적용 범위/질문 적합성 메타데이터가 없다. 이를 임의 predicate나 범용 규격으로 채우지 않았다. 내부 판정 입력은 이 공백을 숨기는 공개 계약 변경이 아니다. 버전이 있는 W 메타데이터 확장은 W/R 공동 합의가 필요하다. 대상 간 선행 관계와 사실/원문이 혼재된 RAW도 명확한 계약 전까지 보수적으로 거절한다.

## 검증 결과

- API 전체: `325 passed`, `58 subtests passed`; 기존 Starlette/AnyIO deprecation warning 1건.
- W F02~F09: 기존 기대 action·사실/RAW 인용·금지 인용·조건/예외·순서 유지. F09는 공백을 포함한 원문 전체 일치.
- 추가 비교 사례: HOT/ICE 모두 필요, 다른 크기 혼입 거절.
- 반례: 판정 없는 RAW/미확정 규격, 판정의 다른 질문·매장·snapshot 재사용, 조건/예외 판정 누락, 선행 누락/역전, 교차 대상, 모호한 RAW, 변조 hash·오래된 revision 거절.
- JSON schema export 15개 및 기존 W fixture 생성물 3개 최신 상태 확인.
- 변경한 API 파일 4개 매장 격리 AST 검사 위반 0건, `git diff --check` 통과.
- 실제 DB/API 권한·publication 경합, 실제 모델 호출, action 결정 및 전체 F01~F35의 R 의미 판정은 이번 인수에 포함하지 않는다. 합성 연결 테스트를 실제 J1 품질 검증으로 간주하지 않는다.

## 병렬 착수 판정

이 접점을 기준으로 **분리된 파일에서 W/R 개발을 병렬 진행할 수 있다.** 실제 의미 판정과 원가 계측을 완료했다는 뜻은 아니다. 우선 CP-00B에서 W extract/STT/storage와 R embed/answer/metrics 계측을 병렬 진행하고 CP-00C 집계 인수로 연결한다. 새 질문 경계는 R 구현의 합성 입력 인터페이스로 사용한다.

결정서 §8의 CP-00A→B→C 선행은 유지한다. W pull에 CP-02~04 산출물이 먼저 포함된 사실을 선행 인수 완료로 해석하지 않는다. CP-00B/C 미완료 상태에서 W-A/R-A 전체 착수·CP-05 완료·운영 전환이 자동 허용된다는 결론은 원래 계획과 다르다. 이후 단계는 해당 선행 인수 근거를 확인해 진행한다.

공유 계약 수정은 양쪽 동기화가 필요하다. DB 연결과 실제 W 출력 기반 J1 검증은 다시 합쳐 수행한다.
