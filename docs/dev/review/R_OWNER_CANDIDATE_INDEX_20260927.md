# R 점주 답변 후보 검색 이전 검증

2026-09-27, PR #25 병합 main `bbce36ad8b65074c4a11b7651af688eb25210c03`에서 만든 `codex/r-owner-candidate-index`의 로컬 구현·검증 기록이다. 공동 실행 계획의 R 선행 항목을 수행했다. 이 기록은 원격 통합·운영 배포·실자료 품질 인수를 뜻하지 않는다.

## 구현

- `app/reg/owner_candidates.py`: 같은 매장의 활성 snapshot과 준비 색인을 읽고 모델·설정·블록 전체 일치를 확인한다. repeatable-read transaction 안에서 현재 승인/검증 상태와 공개 버전 포인터가 일치하는 카드만 회수한다.
- 카드별 최고 블록 cosine 점수로 먼저 묶은 뒤 top-k를 적용한다. 한 카드의 여러 블록이 다른 카드 후보를 밀어내지 않는다. 제목·본문은 불변 `card_versions` 승인판 전체를 반환하며 미승인 초안은 섞이지 않는다.
- `knowledge_loop.find_owner_answer_candidates`: 질문+답변 query 임베딩과 비용 귀속을 유지하고, 기존 `id/title/content/score/version_id/category_id/assignment_type/category_name` 반환 필드를 보존한다. `match_cards/card_embeddings`를 더 이상 읽지 않는다.
- 색인 없음·불일치·조회 실패는 재시도 가능한 오류로 전달한다. 성공한 빈 검색과 구분하여 장애 때문에 NEW 제안을 만드는 일을 막는다. 기존 동일 본문·관계 판단·수동 배정 및 fallback 분기는 유지한다.
- W `owner_answer_worker` 호출부만 `ShortSession`으로 바꾸어 임베딩·모델·usage sink 실행 중 DB 연결을 반환한다. W의 옛 색인 호환 쓰기는 아직 유지한다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| 전체 API pytest | 1,133 passed, 4 xfailed, 131 subtests passed |
| Docker 격리 DB schema rebuild | migration 33개 및 전체 handoff runner 통과 |
| 신규 owner candidate DB 검증 | 23 checks |
| 기존 색인 재사용 / W 공개 / 점주 인용 DB 검증 | 11 / 66 / 8 checks |
| schema·공유 fixture 최신 검사 | 15 / 3개 통과 |
| reg·learn·cards 매장 격리 정적 검사 | 위반 0개 |

신규 DB 검증은 레거시 벡터 0개 상태에서 실제 W 공개 결과를 사용했다. 다중 블록의 카드별 top-k, cosine 0.8, 수동 카테고리, 긴 승인 원문 보존, 초안·제외 카드·snapshot 밖 포인터 차단, 동일 답변 IDENTICAL, fallback SUPPLEMENT, 다른 매장·모델 불일치를 확인했다. 실제 W worker는 연결 1개짜리 풀에서 임베딩 중 연결 재취득이 가능하고 최종 LINKED까지 완료했다. 색인 장애의 worker 재시도 상태는 단위 테스트로 확인했다.

실행: `api/scripts/verify_r_handoff.ps1 -Python api/.venv/Scripts/python.exe -IncludeSchemaRebuild` 및 API 전체 pytest. pytest에는 작업 폴더 아래 별도 `--basetemp`와 `-p no:cacheprovider`를 사용했다. 로컬 DB 로그는 gitignored `api/tmp/r-owner-candidate-index-final.log`에 있다. 임시 Docker DB만 사용했으며 종료 후 컨테이너를 정리했다.

## W 인계와 남은 경계

1. 이 브랜치 검토·통합 후 W가 `approve_card`·`approve_owner_proposal`의 옛 `prepare_embedding`/`embed_card` 호환 쓰기를 제거한다. 남은 레거시 호출자를 확인하고 승인→후보 검색→관계 판단을 재검증한다.
2. 활성 색인이 없는 매장은 `INDEX_UNAVAILABLE`이다. worker 활성화 전에 대상 매장의 공개 snapshot·색인을 준비한다. 첫 매장/마지막 카드 제외의 빈 공개판 처리 계약은 공동 결정 대상으로 남는다.
3. 점수는 cosine 의미를 유지하지만, 과거 카드 전체 벡터에서 현재 카드의 최고 블록 점수로 분포가 달라진다. 합성 임계값 회귀 통과가 실자료 품질·임계값 교정 완료를 뜻하지 않는다. 사람 정답·유료 평가는 기존 대기 조건을 따른다.
4. W 직접 공개 레거시 경로, 편집 시 점주 답변 출처 보존, 제외·복원 원자성 및 과거 누락 복구는 별도 후속이다.

이번 브랜치에 schema/migration 추가는 없다. 운영 플래그·운영 DB 변경과 유료 provider 호출은 하지 않았다. 프론트 변경이 없어 브라우저 검사는 이번에 재실행하지 않았고, 원격 CI 결과는 이 로컬 검증에 포함하지 않는다.

근거: [실행 순서](../plan/R_W_NEXT_AFTER_INDEX_REUSE_20260927.md), [공동 절차](../plan/WR_JOINT_WORKFLOW.md), [W 인계](../plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md).
