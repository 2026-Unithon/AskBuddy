# AskBuddy 운영 배포 런북

이 문서는 `main` 브랜치에서 Supabase, Railway, Vercel을 순서대로 배포하기 위한 기준 절차다.

## 운영 구성

| 영역 | 서비스 | Root Directory | 운영 주소 |
| --- | --- | --- | --- |
| Database | Supabase `askbuddy` | `supabase/` | project ref `xuthckbkdeblvrrsynlo` |
| API | Railway | `api` | `https://askbuddy-production.up.railway.app` |
| Web | Vercel | `web` | `https://ask-buddy-iota.vercel.app` |

배포 순서는 항상 **Database → API → Web** 이다. 새 스키마를 먼저 호환 가능한 형태로 배포하고, 그 스키마를 사용하는 API와 Web을 뒤이어 배포한다.

## DB 변경 원칙

- SQL Editor에서 운영 스키마를 직접 변경하지 않는다.
- 모든 스키마 변경은 `supabase/migrations/<timestamp>_<name>.sql`에 추가한다.
- 이미 적용된 migration 파일은 수정하지 않고 새 migration을 만든다.
- 운영에서 `supabase db reset --linked`를 실행하지 않는다.
- 운영 DB에 seed를 적용하지 않는다. `db/002_seed_demo.sql`은 로컬 개발 전용이다.
- 동시에 여러 사람이 `db push`하지 않도록 운영 배포 담당자를 한 명으로 정한다.
- 1~15단계 동안은 백업, 로컬 검증, dry-run이 통과하면 운영 DB까지 적용한다.
- 15단계 이후에는 기본적으로 migration 파일 작성과 dry-run까지만 수행한다. 사용자가 백업 완료 후 운영 적용을 명시적으로 요청한 경우에만 `db push`한다.

## 최초 기준점

- `20260910132651_remote_schema.sql`: SQL Editor로 만들어져 있던 운영 스키마를 가져온 기준 migration
- `20260910133000_mvp_contract_v1.sql`: MVP 계약 v1 확장 migration

최초 기준점은 이미 운영 migration history에 등록되어 있다. 앞으로 다시 `db pull`로 기준점을 만들지 않는다. 불가피하게 운영에서 수동 변경이 생기면 먼저 변경 원인을 확인하고 별도 migration으로 저장소와 운영의 이력을 맞춘다.

## DB 배포 절차

아래 명령은 저장소 루트에서 실행한다. 비밀번호, access token, service-role key는 명령이나 문서에 직접 기록하지 않는다.

### 1. 사전 확인

```bash
git status --short
supabase migration list --linked
```

예상하지 못한 운영 전용 migration이나 다른 사람의 미완료 변경이 있으면 배포를 중단하고 먼저 이력을 맞춘다.

### 2. 운영 백업

운영 반영 직전에 schema와 data를 각각 백업한다. 백업 파일은 Git에서 제외된 `db/data/`에 저장한다.

```bash
mkdir -p db/data
supabase db dump --linked --schema public \
  -f db/data/production_pre_<change>_<YYYYMMDD>_schema.sql
supabase db dump --linked --data-only --schema public \
  -f db/data/production_pre_<change>_<YYYYMMDD>_data.sql
```

파일 크기가 0이 아닌지 확인한다. 민감한 운영 데이터가 포함될 수 있으므로 커밋하거나 공유하지 않는다.

### 3. 로컬 재구축 및 검증

```bash
supabase start
supabase db reset --local
```

`db reset --local`은 migration 전체를 처음부터 적용한 뒤 로컬 demo seed를 넣는다. 변경에 대응하는 검증 SQL과 API 테스트를 실행한다.

MVP 계약 v1 검증 예시:

```bash
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres \
  -v ON_ERROR_STOP=1 -f db/verify_003_mvp_contract_v1.sql
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres \
  -v ON_ERROR_STOP=1 -f db/test_003_mvp_contract_v1.sql
```

### 4. 운영 변경 미리보기

```bash
supabase db push --linked --dry-run
```

적용하려는 파일만 표시되는지 확인한다. 예기치 않은 migration이 보이면 적용하지 않는다.

### 5. 운영 적용

```bash
supabase db push --linked
supabase migration list --linked
supabase db push --linked --dry-run
```

마지막 dry-run 결과가 최신 상태여야 한다. 운영 적용 후에는 읽기 전용 검증 쿼리로 핵심 테이블, 제약조건, backfill 결과를 확인한다.

## API와 Web 배포

DB migration이 하위 호환되며 검증까지 끝난 뒤 `main`에 반영한다. Railway와 Vercel의 Git 연동이 각각 `api`, `web` root directory를 사용하도록 유지한다.

필수 연결값:

- Vercel `NEXT_PUBLIC_API_URL=https://askbuddy-production.up.railway.app`
- Railway `ALLOWED_ORIGINS=https://ask-buddy-iota.vercel.app`
- Railway의 Supabase URL/key 및 DB 관련 환경변수는 기존 설정을 유지한다.
- Web Push를 사용할 때 Railway에 `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
  `VAPID_SUBJECT`(`mailto:` 또는 운영 HTTPS 주소)를 추가한다. 공개키는 API가 Web에 내려주므로 Vercel
  환경변수로 중복 저장하지 않는다.

환경변수의 실제 비밀값은 저장소에 넣지 않는다. 값 변경 시 각 플랫폼에서 저장한 뒤 해당 서비스를 재배포한다.

## 배포 후 점검

```bash
curl -fsS https://askbuddy-production.up.railway.app/health
curl -fsSI https://ask-buddy-iota.vercel.app/
```

추가로 브라우저에서 다음을 확인한다.

1. Web 첫 화면이 정상 로드된다.
2. Web에서 API 요청이 CORS 오류 없이 완료된다.
3. 기존 사용자의 핵심 데이터가 유지된다.
4. 새 기능의 생성·조회 경로가 동작한다.
5. Railway와 Vercel 배포 로그에 반복 오류가 없다.

## 롤백

이번 MVP migration은 기존 API와 함께 동작하도록 확장형으로 설계했다. 장애가 나면 우선 Railway/Vercel에서 직전 정상 배포로 앱을 롤백하고, 새 컬럼이나 테이블을 즉시 삭제하지 않는다.

DB 역변경이나 백업 복원은 데이터 손실 가능성이 있으므로 자동 수행하지 않는다. 원인을 확인하고 복구 SQL과 영향 범위를 검토한 뒤 사용자의 명시적 승인으로 실행한다.
