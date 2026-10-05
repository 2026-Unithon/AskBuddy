# R 우선순위 구현·검증 — 2026-10-05

사용자가 요청한 R 일곱 항목을 기준으로 기록한다. W에 독립적인 구현과 검증을 병합 대상으로 정리했다. main 병합 후 기존 CI·API 자동 배포 흐름을 따르며, 기능·정리 플래그는 활성화하지 않는다. W3 실제 조립 출력과 실자료 품질 인수까지 끝난 것으로 간주하지 않는다.

## 구현 범위

| 순서 | 결과 | 남은 인수 |
|---|---|---|
| 1. W3 출처 계약 | `FactProvenance`가 파일 또는 점주 답변 출처를 받는다. 파일은 `source_id + occurrence_id`, 점주 답변은 `owner_answer_id`이며 가짜 파일 occurrence를 만들지 않는다. 사실 인용·저장·상세·과거 조회와 혼합 출처를 지원한다. | W3 생산자가 이 계약으로 실제 출력 생성. 점주 답변 텍스트 파일 생성은 W 담당. |
| 2. 옛 공개 경로 | v1 `answer_pending`의 NEW 자동 공개를 `approve_owner_proposal` 조정자로 연결했다. 카드·snapshot·색인과 제안 완료가 같은 공개 transaction을 통과한다. 기존 v1 검수 제안도 승인할 수 있다. | 운영의 과거 PUBLISHED지만 색인 누락인 제안은 bootstrap 점검 대상. 기존 완료 상태를 임의 재작성하지 않았다. |
| 3. 옛 검색 경로 | `/reg/retrieve`와 이를 호출하는 평가 러너가 현재 공개 블록 색인을 사용한다. 카드별 최고 cosine 점수, 승인 버전 본문, 카테고리, 기존 앵커 게이트를 유지한다. preflight의 옛 테이블·함수 필수 조건을 제거했다. | `card_embeddings`·`match_cards`의 실제 제거는 W와 별도 결정. 옛 공개 helper는 제품 호출부에서 제거했으며 과거 이관 재현 스크립트가 아직 사용한다. |
| 4. 신규·빈 공개판 | 승인 카드 0개는 빈 후보로 처리하며 worker가 첫 답변을 처리한다. 첫 v2 질문은 실제 빈 snapshot·색인을 멱등 생성하고 pending을 저장한다. 마지막 카드 제외도 빈 snapshot으로 공개한다. | 승인 카드는 있으나 색인이 없거나 모델/문서 구성이 틀린 상태는 계속 장애로 처리한다. |
| 5. 통합 회귀 | 기존 W RAW 공개, REVIEW 승인·알림, 재사용, 후보 검색, 제외·복원, 공개 실패 rollback을 실제 격리 DB에서 검사했다. W 사실 원장 서비스가 생성한 파일 없는 사실로 R 저장·검색·인용·재조회도 검사했다. | **W2 원장 → 합성 W3 DTO → 실제 R** 검사다. 현재 W 생산기는 RAW이므로 W3 실제 조립·검수 출력의 업로드→직원 재질문 인수는 남아 있다. |
| 6. 벡터 정리 | 시간별 진단 정리 루프에 별도 정리 함수를 연결했다. 문서 행만 정리하고 준비 기록·snapshot·출처·과거 인용은 보존한다. | 기본 비활성. 보관 N·M 합의 전 실행하지 않는다. |
| 7. 질문 품질 | 기존 평가 러너의 검색 이전 및 합성 행동·인용 회귀 완료. E0 기준선 37개 사례/16개 질문을 재기록했으며 실행 오류 0개다. | 실제 W3 승인판·검토된 정답·평가 매장·유료 호출 예산으로 정답/재질문/이관, 비용, 지연을 평가해야 한다. 합성 회귀를 실제 정확도·p95·원가로 보고하지 않는다. |

## 출처·삭제 계약

- 기존 파일 출처의 canonical hash는 유지했다. 새 `owner_answer_id`는 해당 출처에서만 hash에 들어간다. schema export와 합성 fixture를 함께 갱신했다.
- 사실에 여러 근거가 있으면 각각 인용한다. 삭제된 파일은 인용 끊김으로 표시하고 보존된 점주 원문은 계속 표시한다.
- 새 FK는 `(store_id, fact_revision_id, owner_answer_id)`가 W의 `fact_owner_answer_links`에 실제 존재해야 한다. 기존 RAW 인용 FK·블록 사실 참조 FK·출처 단일성 제약도 유지한다.
- R 점주 답변은 원문 불변 trigger로 삭제·변경이 차단된다. W의 `fact_revision_meta`와 `fact_owner_answer_links`도 삭제 RESTRICT다. 진단·벡터 정리는 점주 답변을 삭제하지 않는다.
- v1은 이미 원문 전달을 기록했으므로 승인 완료 시 공개 증거를 검증하고 종료한다. 없는 v2 revision·REVIEW 원장을 만들어내지 않는다. v2 완료 검증은 그대로 유지한다.

## 빈 상태와 장애

빈 첫 공개판은 가짜 snapshot ID를 응답하지 않고 기존 공개 조정자를 통해 저장한다. 카드 0개는 임베딩 호출이 필요 없다. 공개 준비와 최종 잠금에서 초기 상태를 다시 확인하므로 동시 승인 내용을 빈 공개판으로 덮지 않는다. 잘못된 정책 확인 receipt는 초기 공개판 생성보다 먼저 거절된다.

카드가 있으나 출처 오류로 모두 manifest에서 빠진 경우는 `EMPTY_MANIFEST` 오류를 유지한다. 이를 신규 매장의 정상 빈 상태로 바꾸지 않는다. 승인된 카드가 있는데 활성 색인이 없으면 `INDEX_UNAVAILABLE`을 유지한다. JSON·schema·hash가 손상된 공개판도 빈 지식으로 답하지 않고 재시도 가능한 503 `INDEX_UNAVAILABLE`로 처리한다.

제외·복원 라우트의 기존 best-effort 재발행 구조 자체는 유지했다. 성공한 제외·복원의 빈 판/검색 복귀와 승인 준비 실패의 rollback은 검증했다. 상태 변경과 재발행 전체를 원자적으로 묶는 W/R 설계 변경은 이번 완료 항목으로 세지 않는다.

## 벡터 정리

- `R_INDEX_GC_ENABLED=false` 기본값.
- `R_INDEX_GC_KEEP_PREVIOUS`, `R_INDEX_GC_MIN_AGE_DAYS` 기본값 없음. 켜더라도 둘 중 하나가 없으면 삭제하지 않고 설정 오류를 기록한다.
- 현재 활성 준비본, `PREPARING`, 만료 전 `PREPARED`, 직전 N개 공개 준비본을 보호한다.
- 시간 기준은 생성·만료·사용 종료 시점 중 가장 늦은 시각이다. 오래전에 만들었어도 방금 교체한 색인은 M일 보호한다. 기존 과거 준비본에도 migration 시점부터 유예를 준다.
- 공개판→준비본 순서로 잠근 뒤 삭제 시 trigger가 조건을 다시 검사한다. 일반 직접 삭제와 수정은 계속 차단하며 정리된 색인의 재활성화도 차단한다.
- 테스트의 N=2/M=30은 합성 검증 입력일 뿐 운영 정책 합의값이 아니다.

## 검증

- Python 전체: **1,563 passed, 4 xfailed, 131 subtests passed**. 기존 Starlette deprecation 경고 1개.
- 격리 PostgreSQL **17.11**: 전체 **41개 migration** 재구축 및 `verify_r_schema_rebuild.py` 전체 통과. 출력의 PASS 719행은 반복 점검과 migration 41개를 포함하며 독립 사례 수를 뜻하지 않는다.
- 실제 DB 추가 검증: `verify_r_index_retention.py`, `verify_r_w3_consumer.py`, `verify_r_legacy_publication.py`.
- E0 합성 기준선: 37 cases, 16 questions, error_count=0, 유료 모델 호출 0. 검색·실제 의미 정확도 평가는 아니다.
- `export_contract_schemas.py`, `build_contract_fixtures.py` 갱신 및 `git diff --check` 확인.

실행 환경의 기존 DB나 `.env`를 수정하지 않았다. 로컬 보유 pgvector 이미지로 만든 일회용 컨테이너와 UUID DB를 사용했다. 합성 임베딩/의미 입력만 대체하고 DB 제약·공개 조정·R 저장은 실제 코드를 실행했다.

## 배포·다음 인수

1. `20261005100000_r_fact_owner_citations.sql`, `20261005110000_r_index_retention.sql`을 API보다 먼저 적용한다. 이번 작업에서 운영 DB에는 적용하지 않았다.
2. W가 출처 계약과 빈 manifest 계약을 소비하고 실제 W3 snapshot을 생산한다. 원장 fact/revision ID를 사용하며 파일 없는 답변에 가짜 occurrence를 만들지 않는다.
3. 같은 매장에서 업로드→검수·승인→직원 질문→점주 답변→검수 승인→재질문→제외·복원→실패 복구를 확인한다. 조건·예외·규격과 인용 원문도 대조한다.
4. 검토된 dev 질문과 명시한 평가 예산으로 기존 평가 도구를 실행한다. holdout은 열지 않았다.
5. N/M을 합의한 뒤에만 벡터 정리를 활성화한다. 기존 W worker·RAW 공개·R v2 플래그도 자동으로 켜지 않았다.
