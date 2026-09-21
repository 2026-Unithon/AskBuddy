# R 공유 전 통합 검증 — 2026-09-21

R `455b06d`에 원격 main `db40813`을 통합한 `2c72aba`에서 실행했다. 충돌 없이 통합됐으며 새 W 추출/PDF 변경은 main 이력으로 보존했다. 이후 변경은 공유 문서뿐이다.

- 전체 API 단위: **913 passed, 4 xfailed, 119 subtests passed**. 기존 Starlette/anyio deprecation warning 1개.
- 계약 schema export **15개**, fixture **3개** 최신 검사 통과.
- 매장 격리 AST: learn/reg/team **76개 파일, 위반 0건**.
- 격리 PG17: **29개 migration** 재구축 및 전체 `verify_r_handoff.ps1 -IncludeSchemaRebuild` 통과. 운영 `.env` DB를 사용하지 않았다.
- R DB/API: 색인 44, 답변 저장 20, v2 HTTP 117, 점주 전달/완료 53, metadata 보존 13, 문맥/stale 21, reranker 계측 13 checks 통과. 기존 원가·권한·예산 검증도 runner에서 통과했다.
- 최초 DB 실행은 Docker Desktop 중지로 시작되지 않았다. Docker를 시작한 뒤 전체를 다시 실행해 통과했다. 검증용 컨테이너 정리 완료.
- 프론트 변경 없음. 브라우저 검증은 PR의 기존 `R validation` CI가 수행한다. 이 기록은 CI 결과를 미리 통과로 간주하지 않는다.

실자료 판정, 유료 모델 평가, 운영 로그 설정 확인, 실제 W worker 왕복은 이번 검증에 포함하지 않았다. 다음 순서와 담당은 [공유 인계 문서](../plan/R_TEAM_NEXT_20260921.md)를 따른다. main 병합 및 Railway 운영 배포는 이번 변경 공유와 별도다.
