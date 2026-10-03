# 카카오 로그인 · 초대 링크 · 합류 승인 · 90일 세션 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 점주·알바가 카카오로 가입·로그인하고, 알바는 초대 링크로 합류 요청 → 점주 승인 후 들어오며, 한 달 이상 쓰지 않으면 다시 로그인하는 90일 슬라이딩 세션을 붙인다.

**Architecture:** FastAPI가 카카오 Authorization Code + PKCE 흐름을 처음부터 끝까지 처리하고(콜백 `api.askbuddy.kr`), 끝나면 `ab_refresh` httpOnly 쿠키만 남긴 채 웹 `/auth/complete`로 돌려보낸다. 웹은 access token(60분)을 메모리에만 두고 `/auth/refresh`로 갱신한다. 합류 대기자는 `store_join_requests`에만 존재하고, 승인 순간 `store_members`가 생긴다. 내보내기는 `store_members.removed_at` 표시이며 매장 격리 경계(`get_store_id`)에서 차단한다.

**Tech Stack:** FastAPI · asyncpg · PyJWT · httpx(카카오 호출) · PostgreSQL 15(Supabase migration) · Next.js 16 App Router · TanStack Query

**Spec:** [KAKAO_AUTH_DESIGN.md](KAKAO_AUTH_DESIGN.md) — 실행자는 설계와 이 계획을 함께 읽는다.

**이슈:** [GitHub 이슈 #37](https://github.com/2026-Unithon/AskBuddy/issues/37)

## Global Constraints

- 커밋·푸시는 사용자가 한다. 각 Task 끝의 "검증"까지만 하고 커밋하지 않는다.
- 새 기능 브랜치는 메인 폴더에서 `git switch -c w/kakao-auth`로 만든다(worktree 금지). 현재 `w/deploy-cicd`의 미커밋 변경과 섞이지 않게 사용자가 먼저 정리한 뒤 시작한다.
- `store_id`는 JWT에서만 꺼낸다. DB 함수의 `store_id`는 키워드 필수 인자, 기본값·Optional 금지. 매장 밖 조회는 `# store-isolation-ok: <사유>`로 표시한다.
- 새 migration은 새 파일. 이미 적용된 migration은 고치지 않는다. 운영 DB에는 적용하지 않는다(로컬까지).
- 주석은 한국어. 상태 문자열은 대문자 상수: 합류 `PENDING` `APPROVED` `REJECTED`, 공급자 `KAKAO`, 알림 `JOIN_REQUESTED`.
- 시크릿(`KAKAO_CLIENT_SECRET`, REST API 키)은 API에만. `web/`에는 공유용 **카카오 JavaScript 키**(`NEXT_PUBLIC_KAKAO_JS_KEY`)만 둔다 — 공개 전제의 키이고 카카오 콘솔에 등록한 도메인에서만 동작한다. 로그인은 SDK가 아니라 서버 흐름(Task 9)으로 한다.
- `.env`에 인라인 주석 금지. `requirements.txt`는 통째로 덮지 않는다(이번 작업은 새 의존성 없음 — httpx·PyJWT 기존).
- access token 60분(`access_token_expire_minutes`), refresh 90일(`refresh_token_expire_days`), refresh 쿠키 `ab_refresh` / `Path=/auth` / `HttpOnly` / `SameSite=Lax`, 동시 회전 유예 30초.
- 초대 토큰 `secrets.token_urlsafe(16)`(22자). 링크 `{WEB_BASE_URL}/join/{token}`. 화면에 토큰 단독 노출 금지.
- 사용자 문구에 서비스명은 AskBuddy만. 신뢰도·완성도 퍼센트 금지.
- `web/`에는 단위 테스트 러너가 없다. "테스트 통과"라고 쓰지 않고 `pnpm check`와 브라우저 확인을 구분해 보고한다.
- 평가용 실제 자료의 브랜드·상호를 테스트 픽스처에 쓰지 않는다. 매장명은 `테스트카페` 같은 가상 이름.

## Review Focus

1. **여러 탭이 동시에 앱을 연다** → 두 탭이 같은 refresh 쿠키로 동시에 `/auth/refresh`. 기대: 둘 다 로그인 유지(한쪽은 30초 유예 401 → 재시도로 통과), family 폐기 없음. → Task 2(유예 테스트), Task 11(웹 재시도).
2. **access token 회전 때 화면 데이터가 날아감** → `SessionExpiryHandler`가 토큰 문자열 변경마다 `queryClient.clear()`. 기대: 같은 사용자의 토큰 갱신은 캐시 유지, 사용자가 바뀔 때만 비움. → Task 11.
3. **오프라인·서버 지연 상태로 앱을 연다** → 시작 시 refresh가 네트워크 오류. 기대: 로그인 화면으로 튕기지 않고 "연결 확인 후 다시 시도" 상태. 401일 때만 비로그인. → Task 11.
4. **승인 대기 중에 점주가 링크를 재생성** → 이미 만든 요청은 유효해야 한다(링크 무효 ≠ 요청 무효). 기대: 점주가 그대로 승인 가능(`approve`는 초대 상태를 보지 않는다). → Task 10 Step 4의 6).
5. **내보낸 알바가 같은 링크/새 링크로 다시 합류** → `unique(store_id,user_id)` 충돌 없이 새 요청 생성, 승인 시 `removed_at` 해제로 이전 학습 기록 복귀. → Task 10 Step 4의 7).

---

## 파일 구조

API
| 파일 | 책임 |
|---|---|
| `supabase/migrations/20261004090000_kakao_auth_join_sessions.sql` (신규) | 테이블 3개·컬럼·제약·기존 코드 무효화 |
| `db/002_seed_demo.sql` (수정) | 데모 초대 토큰 교체 |
| `api/app/config.py` (수정) | 세션·카카오·웹 주소 설정 |
| `api/app/auth/session.py` (신규) | refresh 발급·회전·폐기, access token 발급, 쿠키, Origin 검사 |
| `api/app/auth/router.py` (수정) | 이메일 경로 쿠키 설정, `/refresh` `/logout` `/join-status` `/invites/{token}`, `/join` 요청화, `/invites` 제거 |
| `api/app/auth/oauth_state.py` (신규) | `ab_oauth` 서명 쿠키, `next` 화이트리스트 |
| `api/app/auth/kakao.py` (신규) | PKCE, authorize URL, 토큰 교환·사용자 조회(httpx) |
| `api/app/auth/kakao_accounts.py` (신규) | intent별 판정(순수 함수)과 계정 생성·로그인 처리 |
| `api/app/auth/kakao_router.py` (신규) | `/auth/providers` `/auth/kakao/start` `/auth/kakao/callback` |
| `api/app/members/__init__.py` `invites.py` `join_requests.py` `repository.py` `router.py` (신규) | 초대 링크, 합류 요청·알림, 직원 목록·승인·거절·내보내기 |
| `api/app/deps.py` (수정) | `get_store_id`에 `removed_at is null` |
| `api/app/bootstrap/router.py` (수정) | 활성 멤버십만, STAFF 무매장 → `/staff/pending` |
| `api/app/learn/router.py:408` `api/app/notifications/router.py:82` (수정) | 현재 직원만 |
| `api/app/main.py` (수정) | 라우터 2개 등록 |
| `.claude/skills/store-isolation-check/check_store_id.py` (수정) | `TENANT_TABLES`에 `store_join_requests` |
| `api/tests/test_auth_session.py` `test_members.py` `test_kakao_auth.py` `test_kakao_auth_migration.py` (신규) | |

`store_members` 사용처 분류(2026-10-03 기준 37곳). **`removed_at is null`을 거는 곳:** `deps.py:86`(격리 경계), `bootstrap/router.py:53`, `learn/router.py:408`(점주가 보는 직원 진도 목록), `notifications/router.py:82`(Push 구독 소속 확인), `auth/router.py` 로그인 매장 선택. **그대로 두는 곳:** 나머지 전부 — `get_store_id` 통과 뒤 member_id를 찾는 조회(`learn/router.py:80`, `v2_router.py:340`, `cards/router.py:299·383`), 점주 행 조회(`owner_delivery.py:12`, `owner_answer_worker.py:82`, `publish/bootstrap.py:102` — 점주는 내보낼 수 없음), 과거 기록 조인(receipts·faq·question_contexts·chat_sessions·notification 조인, `roadmap.py:181` 진도 갱신, `answer_storage.py:206`, `index_preparation.py:140`).

Web
| 파일 | 책임 |
|---|---|
| `web/lib/api.ts` (수정) | `credentials: "include"`, refresh 단일 비행·401 재시도, 새 API 함수 |
| `web/lib/store.tsx` (수정) | 토큰 비영속, 시작 시 세션 복원, `SET_TOKEN` |
| `web/lib/guard.tsx` (수정) | 복원 실패 상태, STAFF 무매장 → `/staff/pending` |
| `web/lib/query.ts` (수정) | 새 query key·options |
| `web/components/session-expiry-handler.tsx` (수정) | 사용자 변경 시에만 캐시 비움 |
| `web/components/kakao-login-button.tsx` `invite-link-card.tsx` (신규) | |
| `web/lib/push.ts` (신규), `web/public/sw.js` (수정) | 개인 Push 구독, Push 수신 시 열린 화면에 알림 |
| `web/app/auth/complete/page.tsx` `web/app/auth/email/page.tsx` `web/app/auth/role/page.tsx` `web/app/join/[token]/page.tsx`·`join-client.tsx` `web/app/staff/pending/page.tsx` `web/app/owner/members/page.tsx` (신규) | |
| `web/app/page.tsx` (수정) | 단일 로그인 화면(카카오·이메일) |
| `web/app/role/page.tsx` `web/app/owner/auth/page.tsx` `web/app/staff/auth/page.tsx` (→ `/` redirect), `web/app/owner/complete/page.tsx` `web/app/owner/notifications/page.tsx` `web/app/manifest.ts` (수정) | |

---

### Task 0: 계약 문서 갱신

**Files:**
- Modify: `docs/dev/ASKBUDDY_MVP_CURRENT.md` §8 표, §18-1, §19-1, §21-1, §25, §28
- Modify: `docs/dev/DEV_TODO_CURRENT.md` (새 항목)

**Interfaces:** 없음(문서)

- [ ] **Step 1: MVP §25에서 "카카오 SSO" 제거**, 매직링크·MFA는 남긴다. 줄 바로 아래에 `- 카카오 SSO는 2026-10-03 범위로 당김 — [KAKAO_AUTH_DESIGN.md](plan/KAKAO_AUTH_DESIGN.md)`.
- [ ] **Step 2: §8 화면 표 수정**
  - A01 `로그인·가입 | 단일 로그인 화면: 카카오 로그인(기본)·이메일(보조), 새 계정은 가입 직후 역할 1회 선택, 90일 세션, 목적지 복원 | 필수`
  - §9-1 진입 우선순위에서 역할 선택 화면(`/role`) 선행을 지우고 "로그인 → (새 계정) 역할 선택 → 역할별 첫 화면"으로
  - A03 `직원 합류 | 초대 링크 → 가입 → 점주 승인 대기 | 필수`
  - O08 `알림·직원 관리 | Push 설정, 앱 내 알림 / 초대 링크·합류 승인·직원 목록·내보내기(/owner/members) | 필수`
- [ ] **Step 3: §21-1 운영 구조 표의 API 행을** `API | AWS EC2 + Caddy | api | https://api.askbuddy.kr`로, Web 주소를 `https://askbuddy.kr`로 고친다(현재 Railway·vercel.app으로 남아 있음).
- [ ] **Step 4: §18-1에 새 API 목록**(설계 §4-1·§4-4·§4-5의 경로 그대로), **§19-1에** "대기자는 `store_join_requests`에만 존재, 내보낸 직원은 `get_store_id`에서 403, refresh 토큰은 SHA-256만 저장·회전·재사용 시 family 폐기" 세 줄.
- [ ] **Step 5: §28 문구 사전에 오류 코드 문구 추가**

| 코드 | 문구 |
|---|---|
| `KAKAO_CANCELLED` | 카카오 로그인을 취소했어요. |
| `KAKAO_FAILED` | 카카오 로그인에 실패했어요. 잠시 후 다시 시도해 주세요. |
| `OAUTH_STATE_INVALID` | 로그인 시간이 지났어요. 처음부터 다시 시도해 주세요. |
| `ROLE_CONFLICT` | 이 계정은 다른 역할로 가입되어 있어요. |
| `ROLE_ALREADY_SET` | 이미 역할을 골랐어요. |
| `INVITE_INVALID` | 더 이상 쓸 수 없는 초대 링크예요. 사장님께 새 링크를 받아 주세요. |
| `ALREADY_IN_OTHER_STORE` | 이미 다른 매장에 합류한 계정이에요. |
| `KAKAO_NOT_CONFIGURED` | 지금은 카카오 로그인을 쓸 수 없어요. 이메일로 계속해 주세요. |

- [ ] **Step 6: TODO에 항목 추가** — "카카오 로그인·초대 링크·합류 승인·90일 세션 (#37, PLAN 링크)" 아래 Task 1~15를 체크박스로.
- [ ] **검증:** `cd api && .venv/bin/python -m pytest tests/test_dev_docs_layout.py -q` → PASS (문서 배치 규칙).

---

### Task 1: migration과 데모 시드

**Files:**
- Create: `supabase/migrations/20261004090000_kakao_auth_join_sessions.sql`
- Modify: `db/002_seed_demo.sql:41-42`, `db/002_seed_demo.sql:141`
- Modify: `.claude/skills/store-isolation-check/check_store_id.py` (`TENANT_TABLES`)
- Test: `api/tests/test_kakao_auth_migration.py`

**Interfaces:**
- Produces: 테이블 `user_identities`, `store_join_requests`, `auth_refresh_tokens`; 컬럼 `store_members.removed_at/removed_by`, `invite_codes.revoked_at`; 알림 타입 `JOIN_REQUESTED`·`JOIN_APPROVED`; 알림 destination `/owner/…`·`/staff/…`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""카카오 로그인·합류 승인·세션 migration 정적 확인 (이슈 #37)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / "supabase/migrations/20261004090000_kakao_auth_join_sessions.sql"


def _code() -> str:
    text = SQL.read_text(encoding="utf-8")
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))


def test_new_tables_and_columns():
    code = _code()
    for name in ("create table user_identities", "create table store_join_requests",
                 "create table auth_refresh_tokens"):
        assert name in code, name
    assert "add column removed_at" in code and "add column removed_by" in code
    assert "add column revoked_at" in code
    assert "alter column role drop not null" in code
    assert "'JOIN_REQUESTED'" in code and "'JOIN_APPROVED'" in code
    assert "^/(owner|staff)/" in code


def test_pending_unique_is_partial():
    assert "where status = 'PENDING'" in _code()


def test_old_invite_codes_revoked():
    code = _code()
    assert "update invite_codes" in code and "revoked_at = now()" in code


def test_no_destructive_statements():
    code = _code().lower()
    for bad in ("drop table", "delete from store_members", "truncate"):
        assert bad not in code, bad


def test_demo_seed_uses_long_token():
    seed = (ROOT / "db/002_seed_demo.sql").read_text(encoding="utf-8")
    assert "'CAFE-DEMO'" not in seed
    assert "demoInviteToken0000001" in seed
```

- [ ] **Step 2: 실패 확인** — `cd api && .venv/bin/python -m pytest tests/test_kakao_auth_migration.py -q` → FAIL (`FileNotFoundError`).

- [ ] **Step 3: migration 작성**

```sql
-- 카카오 로그인 · 초대 링크 · 합류 승인 · 90일 세션 (이슈 #37)
-- 모두 가산형이다. 기존 API 는 이 migration 직후에도 그대로 동작한다.
begin;

-- 외부 로그인 연결. 카카오 프로필 원본·토큰은 저장하지 않는다
create table user_identities (
  identity_id       bigint generated always as identity primary key,
  user_id           bigint not null references users(user_id) on delete cascade,
  provider          varchar(20) not null check (provider in ('KAKAO')),
  provider_user_id  varchar(64) not null,
  created_at        timestamptz not null default now(),
  last_login_at     timestamptz not null default now(),
  unique (provider, provider_user_id),
  unique (user_id, provider)
);

-- 합류 요청. 승인 전에는 store_members 행이 없다
create table store_join_requests (
  request_id    bigint generated always as identity primary key,
  store_id      bigint not null references stores(store_id) on delete cascade,
  user_id       bigint not null references users(user_id) on delete cascade,
  invite_id     bigint references invite_codes(invite_id) on delete set null,
  status        varchar(20) not null default 'PENDING'
                check (status in ('PENDING','APPROVED','REJECTED')),
  requested_at  timestamptz not null default now(),
  decided_at    timestamptz,
  decided_by    bigint references users(user_id) on delete set null,
  check ((status = 'PENDING') = (decided_at is null))
);
create unique index store_join_requests_one_pending
  on store_join_requests (store_id, user_id) where status = 'PENDING';
create index store_join_requests_user on store_join_requests (user_id, requested_at desc);

-- 90일 슬라이딩 세션. 원문은 쿠키에만, DB 에는 SHA-256(hex)만 둔다
create table auth_refresh_tokens (
  token_id      bigint generated always as identity primary key,
  user_id       bigint not null references users(user_id) on delete cascade,
  token_hash    char(64) not null unique,
  family_id     uuid not null,
  expires_at    timestamptz not null,
  created_at    timestamptz not null default now(),
  last_used_at  timestamptz,
  revoked_at    timestamptz,
  replaced_by   bigint references auth_refresh_tokens(token_id) on delete set null
);
create index auth_refresh_tokens_active_user
  on auth_refresh_tokens (user_id) where revoked_at is null;
create index auth_refresh_tokens_family on auth_refresh_tokens (family_id);

-- 단일 로그인 화면: 새 계정은 가입 직후 역할을 고른다. 고르기 전에는 비어 있다.
-- users_role_check(in 목록)는 null 을 통과시키므로 그대로 둔다
alter table users alter column role drop not null;

-- 내보내기는 삭제가 아니라 표시. 질문·학습 기록 FK 가 cascade 라 행을 지우면 기록이 사라진다
alter table store_members
  add column removed_at timestamptz,
  add column removed_by bigint references users(user_id) on delete set null;

-- 초대 링크 재생성. 매장당 활성 링크는 하나
alter table invite_codes add column revoked_at timestamptz;
-- 4자리 코드는 대입 가능하다. 전부 무효로 하고 점주가 새 링크를 만든다.
-- 매장당 활성 코드가 여러 개인 경우가 있어 unique 인덱스보다 먼저 정리한다
update invite_codes set revoked_at = now() where revoked_at is null;
create unique index invite_codes_one_active
  on invite_codes (store_id) where revoked_at is null;

alter table notification_events drop constraint notification_events_event_type_check;
alter table notification_events add constraint notification_events_event_type_check
  check (event_type in ('INGEST_COMPLETED','PENDING_QUESTION','OWNER_ANSWER',
                        'JOIN_REQUESTED','JOIN_APPROVED'));

-- 승인 알림은 알바 화면으로 보낸다. 지금까지는 점주 화면만 허용했다
alter table notification_events drop constraint notification_events_destination_check;
alter table notification_events add constraint notification_events_destination_check
  check (destination ~ '^/(owner|staff)/[A-Za-z0-9_/?=&.-]*$');

commit;
```

  `notification_events_event_type_check`의 현재 정의는 `supabase/migrations/20260917130000_m3_owner_answer_delivery.sql:61`이다. 그 사이 다른 migration이 이 제약을 바꿨는지 `grep -n "notification_events_event_type_check" supabase/migrations/*.sql`로 확인하고 최신 값 목록에 `JOIN_REQUESTED`만 더한다.

- [ ] **Step 4: 데모 시드 교체** — `db/002_seed_demo.sql:41-42`를

```sql
insert into invite_codes (store_id, code, expires_at)
select store_id, 'demoInviteToken0000001', 'infinity'::timestamptz
```

  로, 141행 주석을 `--   select code from invite_codes;           -- demoInviteToken0000001 → /join/demoInviteToken0000001`로.

- [ ] **Step 5: 검사기 갱신** — `TENANT_TABLES`에 `# 합류 요청 (가산)` 주석과 `"store_join_requests",` 추가. `user_identities`·`auth_refresh_tokens`는 `store_id`가 없어 넣지 않는다.

- [ ] **Step 6: 테스트 통과 확인** — `.venv/bin/python -m pytest tests/test_kakao_auth_migration.py tests/test_migration_versions.py -q` → PASS.

- [ ] **Step 7: 로컬 DB 적용과 제약 실측**

```bash
docker exec -i supabase_db_AskBuddy psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  < supabase/migrations/20261004090000_kakao_auth_join_sessions.sql
docker exec -i supabase_db_AskBuddy psql -U postgres -d postgres <<'SQL'
\set ON_ERROR_STOP 0
-- 같은 매장·사람의 PENDING 두 건은 막혀야 한다 (ERROR 기대)
begin;
insert into store_join_requests (store_id, user_id) select store_id, owner_id from stores limit 1;
insert into store_join_requests (store_id, user_id) select store_id, owner_id from stores limit 1;
rollback;
-- 결정 없이 APPROVED 는 막혀야 한다 (ERROR 기대)
begin;
insert into store_join_requests (store_id, user_id, status) select store_id, owner_id, 'APPROVED' from stores limit 1;
rollback;
select count(*) as active_codes from invite_codes where revoked_at is null;  -- 0 기대
SQL
```

  Expected: 두 insert 시도에서 ERROR, `active_codes = 0`.

---

### Task 2: 세션 모듈 (refresh 발급·회전·폐기)

**Files:**
- Modify: `api/app/config.py` (설정 7개)
- Create: `api/app/auth/session.py`
- Test: `api/tests/test_auth_session.py`

**Interfaces:**
- Produces:
  - `REFRESH_COOKIE = "ab_refresh"`, `REUSE_GRACE_SECONDS = 30`
  - `class RefreshRejected(Exception)`
  - `async issue_refresh(db, *, user_id: int, family_id: uuid.UUID | None = None) -> tuple[str, int]`
  - `async rotate_refresh(db, *, raw: str) -> tuple[int, str]` — (user_id, 새 원문)
  - `async revoke_family_of(db, *, raw: str) -> None`
  - `async revoke_user_sessions(db, *, user_id: int) -> None`
  - `async active_store_id(db, *, user_id: int) -> int | None`
  - `create_access_token(*, user_id: int, role: str, store_id: int | None) -> str`
  - `async session_payload(db, *, user_id: int) -> dict` — `{"token", "user": {user_id, name, role, store_id?}}`
  - `set_refresh_cookie(response: Response, raw: str) -> None`, `clear_refresh_cookie(response: Response) -> None`
  - `require_allowed_origin(request: Request) -> None` (403 `ORIGIN_FORBIDDEN`)

- [ ] **Step 1: 설정 추가** — `api/app/config.py`의 `ops_login_lock_minutes` 아래에

```python
    # 제품 세션 (이슈 #37). access 는 짧게 두고 refresh 로 90일 동안 이어 쓴다.
    # jwt_expire_minutes 는 scripts/dev_token.py 전용으로 남긴다
    access_token_expire_minutes: int = Field(default=60, ge=5, le=1440)
    refresh_token_expire_days: int = Field(default=90, ge=1, le=365)
    # 로컬 http 에서는 false. 운영은 반드시 true
    auth_cookie_secure: bool = True
    # 카카오 콜백이 끝나면 돌려보낼 웹 주소, 초대 링크의 앞부분
    web_base_url: str = "http://localhost:3000"
    # 셋 다 있어야 카카오 로그인을 연다. 없으면 /auth/kakao/start 가 503
    kakao_rest_api_key: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str = "http://localhost:8000/auth/kakao/callback"
```

- [ ] **Step 2: 실패하는 테스트 작성** — 가짜 DB는 `auth_refresh_tokens`를 dict로 흉내 낸다.

```python
"""90일 슬라이딩 세션 (이슈 #37)."""
import asyncio
import hashlib
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt

from app.auth import session

SETTINGS = SimpleNamespace(
    jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256",
    access_token_expire_minutes=60, refresh_token_expire_days=90,
    auth_cookie_secure=True, origins=["https://askbuddy.kr"])


def _h(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class TokenDb:
    """auth_refresh_tokens 만 흉내 낸다. SQL 앞부분으로 동작을 고른다."""

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.next_id = 1

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchval(self, sql, *args):
        if sql.lstrip().startswith("insert into auth_refresh_tokens"):
            user_id, token_hash, family_id, expires_at = args
            tid = self.next_id
            self.next_id += 1
            self.rows[tid] = dict(token_id=tid, user_id=user_id, token_hash=token_hash,
                                  family_id=family_id, expires_at=expires_at,
                                  revoked_at=None, replaced_by=None)
            return tid
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if "from auth_refresh_tokens where token_hash" in sql:
            return next((dict(r) for r in self.rows.values() if r["token_hash"] == args[0]), None)
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        now = datetime.now(timezone.utc)
        if "replaced_by = $2" in sql:
            row = self.rows[args[0]]
            row.update(revoked_at=now, replaced_by=args[1])
        elif "where family_id = $1" in sql:
            for r in self.rows.values():
                if r["family_id"] == args[0] and r["revoked_at"] is None:
                    r["revoked_at"] = now
        elif "where user_id = $1" in sql:
            for r in self.rows.values():
                if r["user_id"] == args[0] and r["revoked_at"] is None:
                    r["revoked_at"] = now
        else:
            raise AssertionError(sql)


def run(coro):
    return asyncio.run(coro)


class SessionTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.auth.session.get_settings", "app.deps.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        self.db = TokenDb()

    def test_issue_stores_only_hash_with_90_day_expiry(self):
        raw, tid = run(session.issue_refresh(self.db, user_id=7))
        row = self.db.rows[tid]
        self.assertEqual(row["token_hash"], _h(raw))
        self.assertNotIn(raw, str(row))
        left = row["expires_at"] - datetime.now(timezone.utc)
        self.assertAlmostEqual(left.total_seconds(), 90 * 86400, delta=60)

    def test_rotate_returns_new_token_and_revokes_old(self):
        raw, tid = run(session.issue_refresh(self.db, user_id=7))
        user_id, new_raw = run(session.rotate_refresh(self.db, raw=raw))
        self.assertEqual(user_id, 7)
        self.assertNotEqual(new_raw, raw)
        old = self.db.rows[tid]
        self.assertIsNotNone(old["revoked_at"])
        new = next(r for r in self.db.rows.values() if r["token_hash"] == _h(new_raw))
        self.assertEqual(old["replaced_by"], new["token_id"])
        self.assertEqual(new["family_id"], old["family_id"])

    def test_reuse_within_grace_rejects_without_family_revoke(self):
        raw, _ = run(session.issue_refresh(self.db, user_id=7))
        _, new_raw = run(session.rotate_refresh(self.db, raw=raw))
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw=raw))
        # 다른 탭이 받은 새 토큰은 여전히 쓸 수 있다
        user_id, _ = run(session.rotate_refresh(self.db, raw=new_raw))
        self.assertEqual(user_id, 7)

    def test_reuse_after_grace_revokes_whole_family(self):
        raw, tid = run(session.issue_refresh(self.db, user_id=7))
        _, new_raw = run(session.rotate_refresh(self.db, raw=raw))
        self.db.rows[tid]["revoked_at"] = datetime.now(timezone.utc) - timedelta(seconds=31)
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw=raw))
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw=new_raw))

    def test_expired_and_unknown_rejected(self):
        raw, tid = run(session.issue_refresh(self.db, user_id=7))
        self.db.rows[tid]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw=raw))
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw="nope"))

    def test_revoke_user_sessions(self):
        raw1, _ = run(session.issue_refresh(self.db, user_id=7))
        raw2, _ = run(session.issue_refresh(self.db, user_id=7))
        other, _ = run(session.issue_refresh(self.db, user_id=8))
        run(session.revoke_user_sessions(self.db, user_id=7))
        for raw in (raw1, raw2):
            with self.assertRaises(session.RefreshRejected):
                run(session.rotate_refresh(self.db, raw=raw))
        self.assertEqual(run(session.rotate_refresh(self.db, raw=other))[0], 8)

    def test_access_token_shape(self):
        token = session.create_access_token(user_id=7, role="STAFF", store_id=None)
        claims = jwt.decode(token, SETTINGS.jwt_secret, algorithms=["HS256"])
        self.assertEqual((claims["user_id"], claims["role"]), (7, "STAFF"))
        self.assertNotIn("store_id", claims)
        self.assertAlmostEqual(claims["exp"] - datetime.now(timezone.utc).timestamp(), 3600, delta=30)
        token = session.create_access_token(user_id=7, role="STAFF", store_id=3)
        self.assertEqual(jwt.decode(token, SETTINGS.jwt_secret, algorithms=["HS256"])["store_id"], 3)
```

- [ ] **Step 3: 실패 확인** — `.venv/bin/python -m pytest tests/test_auth_session.py -q` → FAIL (`ImportError: cannot import name 'session'`).

- [ ] **Step 4: 구현** — `api/app/auth/session.py`

```python
"""제품 세션 — 90일 슬라이딩 refresh token (이슈 #37).

원문은 httpOnly 쿠키에만 있고 DB 에는 SHA-256 만 둔다. 쓸 때마다 새 토큰으로 바꾼다.
이미 바뀐 토큰이 유예 시간 뒤에 다시 오면 탈취로 보고 그 계열(family) 전체를 폐기한다.
유예 시간 안의 재사용은 여러 탭이 동시에 갱신한 경우라 401 만 돌려준다.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response

from app.config import get_settings
from app.deps import create_token
from app.errors import ApiError

REFRESH_COOKIE = "ab_refresh"
COOKIE_PATH = "/auth"
REUSE_GRACE_SECONDS = 30


class RefreshRejected(Exception):
    """refresh 토큰을 받아줄 수 없다. 사유는 응답에 드러내지 않는다."""


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# store-isolation-ok: 세션은 사용자 단위다. 매장 범위는 access token 발급 때 정한다
async def issue_refresh(db, *, user_id: int, family_id: uuid.UUID | None = None) -> tuple[str, int]:
    raw = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(days=get_settings().refresh_token_expire_days)
    token_id = await db.fetchval(
        """
        insert into auth_refresh_tokens (user_id, token_hash, family_id, expires_at)
        values ($1, $2, $3, $4) returning token_id
        """,
        user_id, _hash(raw), family_id or uuid.uuid4(), expires_at)
    return raw, int(token_id)


# store-isolation-ok: 세션은 사용자 단위다
async def rotate_refresh(db, *, raw: str) -> tuple[int, str]:
    reused_family = None
    async with db.transaction():
        row = await db.fetchrow(
            """
            select token_id, user_id, family_id, expires_at, revoked_at
            from auth_refresh_tokens where token_hash = $1 for update
            """,
            _hash(raw))
        if row is None or row["expires_at"] <= _now():
            raise RefreshRejected()
        if row["revoked_at"] is not None:
            if _now() - row["revoked_at"] > timedelta(seconds=REUSE_GRACE_SECONDS):
                reused_family = row["family_id"]
        else:
            new_raw, new_id = await issue_refresh(
                db, user_id=int(row["user_id"]), family_id=row["family_id"])
            await db.execute(
                """
                update auth_refresh_tokens
                set revoked_at = now(), last_used_at = now(), replaced_by = $2
                where token_id = $1
                """,
                row["token_id"], new_id)
            return int(row["user_id"]), new_raw
    # 트랜잭션 안에서 예외를 던지면 폐기까지 되돌려진다. 밖에서 폐기하고 거절한다
    if reused_family is not None:
        await _revoke_family(db, reused_family)
    raise RefreshRejected()


async def _revoke_family(db, family_id) -> None:
    # store-isolation-ok: 세션 계열 폐기는 사용자 단위다
    await db.execute(
        "update auth_refresh_tokens set revoked_at = now() where family_id = $1 and revoked_at is null",
        family_id)


# store-isolation-ok: 로그아웃은 사용자 단위다
async def revoke_family_of(db, *, raw: str) -> None:
    row = await db.fetchrow(
        "select family_id from auth_refresh_tokens where token_hash = $1", _hash(raw))
    if row is not None:
        await _revoke_family(db, row["family_id"])


# store-isolation-ok: 내보내기 때 그 사용자의 모든 기기를 끊는다
async def revoke_user_sessions(db, *, user_id: int) -> None:
    await db.execute(
        "update auth_refresh_tokens set revoked_at = now() where user_id = $1 and revoked_at is null",
        user_id)


# store-isolation-ok: 로그인 시점에 이 사용자의 현재 매장을 찾는 경계다
async def active_store_id(db, *, user_id: int) -> int | None:
    value = await db.fetchval(
        """
        select store_id from store_members
        where user_id = $1 and removed_at is null
        order by member_id limit 1
        """,
        user_id)
    return int(value) if value is not None else None


def create_access_token(*, user_id: int, role: str, store_id: int | None) -> str:
    payload: dict = {
        "user_id": user_id,
        "role": role,
        "exp": _now() + timedelta(minutes=get_settings().access_token_expire_minutes),
    }
    if store_id is not None:
        payload["store_id"] = store_id
    return create_token(payload)


# store-isolation-ok: 매장은 서버가 활성 멤버십에서 정한다. 요청값을 받지 않는다
async def session_payload(db, *, user_id: int) -> dict:
    user = await db.fetchrow("select user_id, name, role from users where user_id = $1", user_id)
    if user is None:
        raise RefreshRejected()
    store_id = await active_store_id(db, user_id=user_id)
    out_user = {"user_id": int(user["user_id"]), "name": user["name"], "role": user["role"]}
    if store_id is not None:
        out_user["store_id"] = store_id
    return {
        "token": create_access_token(user_id=user_id, role=user["role"], store_id=store_id),
        "user": out_user,
    }


def set_refresh_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE, raw, max_age=s.refresh_token_expire_days * 86400,
        path=COOKIE_PATH, httponly=True, secure=s.auth_cookie_secure, samesite="lax")


def clear_refresh_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE, path=COOKIE_PATH, httponly=True,
        secure=s.auth_cookie_secure, samesite="lax")


def require_allowed_origin(request: Request) -> None:
    """쿠키로 인증하는 엔드포인트의 CSRF 방어. SameSite=Lax 에 더해 Origin 을 확인한다."""
    origin = request.headers.get("origin")
    if origin is None or origin not in get_settings().origins:
        raise ApiError(403, "ORIGIN_FORBIDDEN", "허용되지 않은 요청입니다.")
```

  `SETTINGS`에 `origins`가 있어야 한다(테스트 상단에 이미 있음).

- [ ] **Step 5: 통과 확인** — `.venv/bin/python -m pytest tests/test_auth_session.py -q` → PASS.

---

### Task 3: 세션 API와 이메일 경로 정렬

**Files:**
- Modify: `api/app/auth/router.py` (`_token_for`, `signup`, `login`, `create_store`, 새 `refresh`·`logout`)
- Test: `api/tests/test_auth_session.py` (클래스 추가)

**Interfaces:**
- Consumes: Task 2 전체
- Produces: `POST /auth/refresh` → `{token, user}`; `POST /auth/logout` → 204; 기존 `/auth/signup` `/auth/login` `/auth/stores` 응답에 `Set-Cookie: ab_refresh`
- Produces(내부): `async start_session(db, response, *, user_id: int) -> None` (auth/router.py, Task 6·9가 import)

- [ ] **Step 1: 실패하는 테스트 추가** — `test_auth_session.py` 끝에

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import router as auth_router_module
from app.deps import get_db
from app.errors import install_error_handlers


class SessionApiTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.auth.session.get_settings", "app.deps.get_settings",
                       "app.auth.router.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        self.db = TokenDb()
        users = {7: {"user_id": 7, "name": "알바", "role": "STAFF"}}
        original_fetchrow = self.db.fetchrow

        async def fetchrow(sql, *args):
            if "from users where user_id" in sql:
                return users.get(args[0])
            return await original_fetchrow(sql, *args)

        async def fetchval(sql, *args, _orig=self.db.fetchval):
            if "from store_members" in sql:
                return 3
            return await _orig(sql, *args)

        self.db.fetchrow = fetchrow
        self.db.fetchval = fetchval
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(auth_router_module.router, prefix="/auth")

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app, base_url="https://api.askbuddy.kr")
        self.addCleanup(self.client.close)

    def _cookie(self):
        raw, _ = run(session.issue_refresh(self.db, user_id=7))
        self.client.cookies.set("ab_refresh", raw, domain="api.askbuddy.kr", path="/auth")
        return raw

    def test_refresh_rotates_cookie_and_returns_store_token(self):
        raw = self._cookie()
        res = self.client.post("/auth/refresh", headers={"Origin": "https://askbuddy.kr"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["user"], {"user_id": 7, "name": "알바", "role": "STAFF", "store_id": 3})
        set_cookie = res.headers["set-cookie"]
        self.assertIn("ab_refresh=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("Path=/auth", set_cookie)
        self.assertIn("SameSite=lax", set_cookie)
        self.assertNotIn(raw, set_cookie)

    def test_refresh_without_cookie_is_401(self):
        res = self.client.post("/auth/refresh", headers={"Origin": "https://askbuddy.kr"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"]["code"], "SESSION_EXPIRED")

    def test_refresh_from_foreign_origin_is_403(self):
        self._cookie()
        for headers in ({"Origin": "https://evil.example"}, {}):
            res = self.client.post("/auth/refresh", headers=headers)
            self.assertEqual(res.status_code, 403)

    def test_logout_revokes_and_clears(self):
        raw = self._cookie()
        res = self.client.post("/auth/logout", headers={"Origin": "https://askbuddy.kr"})
        self.assertEqual(res.status_code, 204)
        self.assertIn('ab_refresh=""', res.headers["set-cookie"])
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw=raw))
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_auth_session.py -q` → 새 테스트 4개 FAIL(404).

- [ ] **Step 3: 구현** — `api/app/auth/router.py`

  import 추가:

```python
from fastapi import APIRouter, HTTPException, Request, Response
from app.auth.session import (
    REFRESH_COOKIE, RefreshRejected, active_store_id, clear_refresh_cookie,
    create_access_token, issue_refresh, require_allowed_origin, revoke_family_of,
    rotate_refresh, session_payload, set_refresh_cookie,
)
from app.errors import ApiError
```

  `_token_for`를 교체(이 파일 안 호출부는 그대로 둔다):

```python
def _token_for(user_id: int, store_id: int | None, role: str) -> str:
    return create_access_token(user_id=user_id, role=role, store_id=store_id)


async def start_session(db, response: Response, *, user_id: int) -> None:
    """로그인·가입이 끝나면 refresh 쿠키를 심는다. 카카오 콜백도 이 함수를 쓴다."""
    raw, _ = await issue_refresh(db, user_id=user_id)
    set_refresh_cookie(response, raw)
```

  `signup`·`login`·`create_store` 시그니처에 `response: Response`를 추가하고, `return` 직전에 `await start_session(db, response, user_id=<그 사용자>)`. `create_store`는 같은 사용자의 기존 쿠키가 있으므로 **새로 심지 않는다**(access token만 재발급) — 시그니처 변경 없음.

  `login`의 매장 선택 쿼리를 내보낸 멤버십 제외로:

```python
        left join store_members sm on sm.user_id = u.user_id and sm.removed_at is null
```

  새 엔드포인트(파일 끝, `DEFAULT_CATEGORIES` 위):

```python
# store-isolation-ok: 쿠키 세션 갱신. 매장은 서버가 활성 멤버십에서 정한다
@router.post("/refresh")
async def refresh(request: Request, response: Response, db: Db):
    require_allowed_origin(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise ApiError(401, "SESSION_EXPIRED", "다시 로그인해 주세요.")
    try:
        user_id, new_raw = await rotate_refresh(db, raw=raw)
        payload = await session_payload(db, user_id=user_id)
    except RefreshRejected as exc:
        raise ApiError(401, "SESSION_EXPIRED", "다시 로그인해 주세요.") from exc
    set_refresh_cookie(response, new_raw)
    return payload


# store-isolation-ok: 로그아웃은 사용자 단위 세션 폐기다
@router.post("/logout", status_code=204)
async def logout(request: Request, db: Db):
    require_allowed_origin(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await revoke_family_of(db, raw=raw)
    out = Response(status_code=204)
    clear_refresh_cookie(out)
    return out
```

  주입된 `response`가 아니라 새 `Response`를 돌려준다 — 204 본문 없음과 쿠키 삭제 헤더를 함께 보장한다. 시그니처에서 `response: Response`는 지운다.

- [ ] **Step 4: 통과 확인** — `.venv/bin/python -m pytest tests/test_auth_session.py tests/test_bootstrap.py tests/test_ops_auth.py -q` → PASS.

---

### Task 4: 내보낸 직원 차단 (격리 경계와 현재 직원 조회)

**Files:**
- Modify: `api/app/deps.py:85-88`, `api/app/bootstrap/router.py:22-27,50-58`, `api/app/learn/router.py:404-412`, `api/app/notifications/router.py:80-84`
- Test: `api/tests/test_members.py` (신규, 이후 Task가 이어 씀), `api/tests/test_bootstrap.py` (수정)

**Interfaces:**
- Produces: `get_store_id`는 `removed_at is null`인 멤버십만 통과. `/app/bootstrap`의 STAFF 무매장 `default_destination == "/staff/pending"`.

- [ ] **Step 1: 실패하는 테스트 작성** — `api/tests/test_members.py`

```python
"""직원 관리·합류 승인·내보내기 (이슈 #37)."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import CurrentStoreId, create_token, get_db

SETTINGS = SimpleNamespace(jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256")


def bearer(**claims):
    claims.setdefault("exp", datetime.now(timezone.utc) + timedelta(minutes=5))
    return {"Authorization": "Bearer " + create_token(claims)}


class MembershipDb:
    def __init__(self, removed: bool):
        self.removed = removed

    async def fetchrow(self, sql, *args):
        assert "removed_at is null" in sql, sql
        return None if self.removed else {"member_role": "STAFF"}


class StoreGateTest(unittest.TestCase):
    def _client(self, removed):
        p = patch("app.deps.get_settings", return_value=SETTINGS)
        p.start()
        self.addCleanup(p.stop)
        app = FastAPI()

        @app.get("/store-only")
        async def store_only(store_id: CurrentStoreId):
            return {"store_id": store_id}

        db = MembershipDb(removed)

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        return TestClient(app)

    def test_active_member_passes(self):
        res = self._client(False).get("/store-only", headers=bearer(user_id=5, store_id=1, role="STAFF"))
        self.assertEqual(res.status_code, 200)

    def test_removed_member_blocked_with_live_token(self):
        res = self._client(True).get("/store-only", headers=bearer(user_id=5, store_id=1, role="STAFF"))
        self.assertEqual(res.status_code, 403)
```

  `api/tests/test_bootstrap.py`에서 STAFF 무매장 기대값을 찾는다: `grep -n "staff/auth" api/tests/test_bootstrap.py`. 있으면 `/staff/pending`으로 바꾸고, 없으면 같은 파일 방식대로 "STAFF, store_id 없는 토큰 → `default_destination == '/staff/pending'`" 테스트를 하나 추가한다.

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_members.py tests/test_bootstrap.py -q` → FAIL(`assert "removed_at is null"`).

- [ ] **Step 3: 구현**
  - `deps.py:86` SQL → `"select member_role from store_members where store_id = $1 and user_id = $2 and removed_at is null"`
  - `bootstrap/router.py` `_default_destination`의 마지막 줄 → `return "/staff/roadmap" if has_store else "/staff/pending"`. 멤버십 조회 `where`에 `and sm.removed_at is null`.
  - `learn/router.py:408` 직원 목록 `where`에 `and m.removed_at is null`.
  - `notifications/router.py:82` → `select 1 from store_members where store_id = $1 and user_id = $2 and removed_at is null`.

- [ ] **Step 4: 통과 확인** — `.venv/bin/python -m pytest tests/ -q` → 전체 PASS(기존 테스트의 가짜 DB가 SQL 문자열을 비교하다 깨지면, 그 가짜 DB의 매칭 문자열만 고친다).

---

### Task 5: 초대 링크 서비스와 API

**Files:**
- Create: `api/app/members/__init__.py`, `api/app/members/invites.py`, `api/app/members/router.py`
- Modify: `api/app/auth/router.py` (`POST /invites`·`_make_invite_code`·`_INVITE_TTL_DAYS` 제거, `GET /invites/{token}` 추가), `api/app/main.py`
- Test: `api/tests/test_members.py` (클래스 추가)

**Interfaces:**
- Produces:
  - `invites.new_token() -> str` (22자)
  - `invites.invite_url(token: str) -> str`
  - `async invites.get_or_create(db, *, store_id: int) -> str` (토큰)
  - `async invites.rotate(db, *, store_id: int) -> str`
  - `async invites.resolve(db, *, token: str) -> dict | None` — `{invite_id, store_id, store_name}`
  - `async invites.resolve_by_id(db, *, invite_id: int | None) -> dict | None` — 같은 모양(코드는 Task 9 Step 4에 있다. 이 Task에서 함께 넣어도 된다)
  - `members/router.py`: `router`, 의존성 `OwnerStoreId`(Annotated int)
  - `GET /members/invite-link`, `POST /members/invite-link/rotate` → `{url}`; `GET /auth/invites/{token}` → `{store_name}` / 404 `INVITE_INVALID`

- [ ] **Step 1: 실패하는 테스트 추가** — `test_members.py`에

```python
from app.members import invites
from app.members import router as members_router_module
from app.auth import router as auth_router_module
from app.errors import install_error_handlers


class FakeInviteDb:
    def __init__(self):
        self.rows = []  # dict(invite_id, store_id, code, revoked_at)

    def transaction(self):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def tx():
            yield
        return tx()

    async def fetchval(self, sql, *args):
        if "select code from invite_codes" in sql:
            row = next((r for r in self.rows if r["store_id"] == args[0] and r["revoked_at"] is None), None)
            return row["code"] if row else None
        if sql.lstrip().startswith("insert into invite_codes"):
            self.rows.append(dict(invite_id=len(self.rows) + 1, store_id=args[0], code=args[1], revoked_at=None))
            return args[1]
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if sql.lstrip().startswith("update invite_codes set revoked_at"):
            for r in self.rows:
                if r["store_id"] == args[0] and r["revoked_at"] is None:
                    r["revoked_at"] = "now"
            return
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if "from invite_codes i" in sql:
            row = next((r for r in self.rows if r["code"] == args[0] and r["revoked_at"] is None), None)
            return dict(invite_id=row["invite_id"], store_id=row["store_id"], store_name="테스트카페") if row else None
        if "from store_members" in sql:
            # get_store_id 경계: user 1 은 점주, 그 밖은 직원
            return {"member_role": "OWNER" if args[1] == 1 else "STAFF"}
        raise AssertionError(sql)


class InviteLinkTest(unittest.TestCase):
    def setUp(self):
        settings = SimpleNamespace(**vars(SETTINGS), web_base_url="https://askbuddy.kr")
        for target in ("app.deps.get_settings", "app.members.invites.get_settings"):
            p = patch(target, return_value=settings)
            p.start()
            self.addCleanup(p.stop)
        self.db = FakeInviteDb()
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(members_router_module.router, prefix="/members")
        app.include_router(auth_router_module.router, prefix="/auth")

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)
        self.owner = bearer(user_id=1, store_id=1, role="OWNER")

    def test_token_is_long_and_url_safe(self):
        token = invites.new_token()
        self.assertGreaterEqual(len(token), 22)
        self.assertRegex(token, r"^[A-Za-z0-9_-]+$")

    def test_get_creates_once_then_reuses(self):
        a = self.client.get("/members/invite-link", headers=self.owner).json()["url"]
        b = self.client.get("/members/invite-link", headers=self.owner).json()["url"]
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("https://askbuddy.kr/join/"))
        self.assertEqual(len(self.db.rows), 1)

    def test_rotate_invalidates_previous_link(self):
        old = self.client.get("/members/invite-link", headers=self.owner).json()["url"].rsplit("/", 1)[1]
        new = self.client.post("/members/invite-link/rotate", headers=self.owner).json()["url"].rsplit("/", 1)[1]
        self.assertNotEqual(old, new)
        self.assertEqual(self.client.get(f"/auth/invites/{old}").status_code, 404)
        self.assertEqual(self.client.get(f"/auth/invites/{new}").json(), {"store_name": "테스트카페"})

    def test_preview_unknown_token_404_same_shape(self):
        res = self.client.get("/auth/invites/doesnotexist000000000")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "INVITE_INVALID")

    def test_staff_cannot_manage_links(self):
        staff = bearer(user_id=5, store_id=1, role="STAFF")
        self.assertEqual(self.client.get("/members/invite-link", headers=staff).status_code, 403)
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_members.py -q` → FAIL(`ModuleNotFoundError: app.members`).

- [ ] **Step 3: 구현** — `api/app/members/__init__.py`: `"""점주의 직원 초대·합류 승인·내보내기 (이슈 #37)."""`

  `api/app/members/invites.py`

```python
"""초대 링크. 토큰은 추측할 수 없는 128비트 무작위 값이고 화면에는 링크로만 나간다.

점주가 언제든 다시 복사할 수 있어야 해서 토큰을 해시하지 않고 그대로 둔다.
링크가 새더라도 점주 승인이 막는다. 회수는 재생성(revoked_at)으로만 한다.
"""
from __future__ import annotations

import secrets

import asyncpg

from app.config import get_settings


def new_token() -> str:
    return secrets.token_urlsafe(16)


def invite_url(token: str) -> str:
    return f"{get_settings().web_base_url.rstrip('/')}/join/{token}"


async def _create(db, *, store_id: int) -> str:
    # 매장당 활성 링크 unique 인덱스가 동시 생성을 막는다. 충돌하면 이미 생긴 것을 쓴다
    try:
        return await db.fetchval(
            """
            insert into invite_codes (store_id, code, expires_at)
            values ($1, $2, 'infinity') returning code
            """,
            store_id, new_token())
    except asyncpg.UniqueViolationError:
        existing = await db.fetchval(
            "select code from invite_codes where store_id = $1 and revoked_at is null", store_id)
        if existing is None:
            raise
        return existing


async def get_or_create(db, *, store_id: int) -> str:
    existing = await db.fetchval(
        "select code from invite_codes where store_id = $1 and revoked_at is null", store_id)
    return existing if existing is not None else await _create(db, store_id=store_id)


async def rotate(db, *, store_id: int) -> str:
    async with db.transaction():
        await db.execute(
            "update invite_codes set revoked_at = now() where store_id = $1 and revoked_at is null",
            store_id)
        return await _create(db, store_id=store_id)


# store-isolation-ok: 공개 초대 링크의 토큰으로 매장을 찾는 경계다. 매장명만 밖으로 나간다
async def resolve(db, *, token: str) -> dict | None:
    row = await db.fetchrow(
        """
        select i.invite_id, i.store_id, s.store_name
        from invite_codes i join stores s on s.store_id = i.store_id
        where i.code = $1 and i.revoked_at is null and i.expires_at > now()
        """,
        token)
    return dict(row) if row else None
```

  `api/app/members/router.py`

```python
"""점주 직원 관리 API (이슈 #37). 모든 쿼리는 JWT 의 store_id 로 좁힌다."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import Claims, CurrentStoreId, Db
from app.errors import ApiError
from app.members import invites

router = APIRouter()


async def get_owner_store_id(store_id: CurrentStoreId, claims: Claims) -> int:
    if claims.get("role") != "OWNER":
        raise ApiError(403, "FORBIDDEN", "사장님만 쓸 수 있어요.")
    return store_id


OwnerStoreId = Annotated[int, Depends(get_owner_store_id)]


@router.get("/invite-link")
async def get_invite_link(db: Db, store_id: OwnerStoreId):
    return {"url": invites.invite_url(await invites.get_or_create(db, store_id=store_id))}


@router.post("/invite-link/rotate")
async def rotate_invite_link(db: Db, store_id: OwnerStoreId):
    return {"url": invites.invite_url(await invites.rotate(db, store_id=store_id))}
```

  `api/app/auth/router.py`: `_INVITE_TTL_DAYS`, `_make_invite_code`, `create_invite`(POST `/invites`) 삭제, `secrets` import가 남는지 확인. 추가:

```python
from app.members import invites


# store-isolation-ok: 공개 초대 링크 미리보기. 매장명만 돌려준다
@router.get("/invites/{token}")
async def preview_invite(token: str, db: Db):
    found = await invites.resolve(db, token=token)
    if found is None:
        raise ApiError(404, "INVITE_INVALID", "더 이상 쓸 수 없는 초대 링크예요.")
    return {"store_name": found["store_name"]}
```

  `api/app/main.py`: `from app.members.router import router as members_router`, `app.include_router(members_router, prefix="/members", tags=["members"])`를 notifications 아래에. `errors.py`의 새 오류 envelope 경로 목록(`validation_error_handler`)에 `"/members"`를 추가한다.

- [ ] **Step 4: 통과 확인** — `.venv/bin/python -m pytest tests/test_members.py -q` → PASS. `grep -rn "createInvite\|/auth/invites\"" web/lib` 결과는 Task 14에서 정리한다(지금은 웹이 깨진 상태로 남는 것을 메모).

---

### Task 6: 합류 요청 (로그인 알바의 요청, 상태 조회, 점주 알림, 알바 이메일 가입)

결정(2026-10-03): 알바는 초대 없이도 계정을 만들 수 있고, 매장이 없으면 아무 데도 접근하지 못한다. 로그인된 알바가 초대 링크를 열면 바로 합류 요청이 간다. 이메일+초대코드 한 번에 가입·합류하던 `/auth/join`은 없앤다.

**Files:**
- Create: `api/app/members/join_requests.py`
- Modify: `api/app/auth/router.py` (`SignupRequest`·`signup`이 STAFF 허용, `JoinRequest`·`join` 삭제, 새 `POST /join-requests`·`GET /join-status`)
- Modify: `api/app/notifications/service.py` (`create_join_request_notification`)
- Test: `api/tests/test_members.py` (클래스 추가)

**Interfaces:**
- Consumes: `invites.resolve`, `start_session`, `active_store_id`, `create_notification_event`, `deliver_notification`
- Produces:
  - `class JoinRefused(Exception)` — `.code`, `.status` (`ROLE_CONFLICT` 403, `ALREADY_IN_OTHER_STORE` 409)
  - `join_requests.decide_join(*, user_role: str, active_store_id: int | None, invite_store_id: int) -> str` — `"ALREADY_MEMBER" | "REQUEST"` (Task 9가 재사용)
  - `async join_requests.request_join(db, *, store_id: int, user_id: int, invite_id: int | None, staff_name: str) -> tuple[int, int | None]` — (request_id, 새로 만든 점주 알림 id). 이미 PENDING이면 `(그 id, None)`
  - `join_requests.status_from_rows(latest: dict | None, *, active_member: bool) -> dict`
  - `async join_requests.latest_status(db, *, user_id: int) -> dict` — `{"status": "PENDING"|"REJECTED"|"APPROVED"|"REMOVED"|"NONE", "store_name": str | None}`
  - `async create_join_request_notification(db, *, store_id: int, request_id: int, staff_name: str) -> int | None`
  - `POST /auth/signup` — `role: "OWNER" | "STAFF"` 둘 다 받는다. STAFF 응답 토큰에는 store_id가 없다
  - `POST /auth/join-requests` `{invite_token}` → `{status: "PENDING" | "ALREADY_MEMBER", store_name}`
  - `GET /auth/join-status` → `latest_status` 그대로

- [ ] **Step 1: 실패하는 테스트 추가** — `test_members.py`에

```python
from app.members.join_requests import JoinRefused, decide_join, status_from_rows


class DecideJoinTest(unittest.TestCase):
    def test_request_when_no_store(self):
        self.assertEqual(decide_join(user_role="STAFF", active_store_id=None, invite_store_id=1), "REQUEST")

    def test_already_member_of_same_store(self):
        self.assertEqual(decide_join(user_role="STAFF", active_store_id=1, invite_store_id=1), "ALREADY_MEMBER")

    def test_owner_refused(self):
        with self.assertRaises(JoinRefused) as ctx:
            decide_join(user_role="OWNER", active_store_id=1, invite_store_id=1)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("ROLE_CONFLICT", 403))

    def test_other_store_refused(self):
        with self.assertRaises(JoinRefused) as ctx:
            decide_join(user_role="STAFF", active_store_id=2, invite_store_id=1)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("ALREADY_IN_OTHER_STORE", 409))


class JoinStatusTest(unittest.TestCase):
    def test_no_request(self):
        self.assertEqual(status_from_rows(None, active_member=False), {"status": "NONE", "store_name": None})

    def test_pending_and_rejected_pass_through(self):
        for status in ("PENDING", "REJECTED"):
            row = {"status": status, "store_name": "테스트카페"}
            self.assertEqual(status_from_rows(row, active_member=False)["status"], status)

    def test_approved_but_removed_is_removed(self):
        row = {"status": "APPROVED", "store_name": "테스트카페"}
        self.assertEqual(status_from_rows(row, active_member=False)["status"], "REMOVED")
        self.assertEqual(status_from_rows(row, active_member=True)["status"], "APPROVED")


class JoinRequestEndpointTest(unittest.TestCase):
    """로그인한 알바가 초대 링크로 합류 요청을 보낸다."""

    def setUp(self):
        settings = SimpleNamespace(**vars(SETTINGS), web_base_url="https://askbuddy.kr",
                                   access_token_expire_minutes=60, refresh_token_expire_days=90,
                                   auth_cookie_secure=True, origins=["https://askbuddy.kr"])
        for target in ("app.deps.get_settings", "app.auth.session.get_settings",
                       "app.members.invites.get_settings"):
            p = patch(target, return_value=settings)
            p.start()
            self.addCleanup(p.stop)
        self.calls = []
        self.delivered = []
        self.active = {5: None, 6: 1, 8: 2}  # user_id → 활성 매장

        async def resolve(db, *, token):
            ok = token == "good-token-0000000"
            return {"invite_id": 9, "store_id": 1, "store_name": "테스트카페"} if ok else None

        async def active_store_id(db, *, user_id):
            return self.active.get(user_id)

        async def request_join(db, **kw):
            self.calls.append(kw)
            return 77, 11

        async def deliver(store_id, notification_id):
            self.delivered.append((store_id, notification_id))

        for target, fn in (("app.auth.router.invites.resolve", resolve),
                           ("app.auth.router.active_store_id", active_store_id),
                           ("app.auth.router.join_requests.request_join", request_join),
                           ("app.auth.router.deliver_notification", deliver)):
            q = patch(target, side_effect=fn)
            q.start()
            self.addCleanup(q.stop)

        class Db:
            async def fetchval(self, sql, *args):
                if "select name from users" in sql:
                    return "새알바"
                raise AssertionError(sql)

        app = FastAPI()
        install_error_handlers(app)
        app.include_router(auth_router_module.router, prefix="/auth")
        db = Db()

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)

    def post(self, token, headers):
        return self.client.post("/auth/join-requests", json={"invite_token": token}, headers=headers)

    def test_storeless_staff_creates_request_and_notifies_owner(self):
        res = self.post("good-token-0000000", bearer(user_id=5, role="STAFF"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "PENDING", "store_name": "테스트카페"})
        self.assertEqual(self.calls[0] | {}, {"store_id": 1, "user_id": 5, "invite_id": 9, "staff_name": "새알바"})
        self.assertEqual(self.delivered, [(1, 11)])

    def test_already_member_does_not_request(self):
        res = self.post("good-token-0000000", bearer(user_id=6, store_id=1, role="STAFF"))
        self.assertEqual(res.json(), {"status": "ALREADY_MEMBER", "store_name": "테스트카페"})
        self.assertEqual(self.calls, [])

    def test_owner_token_refused(self):
        res = self.post("good-token-0000000", bearer(user_id=6, store_id=1, role="OWNER"))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"]["code"], "ROLE_CONFLICT")

    def test_member_of_other_store_refused(self):
        res = self.post("good-token-0000000", bearer(user_id=8, store_id=2, role="STAFF"))
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "ALREADY_IN_OTHER_STORE")

    def test_invalid_link_and_no_login(self):
        res = self.post("revoked-token-0000", bearer(user_id=5, role="STAFF"))
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "INVITE_INVALID")
        self.assertEqual(self.post("good-token-0000000", {}).status_code, 401)
        self.assertEqual(self.calls, [])


class StaffSignupTest(unittest.TestCase):
    """알바는 초대 없이 가입할 수 있다. 매장 없는 계정이 된다."""

    def setUp(self):
        settings = SimpleNamespace(**vars(SETTINGS), access_token_expire_minutes=60,
                                   refresh_token_expire_days=90, auth_cookie_secure=True,
                                   origins=["https://askbuddy.kr"])
        for target in ("app.deps.get_settings", "app.auth.session.get_settings"):
            p = patch(target, return_value=settings)
            p.start()
            self.addCleanup(p.stop)

        async def start_session(db, response, *, user_id):
            response.set_cookie("ab_refresh", "x")

        q = patch("app.auth.router.start_session", side_effect=start_session)
        q.start()
        self.addCleanup(q.stop)

        class Db:
            async def fetchrow(self, sql, *args):
                if "from users where email" in sql:
                    return None
                if sql.lstrip().startswith("insert into users"):
                    return {"user_id": 5, "name": args[0], "email": args[2], "role": args[4]}
                raise AssertionError(sql)

            async def execute(self, sql, *args):
                raise AssertionError("store_members 에 쓰면 안 된다: " + sql)

        app = FastAPI()
        install_error_handlers(app)
        app.include_router(auth_router_module.router, prefix="/auth")
        db = Db()

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)

    def test_staff_signup_has_no_store(self):
        res = self.client.post("/auth/signup", json={
            "name": "새알바", "email": "new@example.com", "password": "secret1", "role": "STAFF"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user"]["role"], "STAFF")
        claims = jwt.decode(res.json()["token"], SETTINGS.jwt_secret, algorithms=["HS256"])
        self.assertNotIn("store_id", claims)

    def test_join_endpoint_removed(self):
        self.assertEqual(self.client.post("/auth/join", json={}).status_code, 404)
```

  파일 상단 import에 `import jwt`를 추가한다. `bearer()`는 `store_id`를 넘기지 않으면 claims에 넣지 않는다(Task 4 정의 그대로).

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_members.py -q` → FAIL(`ImportError: decide_join`).

- [ ] **Step 3: 점주 알림 함수** — `notifications/service.py`의 `create_ingest_completed_notification` 아래

```python
async def create_join_request_notification(
    db: asyncpg.Connection, *, store_id: int, request_id: int, staff_name: str,
) -> int | None:
    """알바 합류 요청을 점주에게 알린다. 점주 행이 없으면 알리지 않는다."""
    owner_id = await db.fetchval(
        """
        select user_id from store_members
        where store_id = $1 and member_role = 'OWNER' and removed_at is null
        order by member_id limit 1
        """,
        store_id)
    if owner_id is None:
        return None
    return await create_notification_event(
        db,
        store_id=store_id,
        recipient_user_id=int(owner_id),
        event_type="JOIN_REQUESTED",
        aggregate_type="JOIN_REQUEST",
        aggregate_id=request_id,
        dedupe_key=f"join_request:{request_id}",
        title="새 직원이 합류를 요청했어요",
        body=f"{staff_name}님이 매장 합류 승인을 기다리고 있어요.",
        destination="/owner/members",
    )
```

  `aggregate_type`에 check 제약이 있는지 `grep -n "aggregate_type" supabase/migrations/*.sql | grep -i check`로 확인한다. 있으면 Task 1 migration에 `'JOIN_REQUEST'`를 추가하고(로컬에만 적용했으므로 `supabase db reset`으로 다시 만든다) `test_new_tables_and_columns`에 `assert "'JOIN_REQUEST'" in code`를 더한다.

- [ ] **Step 4: `join_requests.py` 구현**

```python
"""알바 합류 요청. 승인 전에는 store_members 행을 만들지 않는다."""
from __future__ import annotations

import asyncpg

from app.notifications.service import create_join_request_notification


class JoinRefused(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status


def decide_join(*, user_role: str, active_store_id: int | None, invite_store_id: int) -> str:
    """이미 있는 계정이 초대 링크를 열었을 때. 카카오 STAFF_JOIN 도 같은 규칙을 쓴다."""
    if user_role != "STAFF":
        raise JoinRefused("ROLE_CONFLICT", 403)
    if active_store_id == invite_store_id:
        return "ALREADY_MEMBER"
    if active_store_id is not None:
        raise JoinRefused("ALREADY_IN_OTHER_STORE", 409)
    return "REQUEST"


def status_from_rows(latest: dict | None, *, active_member: bool) -> dict:
    """가장 최근 요청과 현재 멤버십으로 알바 화면 상태를 정한다."""
    if latest is None:
        return {"status": "NONE", "store_name": None}
    status = latest["status"]
    if status == "APPROVED" and not active_member:
        status = "REMOVED"
    return {"status": status, "store_name": latest["store_name"]}


async def request_join(db, *, store_id: int, user_id: int, invite_id: int | None,
                       staff_name: str) -> tuple[int, int | None]:
    """(request_id, 새로 만든 점주 알림 id). 이미 기다리는 요청이 있으면 알림 없이 그 id."""
    existing = await db.fetchval(
        """
        select request_id from store_join_requests
        where store_id = $1 and user_id = $2 and status = 'PENDING'
        """,
        store_id, user_id)
    if existing is not None:
        return int(existing), None
    try:
        async with db.transaction():
            request_id = int(await db.fetchval(
                """
                insert into store_join_requests (store_id, user_id, invite_id)
                values ($1, $2, $3) returning request_id
                """,
                store_id, user_id, invite_id))
            notification_id = await create_join_request_notification(
                db, store_id=store_id, request_id=request_id, staff_name=staff_name)
    except asyncpg.UniqueViolationError:
        # 같은 사람이 동시에 두 번 눌렀다. 먼저 생긴 요청을 쓴다
        return int(await db.fetchval(
            """
            select request_id from store_join_requests
            where store_id = $1 and user_id = $2 and status = 'PENDING'
            """,
            store_id, user_id)), None
    return request_id, notification_id


# store-isolation-ok: 매장 소속 전 알바가 자기 요청만 본다(user_id 는 JWT)
async def latest_status(db, *, user_id: int) -> dict:
    latest = await db.fetchrow(
        """
        select r.store_id, r.status, s.store_name
        from store_join_requests r join stores s on s.store_id = r.store_id
        where r.user_id = $1
        order by r.requested_at desc, r.request_id desc limit 1
        """,
        user_id)
    active = False
    if latest is not None:
        active = await db.fetchval(
            """
            select exists(select 1 from store_members
                          where store_id = $1 and user_id = $2 and removed_at is null)
            """,
            latest["store_id"], user_id)
    return status_from_rows(dict(latest) if latest else None, active_member=bool(active))
```

- [ ] **Step 5: `auth/router.py` 변경**
  - `SignupRequest.role`은 그대로 `^(OWNER|STAFF)$`. `signup`의 `if req.role != "OWNER": raise HTTPException(400, ...)` 두 줄을 지우고, insert의 `'OWNER'` 리터럴을 `$5`로 바꿔 `req.role`을 넘긴다(가짜 DB가 `args[4]`로 읽는다). 독스트링은 `"""점주·알바 가입. 알바는 매장 없는 계정이 되고, 초대 링크로 합류를 요청한다."""`.
  - `JoinRequest` 클래스와 `join` 핸들러를 지운다.
  - import: `from fastapi import BackgroundTasks`, `from app.members import join_requests`, `from app.notifications.service import deliver_notification`(Task 3의 session import에 이미 `active_store_id` 포함).
  - 추가:

```python
class JoinByInviteRequest(BaseModel):
    invite_token: str = Field(min_length=16, max_length=64)


_JOIN_MESSAGES = {
    "ROLE_CONFLICT": "사장님 계정으로는 직원으로 합류할 수 없어요.",
    "ALREADY_IN_OTHER_STORE": "이미 다른 매장에 합류한 계정이에요.",
}


# store-isolation-ok: 매장 소속 전 알바의 합류 요청. 매장은 초대 토큰으로 서버가 찾는다
@router.post("/join-requests")
async def create_join_request(req: JoinByInviteRequest, db: Db, claims: Claims,
                              user_id: CurrentUserId, background: BackgroundTasks):
    invite = await invites.resolve(db, token=req.invite_token)
    if invite is None:
        raise ApiError(404, "INVITE_INVALID", "더 이상 쓸 수 없는 초대 링크예요.")
    store_id = int(invite["store_id"])
    try:
        action = join_requests.decide_join(
            user_role=str(claims.get("role")),
            active_store_id=await active_store_id(db, user_id=user_id),
            invite_store_id=store_id)
    except join_requests.JoinRefused as exc:
        raise ApiError(exc.status, exc.code, _JOIN_MESSAGES[exc.code]) from exc
    if action == "ALREADY_MEMBER":
        return {"status": "ALREADY_MEMBER", "store_name": invite["store_name"]}
    name = await db.fetchval("select name from users where user_id = $1", user_id)
    _, notification_id = await join_requests.request_join(
        db, store_id=store_id, user_id=user_id,
        invite_id=int(invite["invite_id"]), staff_name=name)
    if notification_id is not None:
        # 커밋 뒤에 보내야 알림 행이 보인다
        background.add_task(deliver_notification, store_id, notification_id)
    return {"status": "PENDING", "store_name": invite["store_name"]}


# store-isolation-ok: 매장 소속 전 알바가 자기 요청 상태만 본다
@router.get("/join-status")
async def join_status(db: Db, user_id: CurrentUserId):
    return await join_requests.latest_status(db, user_id=user_id)
```

  `Claims`·`CurrentUserId`는 이미 import돼 있다(`app.deps`).

- [ ] **Step 6: 통과 확인** — `.venv/bin/python -m pytest tests/test_members.py tests/test_notifications.py -q` → PASS.

---

### Task 6A: 역할 미정 계정과 가입 직후 역할 선택

결정(2026-10-03): 로그인 화면은 하나다(역할 선택 화면 없음). 기존 계정은 역할과 상관없이 바로 로그인하고, 새 계정은 가입 직후 "사장님이에요 / 알바생이에요"를 **한 번** 고른다. 초대 링크로 온 사람은 자동으로 알바가 된다.

**Files:**
- Modify: `api/app/auth/router.py` (`LoginRequest`·`login`, `SignupRequest`·`signup`, 새 `POST /role`), `api/app/auth/session.py` (`create_access_token` role None)
- Modify: `api/app/bootstrap/router.py`, `api/app/bootstrap/schemas.py`
- Modify: `api/app/auth/router.py` `create_join_request` (역할 미정이면 STAFF로 확정 후 요청)
- Test: `api/tests/test_auth_role.py` (신규)

**Interfaces:**
- Consumes: Task 1 `users.role` nullable, Task 3 `session_payload`·`start_session`, Task 6 `create_join_request`
- Produces:
  - `create_access_token(*, user_id: int, role: str | None, store_id: int | None)` — role이 None이면 claim을 넣지 않는다
  - `POST /auth/login` `{email, password, role?}` — `role`은 받기만 하고 무시(구버전 웹 호환). 역할 일치 검사 제거
  - `POST /auth/signup` `{name, email, password, role?, phone?}` — `role` 없으면 역할 미정 계정
  - `POST /auth/role` `{role: "OWNER" | "STAFF"}` → `session_payload` 모양 `{token, user}`. 이미 역할이 있으면 409 `ROLE_ALREADY_SET`
  - `/app/bootstrap`: 역할 미정 → `user.role = null`, `default_destination = "/auth/role"`
  - `async set_role_if_unset(db, *, user_id: int, role: str) -> bool` (`auth/router.py` 내부, 바꿨으면 True)

- [ ] **Step 1: 실패하는 테스트 작성** — `api/tests/test_auth_role.py`

```python
"""역할 미정 계정과 역할 선택 (이슈 #37)."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import router as auth_router_module
from app.auth import session
from app.bootstrap.router import _default_destination
from app.deps import create_token, get_db
from app.errors import install_error_handlers

SETTINGS = SimpleNamespace(jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256",
                           access_token_expire_minutes=60, refresh_token_expire_days=90,
                           auth_cookie_secure=True, origins=["https://askbuddy.kr"])


def bearer(**claims):
    claims.setdefault("exp", datetime.now(timezone.utc) + timedelta(minutes=5))
    return {"Authorization": "Bearer " + create_token(claims)}


class RoleDb:
    def __init__(self):
        self.users = {5: {"user_id": 5, "name": "새사람", "role": None}}

    async def fetchval(self, sql, *args):
        if sql.lstrip().startswith("update users set role"):
            user = self.users.get(args[0])
            if user and user["role"] is None:
                user["role"] = args[1]
                return args[0]
            return None
        if "from store_members" in sql:
            return None
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if "from users where user_id" in sql:
            return self.users.get(args[0])
        raise AssertionError(sql)


class RoleSelectTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.deps.get_settings", "app.auth.session.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        self.db = RoleDb()
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(auth_router_module.router, prefix="/auth")

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)

    def test_unset_token_has_no_role_claim(self):
        claims = jwt.decode(session.create_access_token(user_id=5, role=None, store_id=None),
                            SETTINGS.jwt_secret, algorithms=["HS256"])
        self.assertNotIn("role", claims)

    def test_choose_owner_once(self):
        res = self.client.post("/auth/role", json={"role": "OWNER"}, headers=bearer(user_id=5))
        self.assertEqual(res.status_code, 200)
        claims = jwt.decode(res.json()["token"], SETTINGS.jwt_secret, algorithms=["HS256"])
        self.assertEqual(claims["role"], "OWNER")
        again = self.client.post("/auth/role", json={"role": "STAFF"}, headers=bearer(user_id=5, role="OWNER"))
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["error"]["code"], "ROLE_ALREADY_SET")
        self.assertEqual(self.db.users[5]["role"], "OWNER")

    def test_rejects_other_roles(self):
        res = self.client.post("/auth/role", json={"role": "OPERATOR"}, headers=bearer(user_id=5))
        self.assertEqual(res.status_code, 422)

    def test_bootstrap_destination_for_unset_role(self):
        self.assertEqual(_default_destination(None, False, False), "/auth/role")
        self.assertEqual(_default_destination("STAFF", False, False), "/staff/pending")
        self.assertEqual(_default_destination("OWNER", False, False), "/owner/intent")
```

  로그인 역할 검사 제거는 이메일 로그인 가짜 DB가 필요하다. 같은 파일에

```python
class LoginWithoutRoleTest(unittest.TestCase):
    def setUp(self):
        import bcrypt
        for target in ("app.deps.get_settings", "app.auth.session.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        hashed = bcrypt.hashpw(b"secret1", bcrypt.gensalt(rounds=4)).decode()

        class Db:
            async def fetchrow(self, sql, *args):
                if "from users u" in sql:
                    return {"user_id": 7, "name": "알바", "email": args[0], "role": "STAFF",
                            "password_hash": hashed, "store_id": 3}
                raise AssertionError(sql)

        async def start_session(db, response, *, user_id):
            response.set_cookie("ab_refresh", "x")

        q = patch("app.auth.router.start_session", side_effect=start_session)
        q.start()
        self.addCleanup(q.stop)
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(auth_router_module.router, prefix="/auth")
        db = Db()

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)

    def test_login_without_role(self):
        res = self.client.post("/auth/login", json={"email": "a@example.com", "password": "secret1"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user"]["role"], "STAFF")

    def test_old_web_sending_wrong_role_still_logs_in(self):
        # 단일 로그인 화면이라 역할로 막지 않는다. 역할은 DB 값이 정한다
        res = self.client.post("/auth/login", json={"email": "a@example.com", "password": "secret1", "role": "OWNER"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user"]["role"], "STAFF")
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_auth_role.py -q` → FAIL.

- [ ] **Step 3: 구현**
  - `session.create_access_token`: 시그니처 `role: str | None`, `payload`에서 `"role"`을 빼고 `if role is not None: payload["role"] = role`. `session_payload`의 `out_user["role"]`은 None 그대로 둔다.
  - `LoginRequest.role`: `role: str | None = Field(default=None, pattern="^(OWNER|STAFF)$")`. `login`의 `if row["role"] != req.role: raise ...` 두 줄과 그 위 주석을 지운다. 독스트링 `"""단일 로그인 화면. 역할은 DB 값이 정한다."""`.
  - `SignupRequest.role`: 같은 방식으로 Optional. `signup` insert의 `$5`에 `req.role`(None 가능)을 넘긴다. 응답 `user.role`도 None 가능.
  - 추가:

```python
class RoleRequest(BaseModel):
    role: Literal["OWNER", "STAFF"]


# store-isolation-ok: 역할은 사용자 단위다. 아직 매장이 없다
async def set_role_if_unset(db, *, user_id: int, role: str) -> bool:
    changed = await db.fetchval(
        "update users set role = $2 where user_id = $1 and role is null returning user_id",
        user_id, role)
    return changed is not None


# store-isolation-ok: 가입 직후 한 번 역할을 고른다. 매장은 아직 없다
@router.post("/role")
async def choose_role(req: RoleRequest, db: Db, user_id: CurrentUserId):
    if not await set_role_if_unset(db, user_id=user_id, role=req.role):
        raise ApiError(409, "ROLE_ALREADY_SET", "이미 역할을 골랐어요.")
    return await session_payload(db, user_id=user_id)
```

    `from typing import Literal` import.
  - `create_join_request`(Task 6): `decide_join` 호출 전에

```python
    role = claims.get("role")
    if role is None:
        # 역할을 고르기 전에 초대 링크를 열었다. 링크로 왔으니 알바로 정한다
        await set_role_if_unset(db, user_id=user_id, role="STAFF")
        role = "STAFF"
```

    로 바꾸고 `decide_join(user_role=str(role), ...)`. 응답 이후 웹은 `/auth/refresh`로 role이 든 토큰을 다시 받는다(Task 13).
  - `bootstrap/schemas.py`: `role: Literal["OWNER", "STAFF"] | None`.
  - `bootstrap/router.py` `_default_destination(role: str | None, ...)` 맨 앞에 `if role is None: return "/auth/role"`. `claims.get("role") != user["role"]` 비교는 둘 다 None이면 통과하므로 그대로 둔다.

- [ ] **Step 4: 통과 확인** — `.venv/bin/python -m pytest tests/test_auth_role.py tests/test_members.py tests/test_bootstrap.py -q` → PASS.

---

### Task 7: 직원 목록·승인·거절·내보내기

**Files:**
- Create: `api/app/members/repository.py`
- Modify: `api/app/members/router.py`, `api/app/notifications/service.py`
- Test: `api/tests/test_members.py` (클래스 추가)

결정(2026-10-03): 점주가 승인하면 알바에게 **바로** 알림이 가고 바로 쓸 수 있다. 승인 트랜잭션에서 `store_members`를 만든 직후 알바 알림 행을 만들고, 커밋 뒤 Web Push를 보낸다.

**Interfaces:**
- Consumes: `OwnerStoreId`, `revoke_user_sessions`
- Produces:
  - `class AlreadyDecided(Exception)`, `class CannotRemoveOwner(Exception)`
  - `async repository.list_members(db, *, store_id: int) -> dict` — `{"pending": [{request_id, name, requested_at}], "active": [{user_id, name, role, joined_at}]}`
  - `async repository.approve(db, *, store_id: int, request_id: int, owner_id: int) -> tuple[int, int | None]` — (승인된 user_id, 알바에게 만든 알림 id). 없으면 `LookupError`, 처리됨 `AlreadyDecided`
  - `async create_join_approved_notification(db, *, store_id: int, request_id: int, staff_user_id: int) -> int | None` (`notifications/service.py`)
  - `async repository.reject(db, *, store_id: int, request_id: int, owner_id: int) -> None`
  - `async repository.remove(db, *, store_id: int, user_id: int, owner_id: int) -> None`
  - `GET /members`, `POST /members/requests/{request_id}/approve|reject` → 204, `POST /members/{user_id}/remove` → 204

- [ ] **Step 1: 실패하는 테스트 추가** — 라우터는 저장소를 가짜로 바꿔 상태 코드 계약을 고정하고, SQL은 Task 10 로컬 실측으로 확인한다.

```python
from app.members import repository


class MembersApiTest(unittest.TestCase):
    def setUp(self):
        p = patch("app.deps.get_settings", return_value=SETTINGS)
        p.start()
        self.addCleanup(p.stop)
        self.revoked = []
        self.delivered = []

        class Db:
            async def fetchrow(self, sql, *args):
                return {"member_role": "OWNER" if args[1] == 1 else "STAFF"}

        async def approve(db, *, store_id, request_id, owner_id):
            if request_id == 404:
                raise LookupError
            if request_id == 409:
                raise repository.AlreadyDecided
            return 5, 21

        async def deliver(store_id, notification_id):
            self.delivered.append((store_id, notification_id))

        async def remove(db, *, store_id, user_id, owner_id):
            if user_id == owner_id:
                raise repository.CannotRemoveOwner
            if user_id == 404:
                raise LookupError

        async def revoke(db, *, user_id):
            self.revoked.append(user_id)

        for target, fn in (("app.members.router.repository.approve", approve),
                           ("app.members.router.repository.remove", remove),
                           ("app.members.router.revoke_user_sessions", revoke),
                           ("app.members.router.deliver_notification", deliver)):
            q = patch(target, side_effect=fn)
            q.start()
            self.addCleanup(q.stop)
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(members_router_module.router, prefix="/members")
        db = Db()

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)
        self.owner = bearer(user_id=1, store_id=1, role="OWNER")

    def test_approve_status_codes(self):
        self.assertEqual(self.client.post("/members/requests/1/approve", headers=self.owner).status_code, 204)
        # 승인 알림은 응답 뒤 알바 기기로 보낸다
        self.assertEqual(self.delivered, [(1, 21)])
        self.assertEqual(self.client.post("/members/requests/404/approve", headers=self.owner).status_code, 404)
        self.assertEqual(self.client.post("/members/requests/409/approve", headers=self.owner).status_code, 409)

    def test_remove_revokes_sessions(self):
        self.assertEqual(self.client.post("/members/5/remove", headers=self.owner).status_code, 204)
        self.assertEqual(self.revoked, [5])

    def test_owner_cannot_remove_self(self):
        res = self.client.post("/members/1/remove", headers=self.owner)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.revoked, [])

    def test_unknown_member_404(self):
        self.assertEqual(self.client.post("/members/404/remove", headers=self.owner).status_code, 404)

    def test_staff_forbidden(self):
        staff = bearer(user_id=5, store_id=1, role="STAFF")
        self.assertEqual(self.client.post("/members/requests/1/approve", headers=staff).status_code, 403)
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_members.py -q` → FAIL(`ImportError: repository`).

- [ ] **Step 3a: 알바 승인 알림 함수** — `notifications/service.py`의 `create_join_request_notification` 아래

```python
async def create_join_approved_notification(
    db: asyncpg.Connection, *, store_id: int, request_id: int, staff_user_id: int,
) -> int | None:
    """승인된 알바에게 알린다. 승인 트랜잭션 안에서 멤버 행을 만든 뒤에 부른다."""
    store_name = await db.fetchval("select store_name from stores where store_id = $1", store_id)
    return await create_notification_event(
        db,
        store_id=store_id,
        recipient_user_id=staff_user_id,
        event_type="JOIN_APPROVED",
        aggregate_type="JOIN_REQUEST",
        aggregate_id=request_id,
        dedupe_key=f"join_approved:{request_id}",
        title="합류가 승인됐어요",
        body=f"{store_name}에서 바로 시작할 수 있어요.",
        destination="/staff/roadmap",
    )
```

  `destination`이 `/staff/`로 시작하므로 Task 1 migration의 destination 제약 완화가 필요하다.

- [ ] **Step 3: `repository.py` 구현**

```python
"""직원 목록·승인·거절·내보내기. 모든 쿼리는 store_id 로 좁힌다."""
from __future__ import annotations

from app.notifications.service import create_join_approved_notification


class AlreadyDecided(Exception):
    """이미 승인·거절된 요청이다."""


class CannotRemoveOwner(Exception):
    """점주 본인은 내보낼 수 없다."""


async def list_members(db, *, store_id: int) -> dict:
    pending = await db.fetch(
        """
        select r.request_id, u.name, r.requested_at
        from store_join_requests r join users u on u.user_id = r.user_id
        where r.store_id = $1 and r.status = 'PENDING'
        order by r.requested_at asc
        """,
        store_id)
    active = await db.fetch(
        """
        select m.user_id, u.name, m.member_role as role, m.joined_at
        from store_members m join users u on u.user_id = m.user_id
        where m.store_id = $1 and m.removed_at is null
        order by m.member_role = 'OWNER' desc, m.joined_at asc
        """,
        store_id)
    return {
        "pending": [{**dict(r), "requested_at": r["requested_at"].isoformat()} for r in pending],
        "active": [{**dict(r), "joined_at": r["joined_at"].isoformat()} for r in active],
    }


async def _decide(db, *, store_id: int, request_id: int, owner_id: int, status: str):
    row = await db.fetchrow(
        """
        select request_id, user_id, status from store_join_requests
        where store_id = $1 and request_id = $2 for update
        """,
        store_id, request_id)
    if row is None:
        raise LookupError(request_id)
    if row["status"] != "PENDING":
        raise AlreadyDecided(request_id)
    await db.execute(
        """
        update store_join_requests
        set status = $3, decided_at = now(), decided_by = $4
        where store_id = $1 and request_id = $2
        """,
        store_id, request_id, status, owner_id)
    return int(row["user_id"])


async def approve(db, *, store_id: int, request_id: int, owner_id: int) -> tuple[int, int | None]:
    async with db.transaction():
        user_id = await _decide(db, store_id=store_id, request_id=request_id,
                                owner_id=owner_id, status="APPROVED")
        # 내보냈던 직원이 다시 들어오면 같은 행을 되살린다. 학습 기록이 그대로 이어진다
        await db.execute(
            """
            insert into store_members (store_id, user_id, member_role, day_count, progress_rate, is_deployable)
            values ($1, $2, 'STAFF', 0, 0, false)
            on conflict (store_id, user_id)
            do update set removed_at = null, removed_by = null
            """,
            store_id, user_id)
        # 멤버 행이 생긴 뒤라 "수신자는 매장 멤버" FK 를 만족한다
        notification_id = await create_join_approved_notification(
            db, store_id=store_id, request_id=request_id, staff_user_id=user_id)
    return user_id, notification_id


async def reject(db, *, store_id: int, request_id: int, owner_id: int) -> None:
    async with db.transaction():
        await _decide(db, store_id=store_id, request_id=request_id,
                      owner_id=owner_id, status="REJECTED")


async def remove(db, *, store_id: int, user_id: int, owner_id: int) -> None:
    if user_id == owner_id:
        raise CannotRemoveOwner()
    updated = await db.fetchval(
        """
        update store_members set removed_at = now(), removed_by = $3
        where store_id = $1 and user_id = $2 and member_role = 'STAFF' and removed_at is null
        returning member_id
        """,
        store_id, user_id, owner_id)
    if updated is None:
        raise LookupError(user_id)
```

  다른 매장에 이미 활성 멤버십이 있는 사용자를 승인하면 단일 매장 전제가 깨진다. `approve`의 `_decide` 다음에

```python
        other = await db.fetchval(
            """
            select store_id from store_members
            where user_id = $1 and store_id <> $2 and removed_at is null limit 1
            """,
            user_id, store_id)
        if other is not None:
            raise AlreadyDecided(request_id)
```

  를 넣는다(이 조회는 매장 밖을 보므로 바로 위에 `# store-isolation-ok: 단일 매장 전제 확인. 다른 매장 id 는 밖으로 내보내지 않는다`).

- [ ] **Step 4: 라우터 추가** — `members/router.py`

```python
from fastapi import BackgroundTasks

from app.auth.session import revoke_user_sessions
from app.deps import CurrentUserId
from app.members import repository
from app.notifications.service import deliver_notification


@router.get("")
async def list_members(db: Db, store_id: OwnerStoreId):
    return await repository.list_members(db, store_id=store_id)


@router.post("/requests/{request_id}/approve", status_code=204)
async def approve_request(request_id: int, db: Db, store_id: OwnerStoreId, owner_id: CurrentUserId,
                          background: BackgroundTasks):
    try:
        _, notification_id = await repository.approve(
            db, store_id=store_id, request_id=request_id, owner_id=owner_id)
    except LookupError as exc:
        raise ApiError(404, "NOT_FOUND", "요청을 찾을 수 없어요.") from exc
    except repository.AlreadyDecided as exc:
        raise ApiError(409, "ALREADY_DECIDED", "이미 처리된 요청이에요.") from exc
    if notification_id is not None:
        background.add_task(deliver_notification, store_id, notification_id)


@router.post("/requests/{request_id}/reject", status_code=204)
async def reject_request(request_id: int, db: Db, store_id: OwnerStoreId, owner_id: CurrentUserId):
    try:
        await repository.reject(db, store_id=store_id, request_id=request_id, owner_id=owner_id)
    except LookupError as exc:
        raise ApiError(404, "NOT_FOUND", "요청을 찾을 수 없어요.") from exc
    except repository.AlreadyDecided as exc:
        raise ApiError(409, "ALREADY_DECIDED", "이미 처리된 요청이에요.") from exc


@router.post("/{user_id}/remove", status_code=204)
async def remove_member(user_id: int, db: Db, store_id: OwnerStoreId, owner_id: CurrentUserId):
    try:
        await repository.remove(db, store_id=store_id, user_id=user_id, owner_id=owner_id)
    except repository.CannotRemoveOwner as exc:
        raise ApiError(400, "CANNOT_REMOVE_OWNER", "사장님 본인은 내보낼 수 없어요.") from exc
    except LookupError as exc:
        raise ApiError(404, "NOT_FOUND", "직원을 찾을 수 없어요.") from exc
    await revoke_user_sessions(db, user_id=user_id)
```

  `test_members.py` 상단 `MembersApiTest`의 `Db`는 `list_members`를 쓰지 않으므로 그대로 둔다.

- [ ] **Step 5: 통과 확인** — `.venv/bin/python -m pytest tests/test_members.py -q` → PASS.

---

### Task 7A: 매장 없는 사용자도 Push 구독 (알바 승인 알림용)

`push_subscriptions`는 사용자 단위(`user_id`, `store_id` 없음)다. 지금 구독 API(`/notifications/subscriptions`)는 점주+매장 전용이라 승인 대기 중인 알바가 구독할 수 없다. 기존 API는 그대로 두고, 로그인 사용자 누구나 자기 기기를 등록하는 API를 추가한다.

**Files:**
- Modify: `api/app/notifications/router.py`
- Test: `api/tests/test_notifications.py` (클래스 추가)

**Interfaces:**
- Consumes: `CurrentUserId`, 기존 `SubscriptionRequest`·`_validate_subscription`·`push_is_configured`
- Produces:
  - `GET /notifications/push-key` → `{push_configured: bool, vapid_public_key: str | null}`
  - `POST /notifications/my-subscriptions` (body = 브라우저 `PushSubscriptionJSON`) → 201 `{subscription_id, enabled: true}`
  - `DELETE /notifications/my-subscriptions/{subscription_id}` → 204 (본인 것만, 아니면 404)

- [ ] **Step 1: 실패하는 테스트 추가** — `test_notifications.py` 끝에

```python
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import create_token, get_db
from app.errors import install_error_handlers
from app.notifications import router as notifications_router_module

PUSH_SETTINGS = SimpleNamespace(jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256",
                                vapid_public_key="pub-key", vapid_private_key="priv",
                                vapid_subject="mailto:ops@example.com")


class PersonalPushTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.deps.get_settings", "app.notifications.router.get_settings",
                       "app.notifications.service.get_settings"):
            p = patch(target, return_value=PUSH_SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        self.subs = {}

        class Db:
            async def fetchval(inner, sql, *args):
                if sql.lstrip().startswith("insert into push_subscriptions"):
                    sid = len(self.subs) + 1
                    self.subs[sid] = {"user_id": args[0], "endpoint": args[1]}
                    return sid
                if sql.lstrip().startswith("update push_subscriptions"):
                    sub = self.subs.get(args[0])
                    if sub and sub["user_id"] == args[1]:
                        sub["enabled"] = False
                        return args[0]
                    return None
                raise AssertionError(sql)

        app = FastAPI()
        install_error_handlers(app)
        app.include_router(notifications_router_module.router, prefix="/notifications")
        db = Db()

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)

    @staticmethod
    def bearer(**claims):
        claims.setdefault("exp", datetime.now(timezone.utc) + timedelta(minutes=5))
        return {"Authorization": "Bearer " + create_token(claims)}

    BODY = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "k" * 20, "auth": "a" * 10}}

    def test_storeless_staff_can_read_key_and_subscribe(self):
        staff = self.bearer(user_id=5, role="STAFF")
        self.assertEqual(self.client.get("/notifications/push-key", headers=staff).json(),
                         {"push_configured": True, "vapid_public_key": "pub-key"})
        res = self.client.post("/notifications/my-subscriptions", json=self.BODY, headers=staff)
        self.assertEqual(res.status_code, 201)
        self.assertEqual(self.subs[1]["user_id"], 5)

    def test_cannot_delete_someone_elses_subscription(self):
        self.client.post("/notifications/my-subscriptions", json=self.BODY, headers=self.bearer(user_id=5, role="STAFF"))
        other = self.bearer(user_id=6, role="STAFF")
        self.assertEqual(self.client.delete("/notifications/my-subscriptions/1", headers=other).status_code, 404)
        mine = self.bearer(user_id=5, role="STAFF")
        self.assertEqual(self.client.delete("/notifications/my-subscriptions/1", headers=mine).status_code, 204)

    def test_requires_login(self):
        self.assertEqual(self.client.get("/notifications/push-key").status_code, 401)
```

  `BODY`의 endpoint·키 형식이 기존 `_validate_subscription` 검사(허용 호스트·길이)를 통과하는지 `notifications/router.py:29`를 읽고 맞춘다.

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_notifications.py -q` → FAIL(404).

- [ ] **Step 3: 구현** — `notifications/router.py` 끝에

```python
# store-isolation-ok: 구독은 사용자 단위다. 매장 없는 알바도 승인 알림을 받아야 한다
@router.get("/push-key")
async def push_key(user_id: CurrentUserId) -> dict:
    settings = get_settings()
    return {
        "push_configured": push_is_configured(),
        "vapid_public_key": settings.vapid_public_key or None,
    }


# store-isolation-ok: 구독은 사용자 단위다(user_id 는 JWT)
@router.post("/my-subscriptions", status_code=201)
async def save_my_subscription(
    req: SubscriptionRequest,
    db: Db,
    user_id: CurrentUserId,
    user_agent: str | None = Header(default=None, alias="User-Agent"),
) -> dict:
    _validate_subscription(req)
    subscription_id = await db.fetchval(
        """
        insert into push_subscriptions (user_id, endpoint, p256dh, auth, user_agent, enabled)
        values ($1,$2,$3,$4,$5,true)
        on conflict (user_id, endpoint) do update
        set p256dh = excluded.p256dh, auth = excluded.auth,
            user_agent = excluded.user_agent, enabled = true, updated_at = now()
        returning subscription_id
        """,
        user_id, req.endpoint, req.keys.p256dh, req.keys.auth, (user_agent or "")[:500] or None)
    return {"subscription_id": int(subscription_id), "enabled": True}


# store-isolation-ok: 본인 구독만 끈다
@router.delete("/my-subscriptions/{subscription_id}", status_code=204)
async def delete_my_subscription(subscription_id: int, db: Db, user_id: CurrentUserId) -> None:
    updated = await db.fetchval(
        """
        update push_subscriptions set enabled = false, updated_at = now()
        where subscription_id = $1 and user_id = $2 returning subscription_id
        """,
        subscription_id, user_id)
    if updated is None:
        raise ApiError(404, "NOT_FOUND", "구독을 찾을 수 없어요.")
```

- [ ] **Step 4: 통과 확인** — `.venv/bin/python -m pytest tests/test_notifications.py -q` → PASS.

---

### Task 8: 카카오 클라이언트와 OAuth state

**Files:**
- Create: `api/app/auth/oauth_state.py`, `api/app/auth/kakao.py`
- Test: `api/tests/test_kakao_auth.py`

**Interfaces:**
- Produces:
  - `oauth_state.OAUTH_COOKIE = "ab_oauth"`, `INTENTS = ("LOGIN", "STAFF_JOIN")`
  - `@dataclass(frozen=True) OAuthState(state: str, verifier: str, intent: str, invite_id: int | None, next: str | None)`
  - `encode_state(s: OAuthState) -> str`, `decode_state(token: str) -> OAuthState` (실패 시 `InvalidState`)
  - `safe_next(value: str | None) -> str | None`
  - `kakao.is_configured() -> bool`, `kakao.pkce_pair() -> tuple[str, str]`, `kakao.authorize_url(*, state: str, code_challenge: str) -> str`
  - `@dataclass(frozen=True) KakaoUser(id: str, nickname: str | None)`
  - `async kakao.fetch_user(*, code: str, code_verifier: str, transport: httpx.AsyncBaseTransport | None = None) -> KakaoUser` (실패 `KakaoError`)

- [ ] **Step 1: 실패하는 테스트 작성** — `api/tests/test_kakao_auth.py`

```python
"""카카오 로그인 (이슈 #37). 카카오 서버는 httpx.MockTransport 로 흉내 낸다."""
import asyncio
import base64
import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx

from app.auth import kakao, oauth_state

SETTINGS = SimpleNamespace(
    jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256",
    kakao_rest_api_key="rest-key", kakao_client_secret="secret",
    kakao_redirect_uri="https://api.askbuddy.kr/auth/kakao/callback",
    web_base_url="https://askbuddy.kr", auth_cookie_secure=True,
    access_token_expire_minutes=60, refresh_token_expire_days=90,
    origins=["https://askbuddy.kr"])


class StateTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.deps.get_settings", "app.auth.oauth_state.get_settings",
                       "app.auth.kakao.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)

    def test_state_round_trip(self):
        s = oauth_state.OAuthState("st", "ver", "STAFF_JOIN", 9, "/staff/roadmap")
        self.assertEqual(oauth_state.decode_state(oauth_state.encode_state(s)), s)

    def test_state_rejects_tamper_and_product_token(self):
        from app.deps import create_token
        token = oauth_state.encode_state(oauth_state.OAuthState("st", "ver", "OWNER", None, None))
        with self.assertRaises(oauth_state.InvalidState):
            oauth_state.decode_state(token[:-2] + "xx")
        product = create_token({"user_id": 1, "role": "OWNER", "exp": 9999999999})
        with self.assertRaises(oauth_state.InvalidState):
            oauth_state.decode_state(product)

    def test_state_token_rejected_by_product_api(self):
        from fastapi import HTTPException
        from app.deps import get_claims
        token = oauth_state.encode_state(oauth_state.OAuthState("st", "ver", "OWNER", None, None))
        with self.assertRaises(HTTPException):
            asyncio.run(get_claims("Bearer " + token))

    def test_safe_next_whitelist(self):
        self.assertEqual(oauth_state.safe_next("/owner/cards?x=1"), "/owner/cards?x=1")
        self.assertEqual(oauth_state.safe_next("/staff/roadmap"), "/staff/roadmap")
        for bad in ("//evil.com", "https://evil.com", "/ownerx", "/role", "/owner/\\evil", None, ""):
            self.assertIsNone(oauth_state.safe_next(bad), bad)

    def test_authorize_url_has_pkce_and_state(self):
        verifier, challenge = kakao.pkce_pair()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)
        q = parse_qs(urlparse(kakao.authorize_url(state="st", code_challenge=challenge)).query)
        self.assertEqual(q["client_id"], ["rest-key"])
        self.assertEqual(q["response_type"], ["code"])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["state"], ["st"])
        self.assertEqual(q["redirect_uri"], [SETTINGS.kakao_redirect_uri])


class FetchUserTest(unittest.TestCase):
    def setUp(self):
        p = patch("app.auth.kakao.get_settings", return_value=SETTINGS)
        p.start()
        self.addCleanup(p.stop)

    def test_exchange_sends_secret_and_verifier(self):
        seen = {}

        def handler(request: httpx.Request):
            if request.url.path == "/oauth/token":
                seen["form"] = parse_qs(request.content.decode())
                return httpx.Response(200, json={"access_token": "kat"})
            seen["auth"] = request.headers["authorization"]
            return httpx.Response(200, json={"id": 123, "kakao_account": {"profile": {"nickname": "닉"}}})

        user = asyncio.run(kakao.fetch_user(code="c", code_verifier="v",
                                            transport=httpx.MockTransport(handler)))
        self.assertEqual(user, kakao.KakaoUser("123", "닉"))
        self.assertEqual(seen["form"]["client_secret"], ["secret"])
        self.assertEqual(seen["form"]["code_verifier"], ["v"])
        self.assertEqual(seen["form"]["grant_type"], ["authorization_code"])
        self.assertEqual(seen["auth"], "Bearer kat")

    def test_token_error_raises(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
        with self.assertRaises(kakao.KakaoError):
            asyncio.run(kakao.fetch_user(code="c", code_verifier="v", transport=transport))
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_kakao_auth.py -q` → FAIL(`ImportError`).

- [ ] **Step 3: `oauth_state.py` 구현**

```python
"""카카오 왕복 동안 state·PKCE verifier 를 서명 쿠키에 담는다. 서버 테이블이 필요 없다.

aud 가 있어 제품 API(get_claims, audience 미지정)는 이 토큰을 받아주지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings

OAUTH_COOKIE = "ab_oauth"
OAUTH_COOKIE_PATH = "/auth/kakao"
_AUD = "askbuddy-oauth"
_TTL = timedelta(minutes=10)
INTENTS = ("LOGIN", "STAFF_JOIN")
# /owner/... 또는 /staff/... 상대 경로만. 역슬래시·스킴·이중 슬래시를 막는다
_NEXT = re.compile(r"^/(owner|staff)(/[A-Za-z0-9_\-/.?=&%]*)?$")


class InvalidState(Exception):
    pass


@dataclass(frozen=True)
class OAuthState:
    state: str
    verifier: str
    intent: str
    invite_id: int | None
    next: str | None


def safe_next(value: str | None) -> str | None:
    if not value or not _NEXT.match(value):
        return None
    return value


def encode_state(s: OAuthState) -> str:
    st = get_settings()
    payload = {**asdict(s), "aud": _AUD, "exp": datetime.now(timezone.utc) + _TTL}
    return jwt.encode(payload, st.jwt_secret, algorithm=st.jwt_algorithm)


def decode_state(token: str) -> OAuthState:
    st = get_settings()
    try:
        data = jwt.decode(token, st.jwt_secret, algorithms=[st.jwt_algorithm],
                          audience=_AUD, options={"require": ["exp", "aud"]})
        return OAuthState(data["state"], data["verifier"], data["intent"],
                          data.get("invite_id"), data.get("next"))
    except (jwt.PyJWTError, KeyError) as exc:
        raise InvalidState() from exc
```

- [ ] **Step 4: `kakao.py` 구현**

```python
"""카카오 로그인 REST 호출 (이슈 #37).

PKCE S256·client_secret_post 지원은 https://kauth.kakao.com/.well-known/openid-configuration 에서
확인했다(2026-10-03). 카카오 access token 은 사용자 조회에만 쓰고 저장하지 않는다.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
USER_URL = "https://kapi.kakao.com/v2/user/me"
_TIMEOUT = httpx.Timeout(5.0)


class KakaoError(Exception):
    pass


@dataclass(frozen=True)
class KakaoUser:
    id: str
    nickname: str | None


def is_configured() -> bool:
    s = get_settings()
    return bool(s.kakao_rest_api_key and s.kakao_client_secret and s.kakao_redirect_uri)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(*, state: str, code_challenge: str) -> str:
    s = get_settings()
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": s.kakao_rest_api_key,
        "redirect_uri": s.kakao_redirect_uri,
        "response_type": "code",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })


async def fetch_user(*, code: str, code_verifier: str,
                     transport: httpx.AsyncBaseTransport | None = None) -> KakaoUser:
    s = get_settings()
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
            token = await client.post(TOKEN_URL, data={
                "grant_type": "authorization_code",
                "client_id": s.kakao_rest_api_key,
                "client_secret": s.kakao_client_secret,
                "redirect_uri": s.kakao_redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            })
            if token.status_code != 200:
                raise KakaoError(f"token {token.status_code}")
            access = token.json()["access_token"]
            me = await client.get(USER_URL, headers={"Authorization": f"Bearer {access}"})
            if me.status_code != 200:
                raise KakaoError(f"user {me.status_code}")
            data = me.json()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise KakaoError(type(exc).__name__) from exc
    finally:
        logger.info("kakao login exchange %.0fms", (time.monotonic() - started) * 1000)
    nickname = (data.get("kakao_account") or {}).get("profile", {}).get("nickname")
    return KakaoUser(str(data["id"]), nickname)
```

- [ ] **Step 5: 통과 확인** — `.venv/bin/python -m pytest tests/test_kakao_auth.py -q` → PASS.

---

### Task 9: 카카오 계정 판정과 start·callback 엔드포인트

**Files:**
- Create: `api/app/auth/kakao_accounts.py`, `api/app/auth/kakao_router.py`
- Modify: `api/app/main.py`
- Test: `api/tests/test_kakao_auth.py` (클래스 추가)

**Interfaces:**
- Consumes: Task 3 `start_session`, Task 5 `invites.resolve`·`resolve_by_id`, Task 6 `join_requests.decide_join`·`request_join`·`JoinRefused`, Task 8 전체
- Produces:
  - `class AuthFlowError(Exception)` (`.code`)
  - `decide(*, intent: str, user_role: str | None, active_store_id: int | None, invite_store_id: int | None) -> str` — `"LOGIN" | "CREATE_UNSET" | "CREATE_STAFF_AND_REQUEST" | "SET_STAFF_AND_REQUEST" | "REQUEST"`, 실패 시 `AuthFlowError`
  - `async complete_kakao_login(db, *, kakao_user: KakaoUser, intent: str, invite: dict | None) -> tuple[int, int | None]` — (user_id, 점주 알림 notification_id)
  - `GET /auth/providers` → `{"kakao": bool}`; `GET /auth/kakao/start`; `GET /auth/kakao/callback`

- [ ] **Step 1: 실패하는 테스트 추가** — 판정표 전체와 엔드포인트 리다이렉트를 고정한다.

```python
from app.auth.kakao_accounts import AuthFlowError, decide


ACTIONS = {"LOGIN", "CREATE_UNSET", "CREATE_STAFF_AND_REQUEST", "SET_STAFF_AND_REQUEST", "REQUEST"}


class DecideTest(unittest.TestCase):
    def check(self, expected, **kw):
        base = dict(user_exists=False, user_role=None, active_store_id=None, invite_store_id=None)
        if kw.get("user_role") is not None:
            base["user_exists"] = True
        base.update(kw)
        if expected in ACTIONS:
            self.assertEqual(decide(**base), expected)
        else:
            with self.assertRaises(AuthFlowError) as ctx:
                decide(**base)
            self.assertEqual(ctx.exception.code, expected)

    def test_login_intent(self):
        # 단일 로그인 화면: 기존 계정은 역할과 상관없이 로그인, 새 계정은 역할 미정으로 만든다
        self.check("CREATE_UNSET", intent="LOGIN")
        for role in ("OWNER", "STAFF", None):
            self.check("LOGIN", intent="LOGIN", user_exists=True, user_role=role)

    def test_staff_join_intent(self):
        self.check("INVITE_INVALID", intent="STAFF_JOIN", invite_store_id=None)
        self.check("CREATE_STAFF_AND_REQUEST", intent="STAFF_JOIN", invite_store_id=1)
        # 역할을 아직 안 고른 계정이 링크로 왔다 → 알바로 정하고 요청
        self.check("SET_STAFF_AND_REQUEST", intent="STAFF_JOIN", user_exists=True, invite_store_id=1)
        self.check("ROLE_CONFLICT", intent="STAFF_JOIN", user_role="OWNER", invite_store_id=1)
        self.check("LOGIN", intent="STAFF_JOIN", user_role="STAFF", active_store_id=1, invite_store_id=1)
        self.check("ALREADY_IN_OTHER_STORE", intent="STAFF_JOIN", user_role="STAFF",
                   active_store_id=2, invite_store_id=1)
        self.check("REQUEST", intent="STAFF_JOIN", user_role="STAFF", invite_store_id=1)


from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import kakao_router as kakao_router_module
from app.deps import get_db
from app.errors import install_error_handlers


class KakaoRouteTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.deps.get_settings", "app.auth.oauth_state.get_settings",
                       "app.auth.kakao.get_settings", "app.auth.kakao_router.get_settings",
                       "app.auth.session.get_settings", "app.members.invites.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        self.completed = []

        async def resolve(db, *, token):
            return {"invite_id": 9, "store_id": 1, "store_name": "테스트카페"} if token == "good" else None

        async def resolve_by_id(db, *, invite_id):
            return {"invite_id": 9, "store_id": 1, "store_name": "테스트카페"} if invite_id == 9 else None

        async def fetch_user(*, code, code_verifier):
            if code == "boom":
                raise kakao.KakaoError("x")
            # 점주 계정으로 초대 링크를 연 경우를 흉내 낸다
            return kakao.KakaoUser("999" if code == "owner" else "123", "닉")

        async def complete(db, *, kakao_user, intent, invite):
            if kakao_user.id == "999":
                raise AuthFlowError("ROLE_CONFLICT")
            self.completed.append((kakao_user.id, intent, invite))
            return 5, None

        async def start_session(db, response, *, user_id):
            response.set_cookie("ab_refresh", "r", path="/auth")

        for target, fn in (("app.auth.kakao_router.invites.resolve", resolve),
                           ("app.auth.kakao_router.invites.resolve_by_id", resolve_by_id),
                           ("app.auth.kakao_router.kakao.fetch_user", fetch_user),
                           ("app.auth.kakao_router.complete_kakao_login", complete),
                           ("app.auth.kakao_router.start_session", start_session)):
            q = patch(target, side_effect=fn)
            q.start()
            self.addCleanup(q.stop)
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(kakao_router_module.router, prefix="/auth")

        async def fake_db():
            yield object()

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app, base_url="https://api.askbuddy.kr", follow_redirects=False)

    def start(self, **params):
        return self.client.get("/auth/kakao/start", params=params)

    def callback(self, start_res, code="ok", state=None, **extra):
        q = parse_qs(urlparse(start_res.headers["location"]).query)
        params = {"code": code, "state": state or q["state"][0], **extra}
        return self.client.get("/auth/kakao/callback", params=params)

    def test_providers(self):
        self.assertEqual(self.client.get("/auth/providers").json(), {"kakao": True})

    def test_start_redirects_to_kakao_and_sets_state_cookie(self):
        res = self.start(intent="LOGIN")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers["location"].startswith("https://kauth.kakao.com/oauth/authorize?"))
        self.assertIn("ab_oauth=", res.headers["set-cookie"])
        self.assertIn("Path=/auth/kakao", res.headers["set-cookie"])

    def test_start_rejects_unknown_intent_and_bad_invite(self):
        self.assertEqual(self.start(intent="OWNER").status_code, 422)
        res = self.start(intent="STAFF_JOIN", invite="bad")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=INVITE_INVALID")

    def test_full_owner_flow(self):
        res = self.callback(self.start(intent="LOGIN", next="/owner/cards"))
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?next=%2Fowner%2Fcards")
        cookies = res.headers.get_list("set-cookie")
        self.assertTrue(any(c.startswith("ab_refresh=") for c in cookies))
        self.assertTrue(any(c.startswith('ab_oauth=""') for c in cookies))
        self.assertEqual(self.completed, [("123", "LOGIN", None)])

    def test_join_passes_invite_from_cookie_not_query(self):
        self.callback(self.start(intent="STAFF_JOIN", invite="good"))
        self.assertEqual(self.completed[0][2]["invite_id"], 9)

    def test_state_mismatch_creates_nothing(self):
        res = self.callback(self.start(intent="LOGIN"), state="forged")
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=OAUTH_STATE_INVALID")
        self.assertEqual(self.completed, [])

    def test_missing_state_cookie(self):
        start_res = self.start(intent="LOGIN")
        self.client.cookies.clear()
        res = self.callback(start_res)
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=OAUTH_STATE_INVALID")

    def test_user_cancel(self):
        start_res = self.start(intent="LOGIN")
        q = parse_qs(urlparse(start_res.headers["location"]).query)
        res = self.client.get("/auth/kakao/callback", params={"error": "access_denied", "state": q["state"][0]})
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=KAKAO_CANCELLED")

    def test_kakao_failure_and_flow_error(self):
        res = self.callback(self.start(intent="LOGIN"), code="boom")
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=KAKAO_FAILED")
        res = self.callback(self.start(intent="STAFF_JOIN", invite="good"), code="owner")
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete?error=ROLE_CONFLICT")

    def test_open_redirect_next_dropped(self):
        res = self.callback(self.start(intent="LOGIN", next="//evil.com"))
        self.assertEqual(res.headers["location"], "https://askbuddy.kr/auth/complete")

    def test_not_configured(self):
        with patch("app.auth.kakao_router.kakao.is_configured", return_value=False):
            self.assertEqual(self.client.get("/auth/providers").json(), {"kakao": False})
            res = self.start(intent="LOGIN")
            self.assertEqual(res.status_code, 302)
            self.assertEqual(res.headers["location"],
                             "https://askbuddy.kr/auth/complete?error=KAKAO_NOT_CONFIGURED")
```

  `test_start_rejects_unknown_intent_and_bad_invite`의 422는 `intent`를 `Literal`로 받아 FastAPI가 검증한다는 뜻이다.

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_kakao_auth.py -q` → FAIL(`ImportError: kakao_accounts`).

- [ ] **Step 3: `kakao_accounts.py` 구현**

```python
"""카카오 계정을 AskBuddy 계정에 잇는다. 판정은 순수 함수, DB 처리는 그 결과만 따른다."""
from __future__ import annotations

import asyncpg

from app.auth.kakao import KakaoUser
from app.members import join_requests
from app.members.join_requests import JoinRefused, decide_join

_FALLBACK_NAME = "카카오 사용자"


class AuthFlowError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def decide(*, intent: str, user_exists: bool, user_role: str | None, active_store_id: int | None,
           invite_store_id: int | None) -> str:
    if intent == "LOGIN":
        # 단일 로그인 화면. 새 계정은 역할을 비워 두고 가입 직후 고르게 한다
        return "LOGIN" if user_exists else "CREATE_UNSET"
    # STAFF_JOIN — 초대 링크로 왔으니 알바다
    if invite_store_id is None:
        raise AuthFlowError("INVITE_INVALID")
    if not user_exists:
        return "CREATE_STAFF_AND_REQUEST"
    if user_role is None:
        return "SET_STAFF_AND_REQUEST"
    try:
        action = decide_join(user_role=user_role, active_store_id=active_store_id,
                             invite_store_id=invite_store_id)
    except JoinRefused as exc:
        raise AuthFlowError(exc.code) from exc
    return "LOGIN" if action == "ALREADY_MEMBER" else "REQUEST"


async def _find(db, kakao_id: str):
    return await db.fetchrow(
        """
        select u.user_id, u.role, u.name from user_identities i join users u on u.user_id = i.user_id
        where i.provider = 'KAKAO' and i.provider_user_id = $1
        """,
        kakao_id)


async def _create_user(db, *, kakao_user: KakaoUser, role: str | None) -> dict:
    name = (kakao_user.nickname or _FALLBACK_NAME).strip()[:50] or _FALLBACK_NAME
    user = await db.fetchrow(
        "insert into users (name, role) values ($1, $2) returning user_id, role, name", name, role)
    await db.execute(
        "insert into user_identities (user_id, provider, provider_user_id) values ($1, 'KAKAO', $2)",
        user["user_id"], kakao_user.id)
    return dict(user)


# store-isolation-ok: 로그인 시점이라 아직 매장 범위가 없다. 초대 매장은 서버가 토큰으로 찾은 값이다
async def complete_kakao_login(db, *, kakao_user: KakaoUser, intent: str,
                               invite: dict | None) -> tuple[int, int | None]:
    for attempt in range(2):
        try:
            async with db.transaction():
                user = await _find(db, kakao_user.id)
                active = None
                if user is not None:
                    active = await db.fetchval(
                        """
                        select store_id from store_members
                        where user_id = $1 and removed_at is null order by member_id limit 1
                        """,
                        user["user_id"])
                action = decide(
                    intent=intent,
                    user_exists=user is not None,
                    user_role=user["role"] if user else None,
                    active_store_id=int(active) if active is not None else None,
                    invite_store_id=int(invite["store_id"]) if invite else None)
                notification_id = None
                if action == "CREATE_UNSET":
                    user = await _create_user(db, kakao_user=kakao_user, role=None)
                elif action in ("CREATE_STAFF_AND_REQUEST", "SET_STAFF_AND_REQUEST", "REQUEST"):
                    if action == "CREATE_STAFF_AND_REQUEST":
                        user = await _create_user(db, kakao_user=kakao_user, role="STAFF")
                    elif action == "SET_STAFF_AND_REQUEST":
                        await db.execute(
                            "update users set role = 'STAFF' where user_id = $1 and role is null",
                            user["user_id"])
                    _, notification_id = await join_requests.request_join(
                        db, store_id=int(invite["store_id"]), user_id=int(user["user_id"]),
                        invite_id=int(invite["invite_id"]), staff_name=user["name"])
                await db.execute(
                    """
                    update user_identities set last_login_at = now()
                    where provider = 'KAKAO' and provider_user_id = $1
                    """,
                    kakao_user.id)
                return int(user["user_id"]), notification_id
        except asyncpg.UniqueViolationError:
            # 같은 카카오 계정의 콜백이 동시에 두 번 왔다. 한 번 더 돌면 기존 계정으로 로그인된다
            if attempt == 1:
                raise
    raise AssertionError("unreachable")
```

- [ ] **Step 4: `kakao_router.py` 구현**

```python
"""카카오 로그인 엔드포인트 (이슈 #37). 콜백이 끝나면 웹 /auth/complete 로 돌려보낸다."""
from __future__ import annotations

import logging
import secrets
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import RedirectResponse

from app.auth import kakao
from app.auth.kakao_accounts import AuthFlowError, complete_kakao_login
from app.auth.oauth_state import (
    OAUTH_COOKIE, OAUTH_COOKIE_PATH, InvalidState, OAuthState, decode_state, encode_state, safe_next,
)
from app.auth.router import start_session
from app.config import get_settings
from app.deps import Db
from app.members import invites
from app.notifications.service import deliver_notification

router = APIRouter()
logger = logging.getLogger(__name__)


def _to_web(*, error: str | None = None, next_path: str | None = None) -> RedirectResponse:
    query = {}
    if error:
        query["error"] = error
    elif next_path:
        query["next"] = next_path
    url = get_settings().web_base_url.rstrip("/") + "/auth/complete"
    res = RedirectResponse(url + ("?" + urlencode(query) if query else ""), status_code=302)
    res.delete_cookie(OAUTH_COOKIE, path=OAUTH_COOKIE_PATH)
    return res


# store-isolation-ok: 공개 설정 조회
@router.get("/providers")
async def providers():
    return {"kakao": kakao.is_configured()}


# store-isolation-ok: 로그인 시작. 초대 토큰으로 매장을 찾되 id 만 서명 쿠키에 담는다
@router.get("/kakao/start")
async def kakao_start(db: Db, intent: Literal["LOGIN", "STAFF_JOIN"],
                      invite: str | None = None, next: str | None = None):
    if not kakao.is_configured():
        return _to_web(error="KAKAO_NOT_CONFIGURED")
    invite_id = None
    if intent == "STAFF_JOIN":
        found = await invites.resolve(db, token=invite) if invite else None
        if found is None:
            return _to_web(error="INVITE_INVALID")
        invite_id = int(found["invite_id"])
    verifier, challenge = kakao.pkce_pair()
    state = secrets.token_urlsafe(24)
    res = RedirectResponse(kakao.authorize_url(state=state, code_challenge=challenge), status_code=302)
    s = get_settings()
    res.set_cookie(
        OAUTH_COOKIE, encode_state(OAuthState(state, verifier, intent, invite_id, safe_next(next))),
        max_age=600, path=OAUTH_COOKIE_PATH, httponly=True, secure=s.auth_cookie_secure, samesite="lax")
    return res


# store-isolation-ok: 로그인 콜백. 매장은 서명 쿠키의 초대 id 를 다시 검증해 정한다
@router.get("/kakao/callback")
async def kakao_callback(request: Request, db: Db, background: BackgroundTasks,
                         state: str | None = None, code: str | None = None, error: str | None = None):
    try:
        saved = decode_state(request.cookies.get(OAUTH_COOKIE) or "")
    except InvalidState:
        return _to_web(error="OAUTH_STATE_INVALID")
    if not state or not secrets.compare_digest(state, saved.state):
        return _to_web(error="OAUTH_STATE_INVALID")
    if error or not code:
        return _to_web(error="KAKAO_CANCELLED" if error == "access_denied" else "KAKAO_FAILED")
    try:
        kakao_user = await kakao.fetch_user(code=code, code_verifier=saved.verifier)
    except kakao.KakaoError as exc:
        logger.warning("kakao exchange failed: %s", exc)
        return _to_web(error="KAKAO_FAILED")

    invite = None
    if saved.intent == "STAFF_JOIN":
        # start 와 callback 사이에 링크가 재생성됐을 수 있다. 다시 확인한다
        invite = await invites.resolve_by_id(db, invite_id=saved.invite_id)
        if invite is None:
            return _to_web(error="INVITE_INVALID")
    try:
        user_id, notification_id = await complete_kakao_login(
            db, kakao_user=kakao_user, intent=saved.intent, invite=invite)
    except AuthFlowError as exc:
        return _to_web(error=exc.code)
    if notification_id is not None:
        background.add_task(deliver_notification, int(invite["store_id"]), notification_id)
    res = _to_web(next_path=saved.next)
    await start_session(db, res, user_id=user_id)
    return res
```

  `invites.resolve_by_id`를 Task 5의 `invites.py`에 추가한다(테스트 가짜도 같이):

```python
# store-isolation-ok: 서명 쿠키에 담아 둔 초대 id 를 다시 확인한다
async def resolve_by_id(db, *, invite_id: int | None) -> dict | None:
    if invite_id is None:
        return None
    row = await db.fetchrow(
        """
        select i.invite_id, i.store_id, s.store_name
        from invite_codes i join stores s on s.store_id = i.store_id
        where i.invite_id = $1 and i.revoked_at is null and i.expires_at > now()
        """,
        invite_id)
    return dict(row) if row else None
```

  `app/main.py`: `from app.auth.kakao_router import router as kakao_router`, `app.include_router(kakao_router, prefix="/auth", tags=["auth"])`를 auth_router 바로 아래에.

- [ ] **Step 5: 통과 확인** — `.venv/bin/python -m pytest tests/test_kakao_auth.py -q` → PASS.

---

### Task 10: API 전체 검증과 로컬 실측

**Files:** 없음(검증)

- [ ] **Step 1: 전체 테스트** — `cd api && .venv/bin/python -m pytest tests/ -q` → 전부 PASS. 실패가 있으면 넘어가지 않는다.
- [ ] **Step 2: 매장 격리 정적 검사** — `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/auth api/app/members api/app/bootstrap api/app/notifications api/app/deps.py` → 종료 코드 0. 위반이 나면 `# store-isolation-ok:` 사유가 실제로 맞는지 다시 보고 고친다.
- [ ] **Step 3: `store-isolation-check` 스킬 절차 수행** — 로컬 API를 띄우고 두 매장 토큰으로 `/members`, `/members/requests/{다른매장 요청id}/approve`, `/members/{다른매장 직원}/remove`가 404인지 확인한다.
- [ ] **Step 4: 로컬 종단 실측(카카오 없이)** — 이메일 경로로 순환을 닫는다.

```bash
API=http://localhost:8000; ORIGIN=http://localhost:3000; J=/tmp/askbuddy-jar
# 1) 점주 로그인(데모) → 링크
curl -s -c $J -H "Origin: $ORIGIN" -H 'Content-Type: application/json' \
  -d '{"email":"<데모점주>","password":"<비번>","role":"OWNER"}' $API/auth/login | tee /tmp/o.json
OWNER=$(python3 -c "import json;print(json.load(open('/tmp/o.json'))['token'])")
curl -s -H "Authorization: Bearer $OWNER" $API/members/invite-link
# 2) 알바 이메일 가입(/auth/signup role=STAFF) → /learn/roadmap 403(매장 없음), join-status NONE
# 3) 알바 POST /auth/join-requests {invite_token} → PENDING, 점주 notification_events 에 JOIN_REQUESTED 1건
# 4) 점주 /members → pending 1건 → approve → 알바 notification_events 에 JOIN_APPROVED 1건(destination /staff/roadmap)
# 4-1) 알바 /auth/refresh(쿠키) → store_id 있는 토큰 → /learn/roadmap 200
# 5) 점주 remove → 알바 기존 토큰으로 /learn/roadmap 403, /auth/refresh 401
# 6) 다른 알바가 요청 → 점주가 /members/invite-link/rotate → 그 요청 approve 204
# 7) 5)에서 내보낸 알바가 다시 로그인 → 새 링크로 join-requests → approve 204 → store_members 같은 member_id, removed_at null
```

  각 단계의 실제 응답을 결과 보고에 붙인다. 데모 계정 값은 `db/002_seed_demo.sql`에서 확인한다.

---

### Task 11: 웹 세션 (메모리 토큰·자동 갱신·복원)

**Files:**
- Modify: `web/lib/api.ts` (`fetchJson`, 새 함수), `web/lib/store.tsx`, `web/lib/guard.tsx`, `web/components/session-expiry-handler.tsx`, `web/components/auth-gate-state.tsx`(필요 시 문구)

**Interfaces:**
- Produces (api.ts):
  - `type SessionResponse = { token: string; user: { user_id: number; name: string; role: "OWNER" | "STAFF"; store_id?: number | null } }`
  - `refreshSession(): Promise<SessionResponse>` — 단일 비행, 401이면 300ms 뒤 1회 재시도
  - `onSessionRenewed(listener: (s: SessionResponse) => void): () => void`
  - `logoutSession(): Promise<void>`
- Produces (store.tsx): 상태 `sessionRestore: "pending" | "ok" | "failed"`, 액션 `{ type: "SET_TOKEN"; token: string; storeId: number | null }`, 컨텍스트 함수 `restoreSession(): void`

- [ ] **Step 1: `fetchJson`에 쿠키와 401 재시도** — 기존 `fetchJson` 본문을 `fetchJsonOnce`로 이름만 바꾸고, `fetch` 호출 옵션에 `credentials: "include"`를 추가한다. `fetchJsonOnce`의 `emitSessionExpired` 호출은 지운다. 그 위에:

```ts
let renewing: Promise<SessionResponse> | null = null;
const renewListeners = new Set<(s: SessionResponse) => void>();

export function onSessionRenewed(listener: (s: SessionResponse) => void): () => void {
  renewListeners.add(listener);
  return () => { renewListeners.delete(listener); };
}

async function postRefresh(): Promise<SessionResponse> {
  return fetchJsonOnce<SessionResponse>("/auth/refresh", { method: "POST", sessionExpiry: false });
}

// 여러 요청이 동시에 401 을 받아도 갱신은 한 번만 한다.
// 다른 탭이 방금 회전했다면 첫 시도가 401 이다 — 쿠키는 탭끼리 공유하므로 잠시 뒤 한 번 더 시도한다.
export function refreshSession(): Promise<SessionResponse> {
  if (!renewing) {
    renewing = (async () => {
      try {
        return await postRefresh();
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          await new Promise((r) => setTimeout(r, 300));
          return await postRefresh();
        }
        throw error;
      }
    })()
      .then((session) => {
        renewListeners.forEach((l) => l(session));
        return session;
      })
      .finally(() => { renewing = null; });
  }
  return renewing;
}

async function fetchJson<T>(path: string, init?: FetchJsonInit): Promise<T> {
  try {
    return await fetchJsonOnce<T>(path, init);
  } catch (error) {
    const headers = new Headers(init?.headers);
    const canRenew = (init?.sessionExpiry ?? true) && headers.has("Authorization");
    if (!(error instanceof ApiError) || error.status !== 401 || !canRenew) throw error;
    let session: SessionResponse;
    try {
      session = await refreshSession();
    } catch {
      emitSessionExpired(path);
      throw error;
    }
    headers.set("Authorization", `Bearer ${session.token}`);
    return fetchJsonOnce<T>(path, { ...init, headers: Object.fromEntries(headers.entries()) });
  }
}

export async function logoutSession(): Promise<void> {
  await fetchJsonOnce<void>("/auth/logout", { method: "POST", sessionExpiry: false });
}
```

  `SessionResponse` 타입은 `AuthResponse` 정의 아래에 둔다. 운영자 호출(`sessionExpiry: false`)은 갱신을 시도하지 않는다.

- [ ] **Step 2: 스토어 — 토큰 비영속과 시작 시 복원** — `store.tsx`
  - `STATE_VERSION = 10`, 복원 허용 버전 `10, 9, 8, 7`.
  - `AppState`에 `sessionRestore: "pending" | "ok" | "failed"` 추가(초기 `"pending"`).
  - `PersistedAppState`와 `persistedState`에서 `token` 제거, `restorePersistedState`의 `token` 줄 제거.
  - 액션 `SET_TOKEN` 추가:

```ts
    case "SET_TOKEN":
      // 같은 사용자의 access token 갱신. 화면 상태는 그대로 둔다
      return { ...state, token: action.token, storeId: action.storeId };
```

  - `HYDRATE` 페이로드에 `sessionRestore`를 함께 넣는다.
  - 첫 `useEffect`를 아래로 교체:

```ts
  const restoreSession = useCallback(() => {
    let persisted: Partial<AppState> = {};
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const parsed: unknown = raw ? JSON.parse(raw) : null;
      if (parsed && typeof parsed === "object" && "v" in parsed &&
          [STATE_VERSION, 9, 8, 7].includes(parsed.v as number) &&
          "data" in parsed && parsed.data && typeof parsed.data === "object") {
        persisted = restorePersistedState(parsed.data);
      } else {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      persisted = {};
    }
    refreshSession().then(
      (s) => dispatch({ type: "HYDRATE", payload: {
        ...persisted, sessionRestore: "ok", token: s.token, role: s.user.role,
        userId: s.user.user_id, storeId: s.user.store_id ?? null } }),
      (error: unknown) => {
        // 401 이면 로그인이 필요하다. 그 밖(오프라인·지연)은 로그인 화면으로 보내지 않고 재시도를 보여 준다
        const unauthenticated = error instanceof ApiError && error.status === 401;
        dispatch({ type: "HYDRATE", payload: unauthenticated
          ? { sessionRestore: "ok" }
          : { ...persisted, sessionRestore: "failed" } });
      });
  }, []);

  useEffect(() => { restoreSession(); }, [restoreSession]);

  useEffect(() => onSessionRenewed((s) => {
    dispatch({ type: "SET_TOKEN", token: s.token, storeId: s.user.store_id ?? null });
  }), []);
```

  `401` 분기에서 `role` 등을 비우는 것은 `HYDRATE`가 `initialState` 위에 페이로드를 덮기 때문이다(현재 상태가 초기값). 컨텍스트 값에 `restoreSession`을 추가한다(`AppContextValue` 타입도).
  - 로그인 화면들이 `SET_AUTH`로 넣는 토큰은 그대로 쓴다(메모리).

- [ ] **Step 3: 가드** — `guard.tsx` (단일 로그인 화면 `/` 기준, Task 13과 함께)
  - `const { state, dispatch, restoreSession } = useApp();`
  - `if (!state.hydrated) return loading` 바로 다음에 `if (state.sessionRestore === "failed") return { ready: false, state: "error", retry: restoreSession };`
  - `hasLocalSession = state.token !== null` (역할 비교 제거 — 역할이 다르거나 미정이면 bootstrap이 목적지를 알려 준다).
  - 세 번째 `useEffect`의 `if (data.user.role !== role) { dispatch LOGOUT; router.replace(authPath) }`를 `if (data.user.role !== role) { router.replace(data.default_destination); return; }`로 바꾼다. 알바가 점주 주소를 열면 로그아웃이 아니라 자기 화면으로 간다. 역할 미정이면 `/auth/role`.
  - `web/app/owner/layout.tsx`·`web/app/staff/layout.tsx`의 `useAuthGuard("OWNER", "/owner/auth")`·`useAuthGuard("STAFF", "/staff/auth")` 두 번째 인자를 `"/"`로.
  - `session-expiry-handler.tsx`의 `authPath` 계산을 `"/"` 고정으로.
  - 세 번째 `useEffect`의 OWNER 무매장 분기 아래에:

```ts
    if (role === "STAFF" && data.store === null && pathname !== "/staff/pending") {
      router.replace("/staff/pending");
    }
```

- [ ] **Step 4: 캐시 비움 조건** — `session-expiry-handler.tsx`의 첫 `useEffect`를 사용자 기준으로:

```ts
  const previousUser = useRef<number | null>(null);

  useEffect(() => {
    // access token 은 60분마다 바뀐다. 사용자가 바뀔 때만 캐시를 비운다
    if (previousUser.current !== null && state.userId !== previousUser.current) {
      queryClient.clear();
    }
    previousUser.current = state.userId;
    if (state.token) handled.current = false;
  }, [state.userId, state.token, queryClient]);
```

  `previousToken` ref는 지운다.

- [ ] **Step 5: 로그인 함수에 쿠키** — `login`, `signup`, `createStore`는 `fetchJson`을 쓰므로 Step 1의 `credentials: "include"`로 충분하다. `signup`의 `role` 타입은 이미 `"OWNER" | "STAFF"`다. `joinByInvite`는 Task 13에서 지운다(`/auth/join` 제거).

- [ ] **Step 6: 정적 검사** — `cd web && pnpm check` → 통과. `createInvite` 참조로 실패하면 Task 14에서 지울 예정이니 `owner/complete/page.tsx`의 import만 임시로 남기지 말고 Task 14를 이어서 진행한다(이 Task 단독 통과 조건: `createInvite` 외 오류 0).

- [ ] **Step 7: `web-async-state-check` 스킬 수행** — 토큰 수명은 `lib/`만 소유하고 화면 컴포넌트가 갱신 타이머·재시도를 갖지 않는지 확인.

---

### Task 12: 승인 대기 화면 — 폴링 없이 승인 즉시 반영

결정(2026-10-03): 15초 폴링 대신 점주가 승인하면 알바에게 바로 알림이 가고 바로 쓸 수 있게 한다. Realtime은 쓰지 않는다(D6). 경로는 ① Web Push → 서비스 워커가 열린 화면에 메시지 → 즉시 재조회, ② 화면 복귀·포커스 시 재조회, ③ 알림 탭 → `/staff/roadmap` 새로 열림 → 세션 복원 때 서버가 store_id 있는 토큰 발급.

**Files:**
- Modify: `web/public/sw.js` (Push 수신 시 열린 화면에 메시지)
- Modify: `web/lib/api.ts` (`getJoinStatus`, `getPushKey`, `saveMyPushSubscription`), `web/lib/query.ts` (`joinStatusQuery`)
- Create: `web/lib/push.ts` (`applicationServerKey`, `enablePersonalPush`)
- Create: `web/app/staff/pending/page.tsx`

**Interfaces:**
- Consumes: Task 6 `GET /auth/join-status`, Task 7A `/notifications/push-key`·`my-subscriptions`, Task 11 `refreshSession`
- Produces:
  - `type JoinStatus = { status: "PENDING" | "REJECTED" | "APPROVED" | "REMOVED" | "NONE"; store_name: string | null }`
  - `getJoinStatus(token, signal?)`, `getPushKey(token, signal?)`, `saveMyPushSubscription(sub: PushSubscriptionJSON, token)`
  - `joinStatusQuery(token: string | null, userId: number | null)`
  - `PUSH_MESSAGE = "askbuddy:push"` (sw.js → 화면 `postMessage`의 `type`)
  - `enablePersonalPush(token: string): Promise<"enabled" | "denied" | "unsupported" | "not_configured">`

- [ ] **Step 1: 서비스 워커** — `web/public/sw.js`의 `push` 핸들러에서 `showNotification`과 함께 열린 화면에 알린다.

```js
self.addEventListener("push", (event) => {
  if (!event.data) return;
  let data;
  try {
    data = event.data.json();
  } catch {
    data = { title: "AskBuddy", body: event.data.text(), destination: "/owner/notifications" };
  }
  // 열린 화면이 있으면 바로 다시 조회하게 알린다. 승인 대기 화면이 이걸로 즉시 넘어간다
  const notifyClients = clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) =>
    windows.forEach((client) => client.postMessage({ type: "askbuddy:push", destination: data.destination || null }))
  );
  event.waitUntil(Promise.all([
    notifyClients,
    self.registration.showNotification(data.title || "AskBuddy", {
      body: data.body || "새 알림이 있어요.",
      icon: data.icon || "/images/buddy-hero.png",
      badge: "/images/buddy-hero.png",
      tag: data.notification_id ? `askbuddy-${data.notification_id}` : undefined,
      data: { destination: data.destination || "/owner/notifications" },
    }),
  ]));
});
```

  `notificationclick`은 그대로 둔다(`existing.navigate(target)`이 전체 이동이라 세션 복원을 다시 거친다).

- [ ] **Step 2: API·쿼리**

```ts
// api.ts
export type JoinStatus = {
  status: "PENDING" | "REJECTED" | "APPROVED" | "REMOVED" | "NONE";
  store_name: string | null;
};

export async function getJoinStatus(token: string, signal?: AbortSignal) {
  return fetchJson<JoinStatus>("/auth/join-status", { headers: authHeader(token), signal, cache: "no-store" });
}

export async function getPushKey(token: string, signal?: AbortSignal) {
  return fetchJson<{ push_configured: boolean; vapid_public_key: string | null }>(
    "/notifications/push-key", { headers: authHeader(token), signal });
}

export async function saveMyPushSubscription(subscription: PushSubscriptionJSON, token: string) {
  return fetchJson<{ subscription_id: number; enabled: boolean }>("/notifications/my-subscriptions", {
    method: "POST", headers: authHeader(token), body: JSON.stringify(subscription),
  });
}
```

```ts
// query.ts — queryKeys 에 joinStatus: (userId: number | null) => ["join-status", userId] as const 추가
export function joinStatusQuery(token: string | null, userId: number | null) {
  return queryOptions({
    queryKey: queryKeys.joinStatus(userId),
    queryFn: ({ signal }) => getJoinStatus(token!, signal),
    enabled: Boolean(token && userId),
    // 폴링하지 않는다. Push 메시지와 화면 복귀 때만 다시 조회한다
    refetchOnWindowFocus: "always",
    staleTime: 0,
  });
}
```

- [ ] **Step 3: `web/lib/push.ts`** — 점주 알림 화면(`web/app/owner/notifications/page.tsx:17`)의 `applicationServerKey`를 여기로 옮기고 그 화면은 import해서 쓴다.

```ts
// Web Push 구독. 점주 알림 설정과 알바 승인 알림이 같이 쓴다
import { getPushKey, saveMyPushSubscription } from "./api";

export const PUSH_MESSAGE = "askbuddy:push";

export function applicationServerKey(value: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

// 권한 요청은 반드시 사용자 버튼 클릭 안에서 부른다(iOS 요구)
export async function enablePersonalPush(token: string): Promise<"enabled" | "denied" | "unsupported" | "not_configured"> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return "unsupported";
  const key = await getPushKey(token);
  if (!key.push_configured || !key.vapid_public_key) return "not_configured";
  if ((await Notification.requestPermission()) !== "granted") return "denied";
  const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" });
  await navigator.serviceWorker.ready;
  const current = (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: applicationServerKey(key.vapid_public_key),
    }));
  await saveMyPushSubscription(current.toJSON(), token);
  return "enabled";
}
```

- [ ] **Step 4: 화면** — `web/app/staff/pending/page.tsx`

```tsx
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Buddy, Button, Shell } from "@/components/ui";
import { apiErrorMessage, refreshSession } from "@/lib/api";
import { PUSH_MESSAGE, enablePersonalPush } from "@/lib/push";
import { joinStatusQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

const COPY = {
  NONE: { title: "아직 합류한 매장이 없어요", body: "사장님께 받은 초대 링크를 열면 합류 요청이 바로 가요." },
  PENDING: { title: "사장님 승인을 기다리고 있어요", body: "승인되면 바로 알려 드리고 시작할 수 있어요." },
  REJECTED: { title: "합류가 승인되지 않았어요", body: "사장님께 확인한 뒤 초대 링크로 다시 요청해 주세요." },
  REMOVED: { title: "매장에서 나가게 되었어요", body: "다시 합류하려면 사장님께 초대 링크를 받아 주세요." },
} as const;

const PUSH_COPY = {
  enabled: "승인되면 알림으로 알려 드릴게요.",
  denied: "알림이 꺼져 있어요. 앱을 다시 열면 승인 여부를 확인할 수 있어요.",
  unsupported: "이 브라우저는 알림을 받을 수 없어요. 홈 화면에 추가한 앱에서 열어 주세요.",
  not_configured: "지금은 알림을 보낼 수 없어요. 앱을 다시 열면 확인할 수 있어요.",
} as const;

export default function StaffPendingPage() {
  const router = useRouter();
  const { state, dispatch } = useApp();
  const status = useQuery(joinStatusQuery(state.token, state.userId));
  const [push, setPush] = useState<keyof typeof PUSH_COPY | "busy" | null>(null);
  const { refetch } = status;

  // 서비스 워커가 Push 를 받으면 바로 다시 조회한다(폴링 없음)
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === PUSH_MESSAGE) void refetch();
    };
    navigator.serviceWorker.addEventListener("message", onMessage);
    return () => navigator.serviceWorker.removeEventListener("message", onMessage);
  }, [refetch]);

  useEffect(() => {
    if (status.data?.status !== "APPROVED") return;
    // 승인되면 store_id 가 든 토큰을 다시 받는다
    void refreshSession().then((s) => {
      dispatch({ type: "SET_AUTH", token: s.token, role: "STAFF", userId: s.user.user_id, storeId: s.user.store_id ?? null });
      router.replace("/staff/roadmap");
    });
  }, [status.data?.status, dispatch, router]);

  async function turnOnPush() {
    if (!state.token) return;
    setPush("busy");
    try {
      setPush(await enablePersonalPush(state.token));
    } catch {
      setPush("not_configured");
    }
  }

  const kind = status.data && status.data.status !== "APPROVED" ? status.data.status : null;
  return (
    <Shell>
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
        <Buddy size={110} />
        {status.isPending && <p className="text-sm text-muted" role="status">확인하고 있어요…</p>}
        {status.isError && (
          <>
            <p role="alert" className="text-sm text-danger-500">{apiErrorMessage(status.error, "상태를 불러오지 못했어요.")}</p>
            <Button onClick={() => void status.refetch()}>다시 시도</Button>
          </>
        )}
        {kind && (
          <>
            {status.data?.store_name && <p className="text-sm font-bold text-brand-700">{status.data.store_name}</p>}
            <h1 className="text-xl font-bold text-foreground">{COPY[kind].title}</h1>
            <p className="text-sm text-muted">{COPY[kind].body}</p>
          </>
        )}
        {kind === "PENDING" && push !== "enabled" && (
          <Button loading={push === "busy"} loadingLabel="알림 켜는 중" onClick={() => void turnOnPush()}>
            승인되면 알림 받기
          </Button>
        )}
        {push && push !== "busy" && <p className="text-xs text-muted" role="status">{PUSH_COPY[push]}</p>}
        {status.data?.status === "APPROVED" && <p className="text-sm text-muted" role="status">승인됐어요. 시작하는 중…</p>}
      </div>
    </Shell>
  );
}
```

  로그아웃 버튼은 넣지 않는다(마이페이지와 함께 Figma 후 구현).

- [ ] **Step 5: 정적 검사** — `cd web && pnpm check` → 통과.

---

### Task 13: 카카오 버튼·초대 링크 진입·콜백 도착 화면

결정(2026-10-03): 초대 링크를 열었을 때 **로그인돼 있으면 바로 합류 요청**이 가고, 로그인 안 돼 있으면 로그인, 계정이 없으면 가입한다. 카카오 `STAFF_JOIN` 한 번이 셋을 모두 처리한다. 알바 화면의 카카오 버튼은 계정이 없으면 만든다(매장 없음).

**Files:**
- Modify: `web/lib/api.ts` (`getProviders`, `getInvitePreview`, `kakaoStartUrl`, `requestJoin`, `AUTH_ERROR_COPY`, `joinByInvite` 삭제), `web/lib/query.ts`
- Create: `web/components/kakao-login-button.tsx`, `web/app/auth/complete/page.tsx`, `web/app/join/[token]/page.tsx`(서버, OG 메타데이터), `web/app/join/[token]/join-client.tsx`
- Create: `web/app/auth/email/page.tsx`, `web/app/auth/role/page.tsx`
- Modify: `web/app/page.tsx`(단일 로그인 화면), `web/app/manifest.ts`, `web/app/role/page.tsx`·`web/app/owner/auth/page.tsx`·`web/app/staff/auth/page.tsx`(→ `/` redirect), `web/lib/store.tsx`(`SET_AUTH` role nullable)

**Interfaces:**
- Produces: `chooseRole(role, token)`, `kakaoStartUrl(p: { intent: "LOGIN" | "STAFF_JOIN"; invite?: string; next?: string | null }): string`, `getProviders()`, `getInvitePreview(token, signal?)`, `requestJoin(inviteToken: string, token: string): Promise<{ status: "PENDING" | "ALREADY_MEMBER"; store_name: string }>`, `providersQuery()`, `invitePreviewQuery(token)`, `<KakaoLoginButton intent invite? next? label? />`, `AUTH_ERROR_COPY: Record<string, string>`

- [ ] **Step 1: API 함수** — `joinByInvite`를 지우고(`/auth/join` 제거됨) 추가:

```ts
export function kakaoStartUrl(p: { intent: "LOGIN" | "STAFF_JOIN"; invite?: string; next?: string | null }) {
  const q = new URLSearchParams({ intent: p.intent });
  if (p.invite) q.set("invite", p.invite);
  if (p.next) q.set("next", p.next);
  return `${BASE}/auth/kakao/start?${q.toString()}`;
}

export async function getProviders(signal?: AbortSignal) {
  return fetchJson<{ kakao: boolean }>("/auth/providers", { signal });
}

export async function getInvitePreview(token: string, signal?: AbortSignal) {
  return fetchJson<{ store_name: string }>(`/auth/invites/${encodeURIComponent(token)}`, { signal });
}

export async function requestJoin(inviteToken: string, token: string) {
  return fetchJson<{ status: "PENDING" | "ALREADY_MEMBER"; store_name: string }>("/auth/join-requests", {
    method: "POST", headers: authHeader(token), body: JSON.stringify({ invite_token: inviteToken }),
  });
}

// MVP §28 문구 사전과 같은 문구
export const AUTH_ERROR_COPY: Record<string, string> = {
  KAKAO_CANCELLED: "카카오 로그인을 취소했어요.",
  KAKAO_FAILED: "카카오 로그인에 실패했어요. 잠시 후 다시 시도해 주세요.",
  OAUTH_STATE_INVALID: "로그인 시간이 지났어요. 처음부터 다시 시도해 주세요.",
  ROLE_CONFLICT: "이 계정은 다른 역할로 가입되어 있어요.",
  INVITE_INVALID: "더 이상 쓸 수 없는 초대 링크예요. 사장님께 새 링크를 받아 주세요.",
  ALREADY_IN_OTHER_STORE: "이미 다른 매장에 합류한 계정이에요.",
  KAKAO_NOT_CONFIGURED: "지금은 카카오 로그인을 쓸 수 없어요. 이메일로 계속해 주세요.",
};
```

  `query.ts`: `providersQuery()`(`staleTime: Infinity`, key `["auth-providers"]`), `invitePreviewQuery(token)`(key `["invite-preview", token]`, `retry: false`).

- [ ] **Step 2: 카카오 버튼** — `web/components/kakao-login-button.tsx`

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { kakaoStartUrl } from "@/lib/api";
import { providersQuery } from "@/lib/query";

// 카카오 디자인 가이드: 배경 #FEE500, 글자 85% 검정. 서버 설정이 없으면 버튼을 숨긴다
export function KakaoLoginButton({ intent, invite, next, label = "카카오 로그인" }: {
  intent: "LOGIN" | "STAFF_JOIN";
  invite?: string;
  next?: string | null;
  label?: string;
}) {
  const providers = useQuery(providersQuery());
  if (!providers.data?.kakao) return null;
  return (
    <a
      href={kakaoStartUrl({ intent, invite, next })}
      className="flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#FEE500] text-[15px] font-bold text-black/85 active:scale-[0.98]"
    >
      <svg aria-hidden width="18" height="18" viewBox="0 0 24 24"><path fill="currentColor" d="M12 3C6.48 3 2 6.48 2 10.77c0 2.77 1.86 5.2 4.66 6.57l-.95 3.48c-.08.3.26.54.52.37l4.15-2.74c.53.07 1.07.1 1.62.1 5.52 0 10-3.48 10-7.78S17.52 3 12 3z" /></svg>
      {label}
    </a>
  );
}
```

  색 리터럴은 카카오 브랜드 규정 색이라 디자인 토큰 대신 그대로 둔다(주석에 근거).

- [ ] **Step 3: `/auth/complete`** — `web/app/auth/complete/page.tsx`

```tsx
"use client";

import { Suspense, useEffect } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Buddy, Shell } from "@/components/ui";
import { AUTH_ERROR_COPY, getBootstrap, refreshSession } from "@/lib/api";
import { useApp } from "@/lib/store";

function Complete() {
  const router = useRouter();
  const params = useSearchParams();
  const error = params.get("error");
  const next = params.get("next");
  const { dispatch } = useApp();
  // 콜백 도착은 한 번뿐인 작업이다. 화면이 다시 그려져도 다시 부르지 않게 쿼리로 둔다
  const session = useQuery({
    queryKey: ["auth-complete"],
    queryFn: async () => {
      const s = await refreshSession();
      const boot = await getBootstrap(s.token);
      return { s, boot };
    },
    enabled: !error,
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
  });

  useEffect(() => {
    if (!session.data) return;
    const { s, boot } = session.data;
    dispatch({ type: "SET_AUTH", token: s.token, role: s.user.role, userId: s.user.user_id, storeId: s.user.store_id ?? null });
    const prefix = s.user.role === "OWNER" ? "/owner/" : "/staff/";
    router.replace(next && next.startsWith(prefix) && boot.store ? next : boot.default_destination);
  }, [session.data, next, dispatch, router]);

  const message = error ? (AUTH_ERROR_COPY[error] ?? AUTH_ERROR_COPY.KAKAO_FAILED)
    : session.isError ? "로그인을 마치지 못했어요. 다시 시도해 주세요." : null;
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
      <Buddy size={100} />
      {message ? (
        <>
          <p role="alert" className="text-sm font-medium text-foreground">{message}</p>
          <Link href="/role" className="text-sm font-bold text-brand-700 underline">처음으로</Link>
        </>
      ) : (
        <p role="status" className="text-sm text-muted">로그인하는 중…</p>
      )}
    </div>
  );
}

export default function AuthCompletePage() {
  return <Shell><Suspense><Complete /></Suspense></Shell>;
}
```

  카카오 `STAFF_JOIN`으로 들어온 알바는 bootstrap이 `/staff/pending`을 주므로 따로 분기하지 않는다.

- [ ] **Step 4a: `/join/[token]/page.tsx` — OG 미리보기** (서버 컴포넌트)

  카톡·문자에 링크만 붙여도 매장명이 든 미리보기가 뜨게 한다. 카카오 SDK 카드가 아닌 경로(Web Share·복사)에서도 같은 미리보기가 나온다. Next 서버가 FastAPI 공개 엔드포인트(`GET /auth/invites/{token}`)를 부른다 — DB·키 접근이 아니므로 불변식 1·2와 충돌하지 않는다.

```tsx
import type { Metadata } from "next";
import { JoinClient } from "./join-client";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function storeName(token: string): Promise<string | null> {
  try {
    const res = await fetch(`${API}/auth/invites/${encodeURIComponent(token)}`, { cache: "no-store" });
    if (!res.ok) return null;
    return ((await res.json()) as { store_name: string }).store_name;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ token: string }> }): Promise<Metadata> {
  const { token } = await params;
  const name = await storeName(token);
  const title = name ? `${name}에서 초대했어요 · AskBuddy` : "AskBuddy 초대";
  const description = name ? "눌러서 매장에 합류하세요. 사장님이 승인하면 바로 시작해요." : "초대 링크를 확인해 주세요.";
  return {
    title,
    description,
    // 토큰이 든 주소가 검색에 노출되지 않게 한다
    robots: { index: false, follow: false },
    openGraph: { title, description, images: ["/images/buddy-hero.png"], type: "website" },
  };
}

export default async function JoinPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <JoinClient inviteToken={token} />;
}
```

  `images`의 상대 경로가 절대 URL이 되려면 루트 `web/app/layout.tsx`의 `metadata`에 `metadataBase`가 있어야 한다. 없으면 `metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000")`을 추가하고 `.env.example`에 `NEXT_PUBLIC_SITE_URL=http://localhost:3000`(Vercel은 `https://askbuddy.kr`)을 둔다.

- [ ] **Step 4: `/join/[token]/join-client.tsx`** — 로그인 여부에 따라 세 갈래.

```tsx
"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Buddy, Button, Input, Shell } from "@/components/ui";
import { KakaoLoginButton } from "@/components/kakao-login-button";
import { AUTH_ERROR_COPY, ApiError, apiErrorMessage, login, refreshSession, requestJoin, signup } from "@/lib/api";
import { invitePreviewQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

type EmailMode = "login" | "signup";

export function JoinClient({ inviteToken }: { inviteToken: string }) {
  const router = useRouter();
  const { state, dispatch } = useApp();
  const preview = useQuery(invitePreviewQuery(inviteToken));
  // 역할을 아직 안 고른 계정도 링크로 왔으면 알바로 요청한다(서버가 STAFF 로 정한다)
  const loggedInStaff = state.hydrated && state.token !== null && state.role !== "OWNER";
  const loggedInOwner = state.hydrated && state.token !== null && state.role === "OWNER";

  // 로그인돼 있으면 화면에 들어오자마자 합류 요청을 보낸다. 한 번만 보낸다(같은 키의 mutation)
  const join = useMutation({
    mutationKey: ["join-request", inviteToken],
    mutationFn: (accessToken: string) => requestJoin(inviteToken, accessToken),
    onSuccess: async (res) => {
      // 역할 미정이었다면 서버가 STAFF 로 정했다. 역할이 든 토큰을 다시 받는다
      const s = await refreshSession();
      dispatch({ type: "SET_AUTH", token: s.token, role: s.user.role, userId: s.user.user_id, storeId: s.user.store_id ?? null });
      router.replace(res.status === "ALREADY_MEMBER" ? "/staff/roadmap" : "/staff/pending");
    },
  });
  const { mutate, status: joinStatus } = join;
  useEffect(() => {
    if (loggedInStaff && preview.data && joinStatus === "idle") mutate(state.token!);
  }, [loggedInStaff, preview.data, joinStatus, mutate, state.token]);

  const [emailMode, setEmailMode] = useState<EmailMode | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitEmail(e: FormEvent) {
    e.preventDefault();
    if (busy || !emailMode) return;
    setBusy(true);
    setError(null);
    try {
      const { token: access, user } = emailMode === "login"
        ? await login(email, password)
        : await signup({ name, email, password });
      dispatch({ type: "SET_AUTH", token: access, role: user.role, userId: user.user_id, storeId: user.store_id ?? null });
      // SET_AUTH 뒤 위 effect 가 합류 요청을 보낸다
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError("이메일 또는 비밀번호가 맞지 않습니다");
      else if (err instanceof ApiError && err.status === 409) setError("이미 가입된 이메일입니다. 로그인해 주세요");
      else setError(apiErrorMessage(err, "요청하지 못했어요."));
    } finally {
      setBusy(false);
    }
  }

  const invalid = preview.error instanceof ApiError && preview.error.status === 404;
  const joinErrorCode = join.error instanceof ApiError ? join.error.code : null;
  return (
    <Shell>
      <div className="flex flex-1 flex-col justify-center gap-5 px-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <Buddy size={96} />
          {(preview.isPending || !state.hydrated) && <p role="status" className="text-sm text-muted">초대 링크를 확인하고 있어요…</p>}
          {invalid && <p role="alert" className="text-sm font-medium">{AUTH_ERROR_COPY.INVITE_INVALID}</p>}
          {preview.isError && !invalid && (
            <>
              <p role="alert" className="text-sm text-danger-500">{apiErrorMessage(preview.error, "초대 링크를 확인하지 못했어요.")}</p>
              <Button onClick={() => void preview.refetch()}>다시 시도</Button>
            </>
          )}
          {preview.data && <h1 className="text-xl font-bold">{preview.data.store_name}에 합류합니다</h1>}
        </div>

        {preview.data && loggedInOwner && (
          <p role="alert" className="text-center text-sm">{AUTH_ERROR_COPY.ROLE_CONFLICT}</p>
        )}

        {preview.data && loggedInStaff && (
          <div className="text-center">
            {join.isPending && <p role="status" className="text-sm text-muted">합류 요청을 보내는 중…</p>}
            {join.isError && (
              <>
                <p role="alert" className="text-sm text-danger-500">
                  {joinErrorCode && AUTH_ERROR_COPY[joinErrorCode] ? AUTH_ERROR_COPY[joinErrorCode] : apiErrorMessage(join.error, "합류 요청을 보내지 못했어요.")}
                </p>
                <Button onClick={() => join.mutate(state.token!)}>다시 시도</Button>
              </>
            )}
          </div>
        )}

        {preview.data && state.hydrated && !state.token && (
          <div className="space-y-3">
            <p className="text-center text-sm text-muted">가입하면 사장님이 승인한 뒤 시작할 수 있어요.</p>
            <KakaoLoginButton intent="STAFF_JOIN" invite={inviteToken} label="카카오로 시작하기" />
            <div className="flex justify-center gap-4 text-sm font-bold text-muted">
              <button type="button" className="underline" onClick={() => setEmailMode("login")}>이메일로 로그인</button>
              <button type="button" className="underline" onClick={() => setEmailMode("signup")}>이메일로 가입</button>
            </div>
            {emailMode && (
              <form onSubmit={submitEmail} className="space-y-2">
                {emailMode === "signup" && <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="이름" required maxLength={50} />}
                <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="이메일" required />
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="비밀번호 6자 이상" required minLength={6} />
                {error && <p role="alert" className="text-xs text-danger-500">{error}</p>}
                <Button type="submit" className="w-full" loading={busy} loadingLabel="처리 중">
                  {emailMode === "login" ? "로그인하고 합류 요청" : "가입하고 합류 요청"}
                </Button>
              </form>
            )}
          </div>
        )}
      </div>
    </Shell>
  );
}
```

  `Input`·`Button`의 실제 prop 이름은 `web/components/ui.tsx`에서 확인하고 맞춘다. 세션 복원(Task 11)이 끝나기 전(`hydrated=false`)에는 세 갈래 중 어느 것도 그리지 않는다 — 로그인된 사용자에게 로그인 버튼이 깜빡이지 않게.

- [ ] **Step 5: 단일 로그인 화면 `/`** — 사진(2026-10-03 사용자 제공) 기준. 지금 `web/app/page.tsx`(마스코트·AskBuddy·문구)에 버튼 영역만 바꾼다.
  - 하단: `<KakaoLoginButton intent="LOGIN" next={searchParams.get("next")} />`(라벨 "카카오 로그인"), 그 아래 흰 버튼 `이메일로 시작하기` → `/auth/email` (`next` 유지), 맨 아래 작은 글씨 `알바생은 사장님이 보낸 링크로 바로 들어와요`.
  - 카카오 버튼이 숨겨지는 경우(서버 키 미설정)에도 이메일 버튼만으로 화면이 성립해야 한다.
  - 이미 로그인돼 있으면(`state.token`) bootstrap을 불러 `default_destination`으로 `router.replace`. 세션 복원 중(`!state.hydrated`)에는 버튼 대신 로딩 표시 — 로그인된 사람에게 버튼이 깜빡이지 않게.
  - `next`는 `useSearchParams`로 읽는다(`Suspense` 경계). 페이지를 `"use client"`로 바꾸면서 기존 `next/image` 사용은 유지한다.
  - `web/app/manifest.ts`의 `start_url`을 `"/"`로.

- [ ] **Step 6: 이메일 로그인·가입 `/auth/email`** — `web/app/auth/email/page.tsx` 신규(레이아웃 가드 밖).
  - 탭 두 개: 로그인(`login(email, password)`), 가입(`signup({ name, email, password })` — 역할 없이).
  - 성공 시 `dispatch SET_AUTH`(role은 응답값, 미정이면 null) → bootstrap → `next`가 그 역할 경로면 `next`, 아니면 `default_destination`(역할 미정이면 `/auth/role`).
  - 오류 문구는 기존 `owner/auth`·`staff/auth`의 `describe`를 옮긴다(401 이메일·비밀번호 불일치, 409 이미 가입된 이메일). 데모 모드 기본값(`NEXT_PUBLIC_DEMO_MODE`)도 옮긴다.
  - `api.ts`: `login(email, password, role?)`의 `role`을 선택 인자로, `signup`의 `role`도 선택으로. `AuthUser.role` 타입을 `"OWNER" | "STAFF" | null`로.

- [ ] **Step 6a: 역할 선택 `/auth/role`** — `web/app/auth/role/page.tsx` 신규.

```tsx
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { Buddy, Button, Shell } from "@/components/ui";
import { apiErrorMessage, chooseRole } from "@/lib/api";
import { useApp } from "@/lib/store";

// 가입 직후 한 번만 고른다. 초대 링크로 온 사람은 여기를 거치지 않는다(자동 알바)
export default function ChooseRolePage() {
  const router = useRouter();
  const { state, dispatch } = useApp();
  const choose = useMutation({
    mutationFn: (role: "OWNER" | "STAFF") => chooseRole(role, state.token!),
    onSuccess: (s) => {
      dispatch({ type: "SET_AUTH", token: s.token, role: s.user.role, userId: s.user.user_id, storeId: s.user.store_id ?? null });
      router.replace(s.user.role === "OWNER" ? "/owner/intent" : "/staff/pending");
    },
  });

  useEffect(() => {
    if (!state.hydrated) return;
    if (!state.token) router.replace("/");
    else if (state.role) router.replace(state.role === "OWNER" ? "/owner/upload" : "/staff/roadmap");
  }, [state.hydrated, state.token, state.role, router]);

  return (
    <Shell>
      <div className="flex flex-1 flex-col justify-center gap-4 px-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <Buddy size={96} />
          <h1 className="text-xl font-bold">어떤 분이세요?</h1>
          <p className="text-sm text-muted">한 번만 고르면 돼요.</p>
        </div>
        <Button className="w-full" loading={choose.isPending && choose.variables === "OWNER"} loadingLabel="설정 중"
          disabled={choose.isPending} onClick={() => choose.mutate("OWNER")}>사장님이에요</Button>
        <Button className="w-full" loading={choose.isPending && choose.variables === "STAFF"} loadingLabel="설정 중"
          disabled={choose.isPending} onClick={() => choose.mutate("STAFF")}>알바생이에요</Button>
        {choose.error && <p role="alert" className="text-center text-xs text-danger-500">{apiErrorMessage(choose.error, "설정하지 못했어요.")}</p>}
      </div>
    </Shell>
  );
}
```

  `api.ts`에 `chooseRole(role, token)` → `fetchJson<SessionResponse>("/auth/role", { method: "POST", headers: authHeader(token), body: JSON.stringify({ role }) })`. 409(`ROLE_ALREADY_SET`)면 `refreshSession()` 후 bootstrap 목적지로 보낸다(다른 탭에서 이미 고른 경우).
  `store.tsx`의 `SET_AUTH` 액션 타입에서 `role: Role`을 `role: Role | null`로.

- [ ] **Step 6b: 옛 경로 정리**
  - `web/app/role/page.tsx`, `web/app/owner/auth/page.tsx`, `web/app/staff/auth/page.tsx`를 각각 `/`로 보내는 페이지로 바꾼다(쿼리 `next` 유지). 설치된 앱의 시작 주소가 `/role`이라 경로는 남긴다.

```tsx
import { redirect } from "next/navigation";

export default async function LegacyAuthRedirect({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  redirect(next ? `/?next=${encodeURIComponent(next)}` : "/");
}
```

  `owner/auth`·`staff/auth`는 레이아웃 가드 안에 있으므로, 가드보다 먼저 서버에서 redirect되는지 브라우저로 확인한다. 안 되면 `next.config`의 `redirects()`에 세 경로를 추가하는 방식으로 바꾼다.
  - `href="/role"`을 쓰는 곳(`owner/intent`, `staff/roadmap`, `owner-page-header`의 "나가기")은 Figma 마이페이지 때 정리하므로 이번에는 그대로 둔다(redirect로 동작은 유지된다).

- [ ] **Step 7: 정적 검사** — `pnpm check` → 통과(Task 14의 `createInvite` 정리 전이면 그 오류만 남는다).

---

### Task 14: 점주 직원 관리 화면

결정(2026-10-03): 로그아웃 버튼·마이페이지·상시 진입점은 Figma 수령 후 프론트 연동 때 만든다. 이번에는 화면 본체와 알림·온보딩 진입만 둔다.
공유는 **카카오 SDK 카드 메시지가 기본**이고, SDK를 쓸 수 없으면 Web Share, 그것도 없으면 복사로 대신한다.

**Files:**
- Modify: `web/lib/api.ts` (`createInvite` 제거, 새 함수), `web/lib/query.ts`
- Create: `web/lib/kakao-share.ts`, `web/components/invite-link-card.tsx`, `web/app/owner/members/page.tsx`
- Modify: `web/app/owner/complete/page.tsx`, `web/.env.example`

**Interfaces:**
- Produces: `getInviteLink(token, signal)`, `rotateInviteLink(token)`, `listMembers(token, signal)`, `approveJoin(id, token)`, `rejectJoin(id, token)`, `removeMember(userId, token)`; 타입 `MembersResponse = { pending: { request_id: number; name: string; requested_at: string }[]; active: { user_id: number; name: string; role: "OWNER" | "STAFF"; joined_at: string }[] }`; `inviteLinkQuery(token, storeId)`, `membersQuery(token, storeId)`; `<InviteLinkCard />`; `shareInviteViaKakao(p: { url: string; storeName: string }): Promise<boolean>` (SDK로 보냈으면 true)

- [ ] **Step 1: API·쿼리** — `createInvite` 삭제 후:

```ts
export type MembersResponse = {
  pending: { request_id: number; name: string; requested_at: string }[];
  active: { user_id: number; name: string; role: "OWNER" | "STAFF"; joined_at: string }[];
};

export async function getInviteLink(token: string, signal?: AbortSignal) {
  return fetchJson<{ url: string }>("/members/invite-link", { headers: authHeader(token), signal });
}
export async function rotateInviteLink(token: string) {
  return fetchJson<{ url: string }>("/members/invite-link/rotate", { method: "POST", headers: authHeader(token) });
}
export async function listMembers(token: string, signal?: AbortSignal) {
  return fetchJson<MembersResponse>("/members", { headers: authHeader(token), signal });
}
export async function approveJoin(requestId: number, token: string) {
  return fetchJson<void>(`/members/requests/${requestId}/approve`, { method: "POST", headers: authHeader(token) });
}
export async function rejectJoin(requestId: number, token: string) {
  return fetchJson<void>(`/members/requests/${requestId}/reject`, { method: "POST", headers: authHeader(token) });
}
export async function removeMember(userId: number, token: string) {
  return fetchJson<void>(`/members/${userId}/remove`, { method: "POST", headers: authHeader(token) });
}
```

  `query.ts`: `queryKeys.inviteLink(storeId)` `["invite-link", storeId]`, `queryKeys.members(storeId)` `["members", storeId]`; `inviteLinkQuery`·`membersQuery`(`refetchInterval: 30_000` — 승인 대기 목록 갱신, D6).

- [ ] **Step 1a: 카카오 공유 모듈** — `web/lib/kakao-share.ts`

  SDK 버전과 SRI 값은 카카오 공식 문서(https://developers.kakao.com/docs/latest/ko/javascript/getting-started)의 "SDK 설치" 최신 값을 그대로 복사해 아래 두 상수에 넣는다(추측해서 쓰지 않는다).

```ts
// 카카오톡 카드 메시지로 초대 링크를 보낸다. 로그인에는 쓰지 않는다(로그인은 서버 흐름).
// JavaScript 키는 공개 전제의 키다. 카카오 콘솔에 등록한 도메인에서만 동작한다.
const SDK_URL = "https://t1.kakaocdn.net/kakao_js_sdk/<공식 문서 버전>/kakao.min.js";
const SDK_INTEGRITY = "<공식 문서 integrity 값>";
const JS_KEY = process.env.NEXT_PUBLIC_KAKAO_JS_KEY ?? "";

type KakaoSdk = {
  isInitialized(): boolean;
  init(key: string): void;
  Share: { sendDefault(options: Record<string, unknown>): void };
};
declare global { interface Window { Kakao?: KakaoSdk } }

let loading: Promise<KakaoSdk | null> | null = null;

function loadSdk(): Promise<KakaoSdk | null> {
  if (!JS_KEY || typeof window === "undefined") return Promise.resolve(null);
  if (window.Kakao) return Promise.resolve(window.Kakao);
  loading ??= new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = SDK_URL;
    script.integrity = SDK_INTEGRITY;
    script.crossOrigin = "anonymous";
    script.onload = () => resolve(window.Kakao ?? null);
    // 차단·오프라인이면 Web Share 로 넘어간다
    script.onerror = () => { loading = null; resolve(null); };
    document.head.appendChild(script);
  });
  return loading;
}

export async function shareInviteViaKakao(p: { url: string; storeName: string }): Promise<boolean> {
  const kakao = await loadSdk();
  if (!kakao) return false;
  try {
    if (!kakao.isInitialized()) kakao.init(JS_KEY);
    const link = { mobileWebUrl: p.url, webUrl: p.url };
    kakao.Share.sendDefault({
      objectType: "feed",
      content: {
        title: `${p.storeName}에서 초대했어요`,
        description: "AskBuddy로 매장 업무를 배워요. 눌러서 합류하세요.",
        imageUrl: new URL("/images/buddy-hero.png", window.location.origin).href,
        link,
      },
      buttons: [{ title: "합류하기", link }],
    });
    return true;
  } catch {
    return false;
  }
}
```

  `web/.env.example`에 `NEXT_PUBLIC_KAKAO_JS_KEY=` 한 줄 추가(인라인 주석 금지, 설명은 윗줄 주석으로 `# 카카오톡 초대 공유용 JavaScript 키. 공개 키이며 로그인에는 쓰지 않는다`). 키가 비어 있으면 SDK를 불러오지 않고 바로 Web Share로 간다 — 로컬 개발은 키 없이 돈다.

- [ ] **Step 2: 초대 링크 카드**

```tsx
"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui";
import { apiErrorMessage, rotateInviteLink } from "@/lib/api";
import { shareInviteViaKakao } from "@/lib/kakao-share";
import { bootstrapQuery, inviteLinkQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

// 링크는 내부 토큰을 담고 있다. 화면에는 링크 자체를 보여 주지 않고 복사·공유만 한다
export function InviteLinkCard() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const link = useQuery(inviteLinkQuery(state.token, state.storeId));
  // 가드가 이미 불러 둔 bootstrap 캐시에서 매장명을 읽는다(추가 요청 없음)
  const storeName = useQuery(bootstrapQuery(state.token, state.userId, state.storeId)).data?.store?.store_name;
  const [notice, setNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const rotate = useMutation({
    mutationFn: () => rotateInviteLink(state.token!),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.inviteLink(state.storeId), data);
      setConfirming(false);
      setNotice("새 링크를 만들었어요. 이전 링크는 더 이상 쓸 수 없어요.");
    },
  });

  async function copy() {
    if (!link.data) return;
    try {
      await navigator.clipboard.writeText(link.data.url);
      setNotice("링크를 복사했어요.");
    } catch {
      setNotice("복사하지 못했어요. 공유 버튼을 써 주세요.");
    }
  }

  async function share() {
    if (!link.data) return;
    // 1) 카카오 카드 메시지 2) 휴대폰 공유창 3) 복사
    if (await shareInviteViaKakao({ url: link.data.url, storeName: storeName ?? "우리 매장" })) return;
    if (navigator.share) {
      try {
        await navigator.share({ title: "AskBuddy 합류 초대", text: "매장 합류 링크예요.", url: link.data.url });
        return;
      } catch {
        // 사용자가 공유 창을 닫았다
        return;
      }
    }
    await copy();
  }

  return (
    <section className="rounded-2xl bg-surface p-4 shadow-sm">
      <h2 className="text-sm font-bold text-foreground">초대 링크</h2>
      <p className="mt-1 text-xs text-muted">알바생에게 보내 주세요. 가입하면 여기서 승인할 수 있어요.</p>
      {link.isPending && <p role="status" className="mt-3 text-xs text-muted">링크를 준비하고 있어요…</p>}
      {link.isError && (
        <div className="mt-3 flex items-center gap-2">
          <p role="alert" className="text-xs text-danger-500">{apiErrorMessage(link.error, "링크를 불러오지 못했어요.")}</p>
          <Button onClick={() => void link.refetch()}>다시 시도</Button>
        </div>
      )}
      {link.data && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Button onClick={() => void copy()}>링크 복사</Button>
          <Button onClick={() => void share()}>카톡으로 보내기</Button>
        </div>
      )}
      <p className="mt-2 min-h-4 text-xs text-muted" role="status" aria-live="polite">{notice}</p>
      {!confirming ? (
        <button type="button" className="text-xs font-bold text-muted underline" onClick={() => setConfirming(true)} disabled={!link.data}>
          링크 새로 만들기
        </button>
      ) : (
        <div className="mt-1 rounded-xl bg-surface-muted p-3 text-xs">
          <p>새로 만들면 지금 링크로는 더 이상 가입할 수 없어요. 이미 들어온 요청은 그대로 남아요.</p>
          <div className="mt-2 flex gap-2">
            <Button loading={rotate.isPending} loadingLabel="만드는 중" onClick={() => rotate.mutate()}>새로 만들기</Button>
            <Button onClick={() => setConfirming(false)}>취소</Button>
          </div>
          {rotate.error && <p role="alert" className="mt-1 text-danger-500">{apiErrorMessage(rotate.error, "새 링크를 만들지 못했어요.")}</p>}
        </div>
      )}
    </section>
  );
}
```

  `Button`의 variant prop(보조 버튼 모양)이 있으면 `취소`·`링크 복사`에 맞춘다(`ui.tsx` 확인).

- [ ] **Step 3: 직원 관리 화면** — `web/app/owner/members/page.tsx`

```tsx
"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Shell, TopBar } from "@/components/ui";
import { InviteLinkCard } from "@/components/invite-link-card";
import { apiErrorMessage, approveJoin, rejectJoin, removeMember } from "@/lib/api";
import { membersQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

function kst(iso: string) {
  return new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function OwnerMembersPage() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const members = useQuery(membersQuery(state.token, state.storeId));
  const [removing, setRemoving] = useState<{ user_id: number; name: string } | null>(null);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.members(state.storeId) });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) =>
      approve ? approveJoin(id, state.token!) : rejectJoin(id, state.token!),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: (userId: number) => removeMember(userId, state.token!),
    onSuccess: () => setRemoving(null),
    onSettled: invalidate,
  });

  return (
    <Shell>
      <TopBar title="직원 관리" backHref="/owner/upload" />
      <div className="space-y-4 px-4 pb-8">
        <InviteLinkCard />

        <section className="rounded-2xl bg-surface p-4 shadow-sm">
          <h2 className="text-sm font-bold">승인 대기 {members.data ? `(${members.data.pending.length})` : ""}</h2>
          {members.isPending && <p role="status" className="mt-2 text-xs text-muted">불러오는 중…</p>}
          {members.isError && (
            <div className="mt-2 flex items-center gap-2">
              <p role="alert" className="text-xs text-danger-500">{apiErrorMessage(members.error, "목록을 불러오지 못했어요.")}</p>
              <Button onClick={() => void members.refetch()}>다시 시도</Button>
            </div>
          )}
          {members.data?.pending.length === 0 && <p className="mt-2 text-xs text-muted">기다리는 요청이 없어요.</p>}
          <ul className="mt-2 divide-y divide-border">
            {members.data?.pending.map((r) => (
              <li key={r.request_id} className="flex items-center gap-2 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-bold">{r.name}</p>
                  <p className="text-xs text-muted">{kst(r.requested_at)} 요청</p>
                </div>
                <Button loading={decide.isPending && decide.variables?.id === r.request_id} loadingLabel="처리 중"
                  onClick={() => decide.mutate({ id: r.request_id, approve: true })}>승인</Button>
                <Button disabled={decide.isPending} onClick={() => decide.mutate({ id: r.request_id, approve: false })}>거절</Button>
              </li>
            ))}
          </ul>
          {decide.error && <p role="alert" className="text-xs text-danger-500">{apiErrorMessage(decide.error, "처리하지 못했어요.")}</p>}
        </section>

        <section className="rounded-2xl bg-surface p-4 shadow-sm">
          <h2 className="text-sm font-bold">함께 일하는 직원 {members.data ? `(${members.data.active.filter((m) => m.role === "STAFF").length})` : ""}</h2>
          {members.data && members.data.active.filter((m) => m.role === "STAFF").length === 0 && (
            <p className="mt-2 text-xs text-muted">아직 합류한 직원이 없어요. 초대 링크를 보내 보세요.</p>
          )}
          <ul className="mt-2 divide-y divide-border">
            {members.data?.active.filter((m) => m.role === "STAFF").map((m) => (
              <li key={m.user_id} className="flex items-center gap-2 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-bold">{m.name}</p>
                  <p className="text-xs text-muted">{kst(m.joined_at)} 합류</p>
                </div>
                <button type="button" className="min-h-11 px-2 text-xs font-bold text-danger-500" onClick={() => setRemoving(m)}>내보내기</button>
              </li>
            ))}
          </ul>
        </section>

        {removing && (
          <div role="dialog" aria-modal="true" className="fixed inset-0 z-20 flex items-end justify-center bg-black/40 p-4">
            <div className="w-full max-w-sm rounded-2xl bg-surface p-5">
              <p className="text-sm font-bold">{removing.name}님을 내보낼까요?</p>
              <p className="mt-1 text-xs text-muted">바로 앱을 쓸 수 없게 돼요. 질문·학습 기록은 남아요. 다시 초대하면 이어서 쓸 수 있어요.</p>
              {remove.error && <p role="alert" className="mt-2 text-xs text-danger-500">{apiErrorMessage(remove.error, "내보내지 못했어요.")}</p>}
              <div className="mt-4 grid grid-cols-2 gap-2">
                <Button onClick={() => setRemoving(null)}>취소</Button>
                <Button loading={remove.isPending} loadingLabel="처리 중" onClick={() => remove.mutate(removing.user_id)}>내보내기</Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Shell>
  );
}
```

  `backHref`는 점주의 기본 화면이다. `bootstrap.default_destination`이 `/owner/questions/v2`일 수도 있으니, 이 화면은 `TopBar`의 `onBack`으로 `router.back()`을 쓰지 말고 `/owner/upload`(업로드 탭, 항상 존재)로 고정한다.

- [ ] **Step 4: 진입점**
  - `owner/complete/page.tsx`: `createInvite`·`code`·`copyCode`를 지우고 버튼 자리에 `<InviteLinkCard />`.
  - 알림 목록의 `JOIN_REQUESTED` 항목은 destination(`/owner/members`)으로 이동한다. `web/app/owner/notifications/page.tsx`와 `r-v2-notifications.tsx`가 `event_type`별로 아이콘·문구를 분기하는지 `grep -n "event_type\|OWNER_ANSWER" web/app/owner/notifications/page.tsx web/components/r-v2-notifications.tsx`로 확인하고, 분기가 있으면 `JOIN_REQUESTED: "👋"`를 추가한다.
  - 헤더(`owner-page-header.tsx`)의 "나가기"·상시 진입 아이콘은 손대지 않는다(Figma 마이페이지 때).

- [ ] **Step 5: 정적 검사** — `cd web && pnpm check` → 통과(이제 `createInvite` 참조 0).

---

### Task 15: 화면 검증과 카카오 실연결

**Files:** 없음(검증). 결과는 사용자 보고로만 남긴다.

- [ ] **Step 1: `web-async-state-check` 스킬** — `lib/api.ts` 갱신 로직, `/auth/complete`·`/staff/pending`·`/owner/members`의 query·mutation.
- [ ] **Step 2: `ui-state-walkthrough` 스킬** — 로컬(`supabase start`, API `AUTH_COOKIE_SECURE=false`, `pnpm dev`)에서 아래를 실제로 확인한다. 실패 경로를 일부러 만든다.
  - `/` 단일 로그인 화면: 카카오 키 없는 로컬에서는 이메일 버튼만, 로그인된 상태로 `/` 열면 바로 자기 화면으로
  - 이메일 신규 가입 → `/auth/role` → 사장님 → `/owner/intent` / 알바생 → `/staff/pending`. 역할 고른 뒤 `/auth/role` 다시 열면 자기 화면으로
  - 알바로 로그인한 채 `/owner/upload` 주소 입력 → 로그아웃 없이 알바 화면으로
  - 설치 앱 시작 주소 `/role`, 옛 `/owner/auth?next=...` → `/`로 이동하고 `next` 유지
  - 새로고침 후에도 로그인 유지(쿠키 → refresh), DevTools Application에서 `ab_refresh`가 HttpOnly인지
  - API를 끈 채 새로고침 → 로그인 화면이 아니라 재시도 화면, API 켜고 재시도 → 원래 화면
  - 두 탭 동시 새로고침 → 둘 다 로그인 유지
  - access token 만료(로컬 `.env`에 `ACCESS_TOKEN_EXPIRE_MINUTES=5`로 두고 5분 대기) → 화면 데이터 유지, 요청 자동 재시도
  - 초대 링크 무효 토큰 → 안내 화면, 링크 재생성 후 이전 링크 → 안내 화면
  - 알바 카카오/이메일 가입(초대 없이) → `/staff/pending` "아직 합류한 매장이 없어요", 매장 화면 URL 직접 입력해도 대기 화면으로
  - 로그인된 알바가 초대 링크를 연다 → 바로 "합류 요청을 보내는 중" → 대기 화면, 점주 알림 도착
  - 로그아웃 상태로 초대 링크 → 카카오 한 번으로 가입·요청, 이메일 로그인/가입 후에도 요청이 자동으로 간다
  - 대기 화면에서 [승인되면 알림 받기] → 점주 승인 → 알바 기기에 알림, 열린 대기 화면은 새로고침 없이 로드맵으로(데스크톱 Chrome에서 확인 가능). 알림 권한 거부 상태에서는 다른 탭 갔다가 돌아오면 반영
  - 점주로 로그인된 브라우저에서 초대 링크 → 역할 충돌 안내
  - 거절 → 거절 안내, 내보내기 → 알바 화면이 다음 요청에서 로그인/대기 화면으로
  - `POST /auth/logout`을 curl로 호출한 뒤 새로고침 → 로그인 화면(로그아웃 버튼 UI는 이번 범위 아님)
- [ ] **Step 3: 카카오 실연결(사용자 준비 필요)** — 사용자가 카카오 개발자 콘솔에서 테스트 앱을 만들고(설계 §6) 로컬 `.env`에 `KAKAO_REST_API_KEY`, `KAKAO_CLIENT_SECRET`, `KAKAO_REDIRECT_URI=http://localhost:8000/auth/kakao/callback`, `WEB_BASE_URL=http://localhost:3000`, `AUTH_COOKIE_SECURE=false`를 넣는다. 확인: `/`에서 카카오 신규 가입 → `/auth/role` → 사장님 → `/owner/intent`, 재로그인은 역할 선택 없이 바로, 다른 카카오 계정 신규 → 알바생 → 대기 "매장 없음", 알바 링크 → 카카오 → 대기, 점주 계정으로 링크 열기 → `ROLE_CONFLICT` 문구, 동의 화면 취소 → `KAKAO_CANCELLED` 문구. 휴대폰 카카오톡에서 링크를 열어 인앱 브라우저 흐름도 한 번 확인한다(Push는 인앱 브라우저에서 오지 않는 것이 정상).
- [ ] **Step 4: 보고** — 자동 테스트(API pytest), 정적 검사(`pnpm check`), 브라우저 확인, 카카오 실연결을 **구분해서** 적는다. 하지 못한 항목은 하지 못했다고 쓴다.

---

## 운영 반영 (사용자 실행, 이 계획 범위 밖)

1. PR 머지 → 자동 배포(migration·서버)
2. 카카오 콘솔: 운영 Redirect URI `https://api.askbuddy.kr/auth/kakao/callback`, 플랫폼 도메인 `https://askbuddy.kr`
3. EC2 env 파일에 설계 §6 변수 추가(`AUTH_COOKIE_SECURE=true`, `WEB_BASE_URL=https://askbuddy.kr`) → 재시작
4. `docs/release/DEPLOY_ACCESS_SETUP.md`에 카카오 env 행 추가(release 문서는 사용자 요청 시 수정)
5. 공지: 배포 직후 전원 1회 재로그인, 점주는 직원 관리에서 새 초대 링크 공유
