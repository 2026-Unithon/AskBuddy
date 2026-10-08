# P5 배포 migration 순서 오류 — 2026-10-08

배포 로그는 `20261006090000_checklist.sql`이 운영 DB의 마지막 migration보다 이른 미적용 migration이라고 보고했다. SQL 실행 전 CLI의 순서 검사에서 실패했다.

`.github/workflows/deploy-api.yml`의 `supabase db push`에 `--include-all`을 추가했다. migration 파일명과 기존 적용 이력은 유지한다. 이 옵션은 원격 이력에 없는 migration만 적용한다. [Supabase CLI 문서](https://supabase.com/docs/reference/cli/supabase-db-push).

배포와 같은 CLI 2.115.0으로 전용 PostgreSQL 17(pgvector)에서 검증했다.

1. P5를 제외한 43개 migration을 적용하고 이력을 구성했다. 최신 이력은 `20261008090000`이다.
2. 기존 명령의 dry-run에서 사용자 로그와 같은 오류와 P5 파일명이 나왔다.
3. `--include-all --dry-run`은 P5 한 파일만 적용 대상으로 표시했다.
4. `--include-all --yes`는 P5 한 파일 적용에 성공했다. 이력 44개·체크리스트 테이블 7개 확인.
5. 다시 dry-run하면 미적용 목록은 비어 있고 up to date다. 검증용 컨테이너를 삭제했다.

운영 DB에는 이 세션에서 접속하거나 적용하지 않았다. workflow는 테스트된 DEPLOY_SHA를 checkout하므로, 실패한 옛 실행을 단순 재실행하면 옛 명령이 다시 실행된다. 수정이 포함된 커밋을 main에 반영한 뒤 새 배포를 실행해야 한다. 기존 백업·배포 직렬화·테스트 성공 조건은 유지된다.
