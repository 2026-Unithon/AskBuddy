# R0 독립 검색 채널 수집 — 2026-09-16

## 구현과 계획 대조

R0 pooling의 다음 단위인 실제 DB 검색 수집을 구현했다. 기존 제품 검색 SQL을 `search_channels`로 분리하고 제품 `hybrid_search`는 같은 결과에 기존 RRF/최종 후보 제한을 적용한다. 평가 수집기는 융합 후 후보에서 순위를 역추정하지 않고 각 채널의 원래 순위·점수를 보존한다.

- `api/app/team/retrieval_collection.py::collect_retrieval_pool`: 격리 평가용 내부 함수. 호출자가 DB pool, trusted store_id, 질문, 사전 준비한 query_vector와 공급자/model/mode/reference, 기대 snapshot ID/revision/hash, oracle 참조, 표본 seed/개수/채널 한도를 전달한다.
- 같은 repeatable-read 트랜잭션에서 snapshot·사전·두 채널·현재 승인 색인 문서 목록을 읽는다. 제품 호출은 평가용 전체 문서 목록 조회를 실행하지 않는다.
- 기대 공개판과 다른 경우 실패한다. oracle을 새 판에 자동 이식하지 않는다.
- 현재 승인 취소·제외·버전 변경된 카드는 채널과 표본에서 제외한다. 제외된 oracle도 거절한다.
- 결과에 query vector hash, 사전 확장어, 정규화/lexical 버전, 소스 지문, 색인 revision, 채널 원점수·순위, 검토 pool 및 collection hash를 보존한다. 벡터의 실제 공급자 여부는 metadata만으로 증명하지 않는다.
- 평가 전용 내부 함수이며 새 공개 API나 운영 실행 CLI는 추가하지 않았다. 질문 임베딩의 호출·비용 기록은 호출자가 기존 계측 경로로 제공해야 한다.

전체 계획의 담당·승격 기준은 변경하지 않았다. R0 TODO는 사람 관련성 검토·정답 매핑·지표/oracle 분해가 남아 있어 완료로 표시하지 않는다.

## 검증

실행: `verify_r_handoff.ps1 -IncludeSchemaRebuild -IncludeUnitTests` (bundled Python, 기존 로컬 test-deps).

- 전체 API 단위 **546 tests / 116 subtests** 통과. 기존 의존성 deprecation 경고 1개.
- 일회용 PostgreSQL **17.11**, **26 migration** 재구축 통과. 종료 시 검증 DB/컨테이너 정리.
- 기존 원가·보안·W 임베딩·W score·문맥/stale 검사: 14+9+6+6+4+21.
- M2 **38**(이번 수집 반례 7 포함), reranker **13**, 답변 저장 **16**, v2 API **84**, 점주 전달 **21** 검사 통과. 반복 provider 확인을 포함한 총 232 PASS이며 독립 시나리오 개수는 아니다.
- 새 DB 확인: 독립 순위, cutoff 밖 표본, 미판정 유지, 공개판 불일치 거절, 제외 카드 표본 차단, 제외 oracle 거절, 타 매장 색인 접근 차단.
- 변경 모듈 3개 매장 격리 정적 검사 및 diff 공백 검사 통과.

실제 PostgreSQL/pgvector를 사용했지만 임베딩은 합성이다. 실자료 모델 품질·비용·지연 개선을 주장하지 않는다.

## 남은 범위

현재 표본 모집단은 **현재 승인된 색인 문서**다. 색인에 아예 빠진 승인 블록까지 포함하는 전수 정답 모집단이 아니다. 검색 재현율 분모를 확정하기 전에 승인 snapshot 블록과 색인 전체의 대응 검사 및 안정적 사실 의미 ID 매핑이 필요하다. 현재 코드는 recall 수치를 산출하지 않는다.

다음 R 단독 작업은 (1) 승인 블록/색인 모집단 대응 검사, (2) pool hash에 연결된 별도 사람 판정 계약과 수입, (3) 검토 범위를 명시하는 검색 지표와 oracle 분해다. 실제 매장 정답 판정과 W 발행/지식화 공동 인수는 별도다.
