# 임베딩 재사용 이후 R/W 실행 순서

기준: PR #24의 W 인계 §4~8, 공동 작업 절차 J-C01~05, R REVIEW·인용·재사용 구현 및 검증. 구현 완료와 운영 인수를 구분한다.

## 1. R이 먼저 진행할 작업

`knowledge_loop.find_owner_answer_candidates`는 아직 `match_cards → card_embeddings`를 읽는다. 질문+점주 답변의 query 임베딩은 유지하고, 후보 조회를 새 활성 공개 색인으로 옮긴다.

- 같은 매장의 현재 공개 snapshot·카드 버전만 후보로 사용한다.
- 블록 검색 결과를 카드 단위로 묶고, W가 사용하는 `id/title/content/score/version_id/category_id/assignment_type/category_name` 반환 의미를 보존한다.
- 검색 점수 변경에 따른 기존 관계 판단·자동 공개 조건을 회귀 검증한다. 색인 없음/실패를 단순히 “후보 없음 → NEW”로 숨기지 않는다.
- 외부 임베딩 동안 DB 연결을 점유하지 않는 호출 구조를 유지한다.
- W 파일도 호출하므로 편집 시작 전에 `knowledge_loop.py` 주 편집자를 R로 맞추고, 함수 인터페이스를 바꾸면 W worker 호출부와 함께 검토한다.

이 단계는 전체 미확정 계약의 결론을 모두 기다릴 필요는 없다. 현재 공개 snapshot 계약으로 구현·합성 검증할 수 있다. W의 호환 쓰기는 유지한 채 이전을 먼저 끝낸다.

## 2. R 완료 후 W 작업

R이 후보 검색 이전과 회귀 검증을 완료하면 W가 `approve_card`와 `approve_owner_proposal`의 옛 `prepare_embedding`/`embed_card` 호환 쓰기를 제거한다. 그 전에 제거하면 점주 답변 후보 조회가 누락되거나 낡은 상태를 읽을 수 있다.

R의 A 방식 재사용은 새 공개 색인에만 적용된다. 이 W 정리를 끝내야 승인마다 추가되던 옛 색인 임베딩 1회도 사라진다. `publish_new_proposal`/`publish_existing_proposal`은 남은 레거시 호출자를 확인한 뒤 제거해야 한다.

## 3. 병행 가능한 W 작업

- `/ingest/cards/*`의 직접 공개 경로를 정리하거나 새 승인 경로로 위임한다.
- 점주 답변 판을 편집할 때 `owner_answer_id`가 사라지는 출처 문제를 해결한다. 혼합 원문을 어떻게 표시할지는 R 인용 의미와 함께 합의한다.
- 이미 PUBLISHED이지만 R 완료 원장이 없는 과거 제안, v2 revision/REVIEW 원장이 없는 레거시 제안의 이관 방식을 R과 정한다. 현재 fast path 재요청은 과거 누락 복구가 아니다.

## 4. 먼저 공동 결정할 계약

| 항목 | 협업 내용 | 막히는 범위 |
|---|---|---|
| 마지막 카드 제외 / 빈 manifest | W의 EMPTY_MANIFEST와 R의 최소 1개 준비 계약 조정, 빈 공개판·검색·FAQ 의미 | PUB-07 및 빈 공개판 완료 처리 |
| 제외·복원 원자성 | 현재 W best-effort 재발행을 유지할지, 상태·snapshot·색인을 한 transaction으로 바꿀지 | 공동 목표의 원자 공개 완료 판정 |
| 카드별 CAS 매핑 | W가 자체 CAS 중이며 R에는 빈 expected_card_revisions를 전달. DTO 변경은 선택 사항 | 후보 조회 이전의 선행 조건은 아님 |
| 참조·편집·레거시 복구 | W가 출처/제안 연결 생산, R이 현재판·revision·인용 검증 | 안전한 운영 전환 및 과거 누락 복구 |

공통 DTO/schema/migration 파일은 주 편집자 한 명을 정한다. 이미 구현한 A 방식 재사용 자체에는 추가 W 계약 변경이 필요 없다.

## 5. 배포·인수 순서

1. migration `20260927140000_r_owner_answer_citations.sql` 적용.
2. R API·근거 UI 배포. 새 API는 파일 인용에서도 새 nullable 컬럼을 사용하므로 migration이 먼저다.
3. W/R 합동으로 REVIEW 승인·원문 출처·직원 재질문·알림 및 실패 rollback 확인.
4. 환경 담당자가 `W_OWNER_ANSWER_RAW_PUBLISH`, `W_OWNER_ANSWER_WORKER_ENABLED` 활성화 범위·순서를 확인한다. 코드 merge가 운영 플래그 변경을 의미하지 않는다.

실자료 정답 검토·유료 평가 예산·운영 로그/접근/보존 증거는 공동 절차 §8의 별도 인수 항목으로 남는다. 합성 검증 통과로 완료 처리하지 않는다.

근거: [W 인계](W_TO_R_PUBLICATION_HANDOFF_20260927.md), [공동 절차](WR_JOINT_WORKFLOW.md), [R 인용 통합 검증](../review/R_OWNER_CITATION_INTEGRATION_20260927.md), [R 재사용 검증](../review/R_INDEX_REUSE_20260927.md).
