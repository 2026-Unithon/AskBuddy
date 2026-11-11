# 계획 9: DB 정리, 매장 파기 기반, AWS 운영 도구

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 쓰지 않는 칸과 같은 값을 두 곳에 두는 칸을 없애고, 사장님 탈퇴 30일 뒤 그 매장의 모든 행과 파일을 지우는 기반을 만든다. 원가 장부만 남긴다. AWS Budgets, Parameter Store, CloudWatch, SES를 붙인다.

**Architecture:** 네 묶음이고 묶음마다 migration이 하나다.
- 9A 죽은 칸 정리: 칸을 지우고 그 칸을 읽고 쓰던 코드를 같이 지운다.
- 9B 제약 보강: 지금 코드가 지키고 있는 규칙을 DB 제약으로 옮긴다.
- 9C 파기 기반: 불변 트리거에 "파기 중인 매장이면 건너뛴다"는 조건(`WHEN`)을 붙이고, Python이 정해진 순서로 표를 비운다. 트리거 함수 본문은 고치지 않는다.
- 9D AWS: 서버 밖 설정이 대부분이라 사용자가 콘솔에서 하는 단계와 저장소에 들어가는 파일을 나눠 적는다.

**Tech Stack:** PostgreSQL 15(로컬 검증은 일회용 pg17 `plan7-pg`), FastAPI, asyncpg, pytest, Docker Compose, AWS CLI.

**Spec:** 2026-11-10 대화의 사용자 결정(아래 표)과 `docs/dev/ASKBUDDY_MVP_CURRENT.md`.

## 사용자 결정 (2026-11-10)

| # | 결정 |
|---|---|
| 1 | 불변(지우지 않는다)은 **매장이 활성인 동안**의 규칙이다. 사장님이 탈퇴하면 30일 뒤 다 지운다 |
| 2 | 남기는 것은 원가 계측에 필요한 최소한뿐이다 |
| 3 | 실수에 가까운 설계는 다 고친다 |
| 4 | Budgets, CloudWatch, Parameter Store, SES를 모두 넣는다 |
| 5 | 순서: Budgets → 9A → 9B → 9C → (Parameter Store, CloudWatch) → 계획 8 → SES → 약관 |

## 계획을 쓰며 내가 정한 것 (사용자 확인 필요)

| # | 정한 것 | 이유 | 틀렸을 때 비용 |
|---|---|---|---|
| R1 | 원가 장부(`ai_usage_attempts`, `cost_assessments`)는 **한 줄도 고치지 않는다.** 앞서 "source_id, job_id를 비운다"고 했던 말을 거둔다 | 장부의 `job_id`, `source_id`, `question_id`는 FK가 없는 숫자다. 가리키던 행이 사라지면 아무것도 가리키지 않는다. 글자 칸(`logical_call_id`, `operation_id`)은 `index:12:embed`, 해시 같은 기계 값이다. 고치려면 장부 동결 트리거를 풀어야 해서 위험만 는다 | 장부에 사람 글이 섞여 있었다면 남는다. Task 6 Step 1 테스트가 칸 목록을 고정해 새 칸이 생기면 실패한다 |
| R2 | `stores` 행은 지우지 않고 **비운다**(이름 '삭제된 매장', 주소 슬러그 없음, 사장님 연결 없음) | 장부가 `stores`를 RESTRICT FK로 가리킨다. 장부를 남기려면 매장 번호가 있어야 한다 | 없음. 매장 번호만으로는 누구인지 알 수 없다 |
| R3 | 파기 기한은 `stores.purge_due_at` 한 칸에 둔다. 계획 8의 `users.withdrawal_due_at`은 만들지 않는다 | 같은 날짜를 두 표에 두면 9A에서 지우는 것과 같은 종류의 중복이다. 30일이라는 숫자는 `config.py`에만 있고 DB는 날짜만 본다 | 계획 8 Task 7의 조회가 `stores`를 거친다(이미 반영) |
| R4 | `upload_change_proposal_facts.conflict_fact_ids`, `affected_card_ids` 배열은 그대로 둔다. 앞서 말한 "자식 표로 쪼개기"는 하지 않는다 | 쓰기만 하고 읽는 앱 코드가 없다. 계산 결과를 찍어 둔 기록이다 | 나중에 이 값으로 조회할 일이 생기면 그때 쪼갠다 |
| R5 | `is_verified`는 지우지 않고 CHECK만 건다 | 이미 트리거가 `review_status`와 맞추고 있고 R 쪽 코드가 이 칸을 읽는다 | 중복 칸이 남는다. 지우려면 R 담당과 맞춰야 한다 |
| R6 | 알바생이 다른 매장에도 속해 있으면 그 사용자 행은 지우지 않는다 | 다른 매장의 기록이 그 사람을 가리킨다 | 없음 |

## R 담당과 맞춰야 하는 것 (Task 5, Task 6을 시작하기 전)

- `r_answer_citations`, `r_answer_receipts`, `r_owner_answer_deliveries`, `r_owner_answer_revisions`, `r_search_lexicons`, `r_index_documents`, `owner_answers`의 불변 트리거에 `WHEN` 조건이 붙는다. 함수 본문은 그대로다.
- `api/scripts/verify_r_*.py` 중 `knowledge_cards`에 `title`, `content`를 넣는 fixture 3개가 바뀐다(Task 3).
- 맞추기 전에는 Task 3, 5, 6을 시작하지 않는다. Task 1, 2, 4는 W 범위라 먼저 한다.

## Global Constraints

- migration 파일 이름과 순서(모두 계획 8의 `20261110120000_settings_account.sql`보다 앞):
  - `20261110090000_drop_dead_columns.sql`
  - `20261110093000_card_text_single_source.sql`
  - `20261110100000_role_and_verified_constraints.sql`
  - `20261110110000_store_purge.sql`
- migration을 더한 뒤에는 `docker exec plan7-pg psql -U postgres -c "drop database if exists plan7_template"`로 틀을 지워야 새 스키마가 잡힌다.
- 검증 명령의 DB 주소: `PLAN7_TEST_DB_URL=postgresql://postgres:synthetic-local-test@127.0.0.1:55439/postgres`
- `tests/test_migration_versions.py`, `python scripts/verify_r_schema_rebuild.py`가 통과해야 한다.
- 매장 격리: 새 쿼리는 `store_id` 필수 인자, `WHERE store_id = ?`. 사용자 단위 쿼리는 `# store-isolation-ok: <사유>`. 끝낼 때 `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/bootstrap api/app/learn api/app/ingest api/app/cards` 위반 수가 시작 전과 같아야 한다.
- 30일은 `api/app/config.py`의 `withdrawal_grace_days` 하나에만 적는다. SQL에 `interval '30 days'`를 새로 쓰지 않는다.
- D5: `is_sensitive`, `dek_encrypted`는 읽지도 쓰지도 않는다. 파기 때도 건드리지 않는다.
- `db/001_init_schema.sql`, `db/data/*`는 과거 기록이라 고치지 않는다. `docs/release/`는 읽지도 고치지도 않는다.
- 운영 DB, 배포판, 실데이터를 건드리지 않는다. AWS 콘솔과 운영 서버에서 하는 단계는 **사용자가** 한다. 커밋하지 않는다.
- 주석은 한국어. 평가 자료의 상호, 메뉴 이름을 fixture에 쓰지 않는다.

## Review Focus

1. 활성 매장에서 `askbuddy.purge_store_id`만 설정하면 불변 행이 지워지면 안 된다(Task 5 `test_guc_alone_does_not_bypass`).
2. 유예 29일째에는 파기가 거절돼야 한다(Task 5 `test_bypass_refused_before_due`, Task 6 `test_purge_refuses_before_due`).
3. 새 표가 생겼는데 파기 목록에 넣지 않으면 그 표의 행이 남는다(Task 6 `test_every_table_is_classified`).
4. 한 매장을 지우다 다른 매장 행이 지워지면 안 된다(Task 6 `test_other_store_untouched`).
5. Storage 파일을 못 지웠는데 DB 행만 지워지면 파일을 찾을 길이 없어진다. 파일을 먼저 지우고, 실패하면 DB는 손대지 않는다(Task 7 `test_storage_failure_keeps_db`).

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `supabase/migrations/20261110090000_drop_dead_columns.sql` | 죽은 칸 5개 삭제 |
| `supabase/migrations/20261110093000_card_text_single_source.sql` | `knowledge_cards.title`, `content` 삭제 |
| `supabase/migrations/20261110100000_role_and_verified_constraints.sql` | 역할 복합 FK, `is_verified` CHECK |
| `supabase/migrations/20261110110000_store_purge.sql` | 탈퇴 칸, `askbuddy_purging`, 트리거 `WHEN` |
| `api/app/bootstrap/purge.py` (새) | `PURGE_ORDER`, `purge_store` |
| `api/app/ingest/preprocess/storage.py` | `delete_store_objects` |
| `api/app/config.py` | `withdrawal_grace_days` |
| `api/tests/test_plan9_schema_db.py` (새) | 9A, 9B 스키마 검사 |
| `api/tests/test_plan9_purge_db.py` (새) | 9C 파기 검사 |
| `deploy/render_env.py` (새), `deploy/remote_deploy.sh`, `deploy/compose.yml` | Parameter Store, CloudWatch |
| `api/app/bootstrap/feedback_mail.py` (새) | SES 알림 |
| `docs/dev/ASKBUDDY_MVP_CURRENT.md`, `CLAUDE.md` | D13, D20 문구 |

---

### Task 0: AWS Budgets (사용자가 콘솔에서, 지금 바로)

저장소 변경 없음. 다른 작업과 무관하게 먼저 한다.

- [ ] **Step 1:** AWS 콘솔 → Billing and Cost Management → Budgets → Create budget → Customize → **Cost budget**
- [ ] **Step 2:** Period `Monthly`, Renewal `Recurring`, Budgeting method `Fixed`. 금액은 지난달 청구액에 20%를 더한 값(달러). Scope는 `All AWS services`
- [ ] **Step 3:** 알림 세 개를 만든다. 받는 사람은 운영자 이메일
  - Actual 80%
  - Actual 100%
  - Forecasted 100%
- [ ] **Step 4:** Budgets 목록에 새 예산이 보이고, 확인 메일의 링크를 눌렀는지 본다.

D21의 월 3,000원은 AI와 Storage 변동비이고 EC2 고정비는 빠져 있다. 이 예산은 AWS 청구 전체를 보는 별도 안전장치다.

---

### Task 1 (9A): 죽은 칸 5개 삭제

지우는 칸: `store_members.day_count`, `progress_rate`, `is_deployable`, `stores.knowledge_coverage`, `deploy_threshold`. 게이지 80% 게이트를 버린 뒤(CLAUDE.md '프로젝트') 화면 어디에서도 쓰지 않는다.

**Files:**
- Create: `supabase/migrations/20261110090000_drop_dead_columns.sql`, `api/tests/test_plan9_schema_db.py`
- Modify: `api/app/learn/router.py:375-428`(`GET /learn/staff` 삭제), `:1264`, `:1298-1304`
- Modify: `api/app/learn/roadmap.py:174-193`(`update_member_rate` 삭제)
- Modify: `api/app/auth/router.py:219`, `api/app/members/repository.py:77`, `api/scripts/demo_seed.py:110,125`, `db/002_seed_demo.sql:22-31`(insert에서 칸 이름과 값 빼기)
- Modify: `web/lib/api.ts:376-384`(`patchRoadmapItem`), `:1167-1180`(`LearnStaffItem`, `listStaff`), `web/lib/query.ts:128`(`queryKeys.staff`), `:298-304`(`staffQuery`) 삭제

**Interfaces — Produces:** PATCH `/roadmap/items/{item_id}` 응답에서 `progress_rate`가 빠진다. 그 밖의 응답은 그대로.

- [ ] **Step 1: 실패하는 테스트**

```python
"""계획 9: 스키마 정리. 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest
from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

DEAD = [("store_members", "day_count"), ("store_members", "progress_rate"), ("store_members", "is_deployable"),
        ("stores", "knowledge_coverage"), ("stores", "deploy_threshold")]


async def columns(conn):
    return {(r["table_name"], r["column_name"]) for r in await conn.fetch(
        "select table_name, column_name from information_schema.columns where table_schema = 'public'")}


@unittest.skipUnless(ENABLED, SKIP_REASON)
class DeadColumnsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_dead_columns_are_gone(self):
        cols = await columns(self.conn)
        for pair in DEAD:
            self.assertNotIn(pair, cols)
```

같은 파일에 코드 검사를 더한다(DB 없이 돈다).

```python
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
LIVE = ["api/app", "api/scripts/demo_seed.py", "db/002_seed_demo.sql", "web/lib", "web/app", "web/components"]


class DeadNamesTest(unittest.TestCase):
    def test_no_live_code_names_dead_columns(self):
        names = ["day_count", "progress_rate", "is_deployable", "knowledge_coverage", "deploy_threshold", "update_member_rate", "listStaff", "staffQuery"]
        hits = []
        for entry in LIVE:
            base = ROOT / entry
            files = [base] if base.is_file() else [p for p in base.rglob("*") if p.suffix in (".py", ".ts", ".tsx", ".sql")]
            for path in files:
                text = path.read_text(encoding="utf-8")
                hits += [f"{path.relative_to(ROOT)}: {n}" for n in names if n in text]
        self.assertEqual(hits, [])
```

- [ ] **Step 2:** `cd api && PLAN7_TEST_DB_URL=… python -m pytest tests/test_plan9_schema_db.py -q`. Expected: 2 failed(`day_count`가 아직 있음, 이름 8종이 남아 있음)
- [ ] **Step 3: migration**

```sql
-- 계획 9A(2026-11-10): 게이지 80% 게이트를 버린 뒤 아무도 읽지 않는 칸
alter table store_members drop column if exists day_count;
alter table store_members drop column if exists progress_rate;
alter table store_members drop column if exists is_deployable;
alter table stores drop column if exists knowledge_coverage;
alter table stores drop column if exists deploy_threshold;
```

- [ ] **Step 4: 코드 삭제.** Files에 적은 곳을 지운다. `learn/router.py:1264`, `:1298`의 `update_member_rate` 호출 줄은 통째로 지우고, 그 반환값 `rate`를 쓰던 `"progress_rate": rate` 항목도 지운다.
- [ ] **Step 5:** 틀 DB를 지우고 `python -m pytest tests/test_plan9_schema_db.py -q`. Expected: 2 passed
- [ ] **Step 6:** `python -m pytest -q`(전체), `cd ../web && pnpm check`. Expected: 둘 다 오류 0. web은 정적 검사만 한 것으로 적는다.

---

### Task 2 (9B): 역할 복합 FK, `is_verified` CHECK

지금은 코드(`api/app/deps.py:89`, `api/app/bootstrap/router.py:74`)가 "멤버 역할과 사용자 역할이 같다"를 매 요청 확인한다. DB는 다른 값을 받아 준다.

**Files:** Create `supabase/migrations/20261110100000_role_and_verified_constraints.sql`. Test `api/tests/test_plan9_schema_db.py`(추가).

- [ ] **Step 1: 실패하는 테스트**

```python
@unittest.skipUnless(ENABLED, SKIP_REASON)
class ConstraintTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        # seed_store 가 FK 와 트리거를 꺼 두므로 다시 켠다
        await self.conn.execute("set session_replication_role = origin")
        self.staff = await self.conn.fetchval("insert into users (name, role) values ('알바', 'STAFF') returning user_id")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_member_role_must_match_user_role(self):
        with self.assertRaises(Exception):
            await self.conn.execute(
                "insert into store_members (store_id, user_id, member_role) values ($1, $2, 'OWNER')", self.store, self.staff)

    async def test_matching_role_is_accepted(self):
        await self.conn.execute(
            "insert into store_members (store_id, user_id, member_role) values ($1, $2, 'STAFF')", self.store, self.staff)

    async def test_user_role_cannot_change_under_a_membership(self):
        await self.conn.execute(
            "insert into store_members (store_id, user_id, member_role) values ($1, $2, 'STAFF')", self.store, self.staff)
        with self.assertRaises(Exception):
            await self.conn.execute("update users set role = 'OWNER' where user_id = $1", self.staff)

    async def test_verified_flag_cannot_disagree_with_status(self):
        # 트리거가 맞춰 주므로 트리거를 끈 채 어긋난 값을 넣어 본다
        await self.conn.execute("set session_replication_role = replica")
        with self.assertRaises(Exception):
            await self.conn.execute(
                "insert into knowledge_cards (store_id, review_status, is_verified) values ($1, 'PENDING', true)", self.store)
```

(Task 3을 아직 하지 않았다면 마지막 insert에 `title, content` 값 `'t', 'c'`를 더한다. Task 3 뒤에는 위 그대로다.)

- [ ] **Step 2:** 실행. Expected: `test_member_role_must_match_user_role`, `test_user_role_cannot_change_under_a_membership`, `test_verified_flag_cannot_disagree_with_status` 3 failed
- [ ] **Step 3: migration**

```sql
-- 계획 9B(2026-11-10): 코드가 매 요청 확인하던 규칙을 DB 가 지키게 한다
-- 어긋난 행이 있으면 여기서 멈춘다. 고칠 값을 사람이 정해야 하므로 자동으로 맞추지 않는다
do $$
begin
  if exists (select 1 from store_members m join users u using (user_id) where u.role is distinct from m.member_role) then
    raise exception '역할이 어긋난 멤버가 있다. store_members.member_role 과 users.role 을 먼저 맞춘다';
  end if;
  if exists (select 1 from knowledge_cards where is_verified is distinct from (review_status = 'APPROVED')) then
    raise exception 'is_verified 와 review_status 가 어긋난 카드가 있다';
  end if;
end $$;

alter table users add constraint users_user_id_role_key unique (user_id, role);
alter table store_members add constraint store_members_role_matches_user
  foreign key (user_id, member_role) references users (user_id, role);
alter table knowledge_cards add constraint knowledge_cards_verified_matches_status
  check (is_verified = (review_status = 'APPROVED'));
```

- [ ] **Step 4:** 틀 DB를 지우고 실행. Expected: 4 passed. 전체 pytest 통과.
- [ ] **Step 5: 배포 전 확인 쿼리를 계획 끝 '배포 순서'에 적어 둔다.** 운영 DB에서 사용자가 돌려 0건이어야 migration이 통과한다.

```sql
select count(*) from store_members m join users u using (user_id) where u.role is distinct from m.member_role;
select count(*) from knowledge_cards where is_verified is distinct from (review_status = 'APPROVED');
```

---

### Task 3 (9A): 카드 제목과 본문을 판(`card_versions`)에만 둔다

`knowledge_cards.title`, `content`는 초안 판의 사본이다. 쓰는 곳 세 군데가 판과 카드에 같은 글을 두 번 쓴다. 읽는 곳은 대부분 이미 판을 읽는다.

**Files:**
- Create: `supabase/migrations/20261110093000_card_text_single_source.sql`
- Modify(쓰기): `api/app/ingest/repository.py:219-236`(`insert_card`), `api/app/cards/fact_edit.py:193`, `api/app/ingest/fact_cards.py:312`
- Modify(읽기): `api/app/ingest/repository.py:402-409`(`get_card`, 호출하는 곳이 없어 삭제), `:518-546`(`list_review_cards`), `api/app/categories/worker.py:62-72`, `api/app/learn/router.py:1087`, `api/app/cards/fact_edit_repo.py:146`
- Modify(fixture): `api/tests/test_plan7_cards_db.py:12`, `test_plan7_category_kind.py:34`, `test_wa_insert_card.py:15`, `api/scripts/verify_cp04.py:62`, `verify_w_fact_only.py:534`, `verify_p7_integration.py:41`, `verify_checklist.py:43`, `_fact_card_fixture.py:148`, `verify_r_w3_consumer.py:63`, `verify_r_index.py:59`, `db/test_003_mvp_contract_v1.sql:82`, `db/test_003_legacy_fixture.sql:16`

**읽는 곳마다 어느 판을 읽는지**

| 곳 | 읽는 판 | 이유 |
|---|---|---|
| `list_review_cards` | `c.draft_version_id` | 사장님 검수 화면은 초안을 본다 |
| `categories/worker.py` | `coalesce(c.draft_version_id, c.published_version_id)` | 분류는 가장 최근 글로 한다 |
| `learn/router.py:1087` | `cv.title`(이미 join된 인용 판). `coalesce`의 `kc.title` 쪽만 뺀다 | 인용은 판을 RESTRICT FK로 가리켜 항상 있다 |
| `fact_edit_repo.py:146` | 같은 함수가 이미 읽어 둔 `version_id`의 판 제목 | 사실 편집은 초안 판을 고친다 |

- [ ] **Step 1: 실패하는 테스트**(`test_plan9_schema_db.py`에 추가)

```python
@unittest.skipUnless(ENABLED, SKIP_REASON)
class CardTextTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_card_has_no_text_columns(self):
        cols = await columns(self.conn)
        self.assertNotIn(("knowledge_cards", "title"), cols)
        self.assertNotIn(("knowledge_cards", "content"), cols)

    async def test_insert_card_writes_text_to_version_only(self):
        from app.ingest import repository
        card_id = await repository.insert_card(
            self.conn, store_id=self.store, category_id=None, source_id=None, title="마감 청소", content="바닥을 닦는다", confidence=70)
        row = await self.conn.fetchrow(
            "select v.title, v.content from knowledge_cards c join card_versions v "
            "on v.store_id = c.store_id and v.version_id = c.draft_version_id where c.store_id = $1 and c.card_id = $2",
            self.store, card_id)
        self.assertEqual((row["title"], row["content"]), ("마감 청소", "바닥을 닦는다"))

    async def test_review_list_reads_draft_version(self):
        from app.ingest import repository
        card_id = await repository.insert_card(
            self.conn, store_id=self.store, category_id=None, source_id=None, title="처음", content="처음 글", confidence=70)
        version = await self.conn.fetchval(
            "insert into card_versions (store_id, card_id, version_no, title, content, change_source) "
            "values ($1, $2, 2, '고친 제목', '고친 글', 'OWNER_EDIT') returning version_id", self.store, card_id)
        await self.conn.execute("update knowledge_cards set draft_version_id = $3 where store_id = $1 and card_id = $2", self.store, card_id, version)
        rows = await repository.list_review_cards(self.conn, self.store, verified=None, source_id=None, limit=10, offset=0)
        self.assertEqual([(r["title"], r["content"]) for r in rows], [("고친 제목", "고친 글")])
```

(`insert_card`, `list_review_cards`의 인자 이름은 지금 시그니처 그대로 맞춘다. 위치 인자면 위치로 넘긴다.)

- [ ] **Step 2:** 실행. Expected: `test_card_has_no_text_columns` FAIL, `test_review_list_reads_draft_version` FAIL(카드 칸의 '처음'을 읽음)
- [ ] **Step 3: 코드부터 고친다**(칸이 있는 동안에도 도는 순서). 쓰기 세 곳은 `knowledge_cards`의 insert, update에서 `title`, `content`를 뺀다. 읽기 네 곳은 위 표대로 판을 join한다. `ingest/repository.py`의 `get_card`는 지운다.
- [ ] **Step 4: migration**

```sql
-- 계획 9A(2026-11-10): 카드의 제목과 본문은 판(card_versions)에만 둔다
-- 판이 하나도 없는 옛 카드가 있으면 글을 잃지 않게 판 1 로 옮긴 뒤 지운다
insert into card_versions (store_id, card_id, version_no, title, content, change_source)
select c.store_id, c.card_id, 1, c.title, c.content, 'EXTRACTION'
from knowledge_cards c
where not exists (select 1 from card_versions v where v.store_id = c.store_id and v.card_id = c.card_id);

update knowledge_cards c set draft_version_id = v.version_id
from card_versions v
where c.draft_version_id is null and c.published_version_id is null
  and v.store_id = c.store_id and v.card_id = c.card_id and v.version_no = 1;

alter table knowledge_cards drop column if exists title;
alter table knowledge_cards drop column if exists content;
```

- [ ] **Step 5: fixture를 고친다.** Files의 12곳에서 `knowledge_cards` insert의 `title`, `content`를 빼고, 그 fixture가 글을 읽어야 하면 `card_versions`에 판을 넣는다. `change_source` 값은 그 파일이 이미 쓰는 값을 따른다.
- [ ] **Step 6:** 틀 DB를 지우고 `python -m pytest -q`. Expected: 전체 통과. 이어서 아래를 하나씩 돌린다. Expected: 모두 exit 0
  - `python scripts/verify_r_schema_rebuild.py`
  - `python scripts/verify_w_fact_only.py`
  - `python scripts/verify_p7_integration.py`
  - `python scripts/verify_checklist.py`
  - `python scripts/verify_cp04.py`
- [ ] **Step 7: 남은 읽기 확인.** 아래가 아무것도 출력하지 않아야 한다.

```bash
cd api && python3 - <<'EOF'
import glob, re
for f in sorted(glob.glob("app/**/*.py", recursive=True)):
    src = open(f, encoding="utf-8").read()
    for m in re.finditer(r"(?:from|join)\s+knowledge_cards\s+(?:as\s+)?([a-z]{1,3})\b", src):
        block = src[max(0, m.start() - 1200): m.end() + 1200]
        if re.search(rf"\b{m.group(1)}\.(title|content)\b", block):
            print(f, src.count("\n", 0, m.start()) + 1)
EOF
```

---

### Task 4: 문서의 '지우지 않는다'를 '활성인 동안'으로

**Files:** Modify `docs/dev/ASKBUDDY_MVP_CURRENT.md`(D13, D20이 적힌 절), `CLAUDE.md`(확정된 결정 표 D13, D20, 그리고 D22 한 줄 추가)

- [ ] **Step 1:** D13 끝에 한 문장을 더한다: `불변은 매장이 활성인 동안의 규칙이다. 매장 파기(D22)는 예외다.`
- [ ] **Step 2:** D20 끝에 더한다: `이 보존도 매장이 활성인 동안이다.`
- [ ] **Step 3:** D22를 새로 적는다.

```
| D22 | **사장님이 탈퇴하면 30일 뒤 그 매장을 파기한다.** 유예 동안 매장은 닫히고 사장님이 취소하면 다시 열린다. 기한이 지나면 그 매장의 모든 행과 Storage 파일을 지운다. 남기는 것은 원가 장부(ai_usage_attempts, cost_assessments)와 비운 stores 행뿐이다. 장부에는 사람 글이 없다. 유예 일수는 config.py 가 단일 출처다 |
```

- [ ] **Step 4:** `grep -n "D22" CLAUDE.md docs/dev/ASKBUDDY_MVP_CURRENT.md`. Expected: 두 파일 모두 1줄 이상

---

### Task 5 (9C): 탈퇴 칸, 파기 판정 함수, 트리거 `WHEN`

**방식.** 지움을 막는 트리거가 17개 표에 13개 함수로 걸려 있다. 함수 본문을 고치지 않고, 트리거를 "파기 중인 매장의 행이면 발동하지 않는다"는 `WHEN` 조건과 함께 다시 만든다. 파기 중인지는 두 가지가 모두 참일 때만 참이다.
1. 이 트랜잭션이 `askbuddy.purge_store_id`를 그 매장 번호로 설정했다.
2. 그 매장의 `purge_due_at`이 지났다.

설정만으로는 풀리지 않는다. 장부 트리거(`trg_usage_attempt_freeze`)는 건드리지 않는다.

**Files:** Create `supabase/migrations/20261110110000_store_purge.sql`, `api/tests/test_plan9_purge_db.py`. Modify `api/app/config.py`.

**Interfaces — Produces:**
- 칸: `stores.closing_at timestamptz`, `stores.purge_due_at timestamptz`, `stores.deleted_at timestamptz`, `users.deleted_at timestamptz`. `stores.owner_id`는 null 허용
- SQL 함수: `askbuddy_purging(p_store_id bigint) returns boolean`, `askbuddy_purging_question(p_question_id bigint) returns boolean`
- 설정: `Settings.withdrawal_grace_days: int = Field(default=30, ge=1, le=365)`

- [ ] **Step 1: 실패하는 테스트**

```python
"""계획 9C: 매장 파기. 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest
from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

GUARDED = ["evaluation_results", "evaluation_runs", "extraction_results", "extraction_runs", "fact_revision_meta",
           "fact_revisions", "knowledge_entity_events", "knowledge_snapshots", "owner_answers", "r_answer_citations",
           "r_answer_receipts", "r_index_documents", "r_owner_answer_deliveries", "r_owner_answer_revisions",
           "r_search_lexicons", "task_categories"]


async def seed_immutable(conn, store):
    """지움이 막힌 행 셋(사실 판, snapshot, 기본 카테고리). FK 는 꺼진 채다."""
    await conn.execute(
        "insert into fact_revisions (store_id, fact_id, entity_id, original_assertion, assertion) values ($1, 1, 1, '원문', '사실')", store)
    await conn.execute(
        "insert into knowledge_snapshots (store_id, knowledge_revision, snapshot_hash, glossary_version, renderer_version) "
        "values ($1, 1, 'h', 'g1', 'r1')", store)
    await conn.execute("insert into task_categories (store_id, category_name, is_system) values ($1, '기타', true)", store)


async def purge_mode(conn, store):
    await conn.execute("select set_config('askbuddy.purge_store_id', $1, true)", str(store))


@unittest.skipUnless(ENABLED, SKIP_REASON)
class PurgeGuardTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        await seed_immutable(self.conn, self.store)
        await self.conn.execute("set session_replication_role = origin")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_owner_id_is_nullable_and_columns_exist(self):
        rows = await self.conn.fetch(
            "select table_name, column_name, is_nullable from information_schema.columns where table_schema = 'public' "
            "and (table_name, column_name) in (('stores','owner_id'),('stores','closing_at'),('stores','purge_due_at'),"
            "('stores','deleted_at'),('users','deleted_at'))")
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r["is_nullable"] == "YES" for r in rows))

    async def test_every_delete_guard_has_the_purge_condition(self):
        rows = await self.conn.fetch(
            "select c.relname, pg_get_triggerdef(t.oid) as def from pg_trigger t join pg_class c on c.oid = t.tgrelid "
            "join pg_namespace n on n.oid = c.relnamespace where not t.tgisinternal and n.nspname = 'public' and (t.tgtype & 8) <> 0")
        guarded = {r["relname"] for r in rows if "askbuddy_purging" in r["def"]}
        unguarded = {r["relname"] for r in rows} - guarded
        self.assertEqual(guarded, set(GUARDED))
        # 장부만 조건 없이 남는다
        self.assertEqual(unguarded, {"ai_usage_attempts"})

    async def test_active_store_rows_stay_immutable(self):
        for table in ("fact_revisions", "knowledge_snapshots", "task_categories"):
            with self.assertRaises(Exception):
                await self.conn.execute(f"delete from {table} where store_id = $1", self.store)

    async def test_guc_alone_does_not_bypass(self):
        async with self.conn.transaction():
            await purge_mode(self.conn, self.store)
            self.assertFalse(await self.conn.fetchval("select askbuddy_purging($1)", self.store))
        with self.assertRaises(Exception):
            async with self.conn.transaction():
                await purge_mode(self.conn, self.store)
                await self.conn.execute("delete from fact_revisions where store_id = $1", self.store)

    async def test_bypass_refused_before_due(self):
        await self.conn.execute(
            "update stores set closing_at = now() - interval '29 days', purge_due_at = now() + interval '1 day' where store_id = $1", self.store)
        with self.assertRaises(Exception):
            async with self.conn.transaction():
                await purge_mode(self.conn, self.store)
                await self.conn.execute("delete from knowledge_snapshots where store_id = $1", self.store)

    async def test_bypass_after_due_only_for_that_store(self):
        other = await self.conn.fetchval(
            "insert into stores (store_name, business_type) values ('다른 합성 매장', 'CAFE') returning store_id")
        await self.conn.execute("set session_replication_role = replica")
        await seed_immutable(self.conn, other)
        await self.conn.execute("set session_replication_role = origin")
        await self.conn.execute(
            "update stores set closing_at = now() - interval '31 days', purge_due_at = now() - interval '1 day' where store_id = $1", self.store)
        async with self.conn.transaction():
            await purge_mode(self.conn, self.store)
            for table in ("fact_revisions", "knowledge_snapshots", "task_categories"):
                await self.conn.execute(f"delete from {table} where store_id = $1", self.store)
        with self.assertRaises(Exception):
            async with self.conn.transaction():
                await purge_mode(self.conn, self.store)
                await self.conn.execute("delete from fact_revisions where store_id = $1", other)

    async def test_bypass_does_not_leak_out_of_the_transaction(self):
        await self.conn.execute("update stores set closing_at = now(), purge_due_at = now() - interval '1 day' where store_id = $1", self.store)
        async with self.conn.transaction():
            await purge_mode(self.conn, self.store)
        self.assertFalse(await self.conn.fetchval("select askbuddy_purging($1)", self.store))
```

- [ ] **Step 2:** 실행. Expected: `test_active_store_rows_stay_immutable`만 통과, 나머지 6개 FAIL(칸, 함수가 없음)
- [ ] **Step 3: migration**

```sql
-- 계획 9C(2026-11-10): 사장님 탈퇴 30일 뒤 매장 파기(D22)
alter table stores alter column owner_id drop not null;
alter table stores add column if not exists closing_at timestamptz;
alter table stores add column if not exists purge_due_at timestamptz;
alter table stores add column if not exists deleted_at timestamptz;
alter table users add column if not exists deleted_at timestamptz;
alter table stores add constraint stores_purge_due_needs_closing
  check (purge_due_at is null or closing_at is not null);
create index if not exists stores_purge_due on stores (purge_due_at) where purge_due_at is not null and deleted_at is null;

-- 파기 중인가. 설정만으로는 참이 되지 않는다: 그 매장의 기한이 지나 있어야 한다
create or replace function askbuddy_purging(p_store_id bigint) returns boolean
language plpgsql stable as $$
declare
  target text := current_setting('askbuddy.purge_store_id', true);
begin
  if target is null or target = '' or p_store_id is null or target <> p_store_id::text then
    return false;
  end if;
  return exists (
    select 1 from stores
    where store_id = p_store_id and deleted_at is null
      and purge_due_at is not null and purge_due_at <= now());
end $$;

-- owner_answers 에는 store_id 가 없어 질문을 거쳐 매장을 찾는다
create or replace function askbuddy_purging_question(p_question_id bigint) returns boolean
language sql stable as $$
  select coalesce((select askbuddy_purging(q.store_id) from pending_questions q where q.question_id = p_question_id), false)
$$;
```

이어서 트리거 16개를 다시 만든다. 모양은 모두 같다(`before update or delete … for each row`). 아래 표의 줄마다 한 번씩 쓴다.

```sql
drop trigger <트리거> on <표>;
create trigger <트리거> before update or delete on <표>
  for each row when (not askbuddy_purging(old.store_id)) execute function <함수>();
```

| 표 | 트리거 | 함수 |
|---|---|---|
| `evaluation_results` | `trg_evaluation_results_append_only` | `askbuddy_evaluation_results_append_only` |
| `evaluation_runs` | `trg_evaluation_runs_freeze` | `askbuddy_evaluation_runs_freeze` |
| `extraction_results` | `trg_extraction_results_append_only` | `askbuddy_extraction_results_append_only` |
| `extraction_runs` | `trg_extraction_runs_freeze` | `askbuddy_extraction_runs_freeze` |
| `fact_revision_meta` | `trg_fact_revision_meta_immutable` | `askbuddy_fact_revision_meta_immutable` |
| `fact_revisions` | `trg_fact_revision_immutable` | `askbuddy_fact_revision_immutable` |
| `knowledge_entity_events` | `trg_entity_event_immutable` | `askbuddy_entity_event_immutable` |
| `knowledge_snapshots` | `trg_snapshot_immutable` | `askbuddy_snapshot_immutable` |
| `r_answer_citations` | `r_answer_citation_immutable` | `askbuddy_answer_receipt_immutable` |
| `r_answer_receipts` | `r_answer_receipt_immutable` | `askbuddy_answer_receipt_immutable` |
| `r_owner_answer_deliveries` | `r_owner_delivery_immutable` | `askbuddy_answer_receipt_immutable` |
| `r_owner_answer_revisions` | `r_owner_revision_immutable` | `askbuddy_answer_receipt_immutable` |
| `r_search_lexicons` | `r_search_lexicon_immutable` | `askbuddy_answer_receipt_immutable` |
| `task_categories` | `trg_task_categories_protect_system` | `askbuddy_protect_system_category` |

나머지 둘은 모양이 다르다.

```sql
-- owner_answers: store_id 가 없다
drop trigger r_owner_original_immutable on owner_answers;
create trigger r_owner_original_immutable before update or delete on owner_answers
  for each row when (not askbuddy_purging_question(old.question_id)) execute function askbuddy_owner_original_immutable();

-- r_index_documents: insert 도 같은 함수가 본다. insert 에는 old 가 없어 트리거를 둘로 나눈다
drop trigger r_index_documents_immutable on r_index_documents;
create trigger r_index_documents_immutable_insert before insert on r_index_documents
  for each row execute function askbuddy_index_documents_immutable();
create trigger r_index_documents_immutable before update or delete on r_index_documents
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_index_documents_immutable();
```

- [ ] **Step 4:** `api/app/config.py`에 `withdrawal_grace_days: int = Field(default=30, ge=1, le=365)`를 더한다. 주석: `# 사장님 탈퇴 유예 일수(D22). DB 는 이 값으로 계산한 purge_due_at 날짜만 본다`
- [ ] **Step 5:** 틀 DB를 지우고 실행. Expected: 7 passed. `python -m pytest -q` 전체 통과, `python scripts/verify_r_schema_rebuild.py` exit 0(`verify_r_index`, `verify_r_metadata_retention`이 같이 돌아 R 불변 동작이 그대로인지 본다).

---

### Task 6 (9C): 파기 순서와 `purge_store`

**Files:** Create `api/app/bootstrap/purge.py`. Test `api/tests/test_plan9_purge_db.py`(추가).

**Interfaces**
- Consumes: Task 5의 칸과 `askbuddy_purging`
- Produces:
  - `KEEP: frozenset[str] = {"stores", "ai_usage_attempts", "cost_assessments"}`
  - `USER_SCOPED: frozenset[str] = {"users", "auth_refresh_tokens", "user_identities", "push_subscriptions"}`
  - `VIA_CASCADE: dict[str, str]`(store_id가 없는 표 → 그 표를 CASCADE로 지워 주는 부모)
  - `PURGE_ORDER: tuple[str, ...]`
  - `class PurgeNotDue(Exception)`
  - `async def purge_store(conn: asyncpg.Connection, *, store_id: int) -> list[int]`: 지운 사용자 번호를 돌려준다. 트랜잭션은 이 함수가 연다.

상수는 아래 그대로 쓴다(2026-11-10 기준 106개 표를 카탈로그로 검산했다).

```python
VIA_CASCADE = {
    "chat_messages": "chat_sessions", "facts": "knowledge_cards", "learning_progress": "roadmap_stages",
    "message_citations": "knowledge_cards", "pending_question_occurrences": "pending_questions",
    "roadmap_items": "roadmap_stages", "source_frames": "sources", "source_kakao": "sources",
    "source_scan": "sources", "source_video": "sources", "source_voice": "sources",
}
PURGE_ORDER = (
    "access_logs", "card_embeddings", "card_evidence", "card_fact_edits", "card_facts", "card_review_events",
    "card_version_fact_provenance", "checklist_card_shifts", "checklist_cards", "checklist_check_events",
    "checklist_checks", "checklist_submissions", "evaluation_results", "extraction_raw_responses",
    "extraction_results", "fact_conflicts", "fact_rejections", "fact_revision_meta", "fact_revision_requires",
    "ingest_job_sources", "intake_route_decisions", "invite_codes", "knowledge_change_proposals",
    "knowledge_entity_aliases", "knowledge_entity_candidates", "knowledge_entity_events", "knowledge_publications",
    "member_shifts", "notification_deliveries", "notification_events", "operations", "outbox_consumptions",
    "outbox_cursors", "outbox_events", "outbox_leases", "owner_answer_attachments", "owner_answer_sources",
    "owner_ui_state", "quality_evaluations", "r_answer_citations", "r_evaluation_reservations",
    "r_failed_user_turns", "r_index_documents", "r_index_publications", "r_owner_answer_deliveries",
    "r_owner_knowledge_states", "r_question_contexts", "r_request_leases", "r_search_lexicons",
    "reclassification_jobs", "reclassification_results", "roadmap_stages", "snapshot_card_versions",
    "source_fact_occurrences", "source_fact_revision_links", "source_facts", "store_glossary",
    "store_join_requests", "store_shifts", "today_task_targets", "today_tasks", "upload_change_proposal_facts",
    "upload_change_proposals", "card_block_facts", "card_version_blocks", "evaluation_cases", "evaluation_runs",
    "extraction_runs", "fact_occurrences", "fact_owner_answer_links", "ingest_jobs", "knowledge_cards",
    "r_answer_receipts", "r_evaluation_budgets", "r_index_preparations", "r_owner_answer_revisions",
    "task_categories", "card_versions", "chat_sessions", "knowledge_facts", "knowledge_snapshots", "raw_spans",
    "owner_answers", "pending_questions", "store_members", "fact_revisions", "knowledge_entities", "sources",
)
```

`purge_store`가 한 트랜잭션에서 하는 일(순서 그대로):
1. `select set_config('askbuddy.purge_store_id', $1::text, true)`
2. `select purge_due_at from stores where store_id = $1 and deleted_at is null for update`. 행이 없거나 `purge_due_at`이 null이거나 `now()`보다 뒤면 `PurgeNotDue`
3. `select user_id from store_members where store_id = $1`로 멤버를 모은다
4. `PURGE_ORDER`를 돌며 지운다. `owner_answers`만 `delete from owner_answers where question_id in (select question_id from pending_questions where store_id = $1)`, 나머지는 `delete from {table} where store_id = $1`. 표 이름은 상수에서만 오므로 f-string으로 넣는다
5. `update stores set owner_id = null, store_name = '삭제된 매장', store_slug = null, deleted_at = now() where store_id = $1`
6. 모아 둔 멤버 중 어느 매장에도 속하지 않고 어느 매장의 사장님도 아닌 사용자를 지운다. `# store-isolation-ok: 사용자는 매장 밖 단위다. 다른 매장 소속을 확인하고 지운다`

```sql
delete from users u where u.user_id = any($1::bigint[])
  and not exists (select 1 from store_members m where m.user_id = u.user_id)
  and not exists (select 1 from stores s where s.owner_id = u.user_id)
returning u.user_id
```

- [ ] **Step 1: 실패하는 카탈로그 테스트**(표가 늘거나 FK가 바뀌면 여기서 걸린다)

```python
@unittest.skipUnless(ENABLED, SKIP_REASON)
class PurgeCatalogTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_every_table_is_classified(self):
        from app.bootstrap import purge
        tables = {r["tablename"] for r in await self.conn.fetch("select tablename from pg_tables where schemaname = 'public'")}
        groups = [set(purge.PURGE_ORDER), set(purge.VIA_CASCADE), set(purge.KEEP), set(purge.USER_SCOPED)]
        self.assertEqual(len(purge.PURGE_ORDER), len(set(purge.PURGE_ORDER)))
        self.assertEqual(sum(len(g) for g in groups), len(set().union(*groups)))  # 한 표는 한 묶음에만
        self.assertEqual(set().union(*groups), tables)

    async def test_tables_with_store_id_are_deleted_directly_or_kept(self):
        from app.bootstrap import purge
        with_store = {r["table_name"] for r in await self.conn.fetch(
            "select c.table_name from information_schema.columns c join pg_tables t on t.tablename = c.table_name "
            "and t.schemaname = 'public' where c.table_schema = 'public' and c.column_name = 'store_id'")}
        self.assertEqual(with_store, (set(purge.PURGE_ORDER) - {"owner_answers"}) | set(purge.KEEP))

    async def test_cascade_tables_really_cascade_from_their_parent(self):
        from app.bootstrap import purge
        fks = await self.conn.fetch(
            "select c.relname as child, p.relname as parent, k.confdeltype::text as rule from pg_constraint k "
            "join pg_class c on c.oid = k.conrelid join pg_class p on p.oid = k.confrelid "
            "where k.contype = 'f' and k.connamespace = 'public'::regnamespace")
        reach = {}
        for row in fks:
            if row["rule"] == "c":
                reach.setdefault(row["child"], set()).add(row["parent"])

        def cascades_from(child, parent, seen=()):
            return any(p == parent or (p in purge.VIA_CASCADE and p not in seen and cascades_from(p, parent, seen + (p,)))
                       for p in reach.get(child, ()))
        for child, parent in purge.VIA_CASCADE.items():
            self.assertTrue(cascades_from(child, parent), f"{child} 는 {parent} 에서 cascade 로 지워지지 않는다")

    async def test_children_are_deleted_before_blocking_parents(self):
        from app.bootstrap import purge
        pos = {t: i for i, t in enumerate(purge.PURGE_ORDER)}
        where = lambda t: pos[t] if t in pos else pos[purge.VIA_CASCADE[t]]
        skip = set(purge.KEEP) | set(purge.USER_SCOPED)
        fks = await self.conn.fetch(
            "select c.relname as child, p.relname as parent from pg_constraint k "
            "join pg_class c on c.oid = k.conrelid join pg_class p on p.oid = k.confrelid "
            "where k.contype = 'f' and k.connamespace = 'public'::regnamespace and k.confdeltype in ('a', 'r')")
        late = [(r["child"], r["parent"]) for r in fks
                if r["child"] != r["parent"] and r["child"] not in skip and r["parent"] not in skip
                and not where(r["child"]) < where(r["parent"])]
        self.assertEqual(late, [])

    async def test_ledger_columns_are_the_reviewed_set(self):
        # R1: 장부에 사람 글이 들어갈 칸이 새로 생기면 파기 뒤에도 남는다. 칸이 바뀌면 여기서 멈추고 다시 본다
        cols = {r["column_name"] for r in await self.conn.fetch(
            "select column_name from information_schema.columns where table_schema = 'public' "
            "and table_name = 'ai_usage_attempts' and udt_name in ('varchar', 'text', 'jsonb')")}
        self.assertEqual(cols, {
            "cost_phase", "cost_purpose", "stage", "logical_call_id", "registration_campaign_id", "operation_id",
            "segment_id", "status", "requested_model", "reported_model", "provider_request_id", "mode", "prompt_hash",
            "config_hash", "rate_card_version", "error_code", "cache_state", "billable_unit_name", "raw_usage",
            "usage_status", "missing_reason", "currency", "price_status"})
```

- [ ] **Step 2: 실패하는 동작 테스트**

```python
@unittest.skipUnless(ENABLED, SKIP_REASON)
class PurgeStoreTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        q = "insert into users (name, role) values ($1, $2) returning user_id"
        self.owner = await self.conn.fetchval(q, "사장", "OWNER")
        self.staff = await self.conn.fetchval(q, "알바", "STAFF")
        await self.conn.execute("update stores set owner_id = $2 where store_id = $1", self.store, self.owner)
        for uid, role in [(self.owner, "OWNER"), (self.staff, "STAFF")]:
            await self.conn.execute("insert into store_members (store_id, user_id, member_role) values ($1, $2, $3)", self.store, uid, role)
        await seed_immutable(self.conn, self.store)
        await self.conn.execute(
            "insert into sources (store_id, uploaded_by, source_type, file_url) values ($1, $2, 'SCAN', 'sources/1/scan/a.pdf')", self.store, self.owner)
        await self.conn.execute(
            "insert into ai_usage_attempts (store_id, cost_phase, stage, logical_call_id, requested_model) "
            "values ($1, 'OPERATING', 'ANSWER', 'answer:1', 'synthetic-model')", self.store)
        await self.conn.execute("set session_replication_role = origin")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def due(self, store, days_ago):
        await self.conn.execute(
            "update stores set closing_at = now() - interval '40 days', purge_due_at = now() - make_interval(days => $2) where store_id = $1", store, days_ago)

    async def leftovers(self, store):
        from app.bootstrap import purge
        counts = {}
        for table in purge.PURGE_ORDER:
            if table == "owner_answers":
                continue
            n = await self.conn.fetchval(f"select count(*) from {table} where store_id = $1", store)
            if n:
                counts[table] = n
        return counts

    async def test_purge_refuses_before_due(self):
        from app.bootstrap import purge
        await self.due(self.store, -1)
        with self.assertRaises(purge.PurgeNotDue):
            await purge.purge_store(self.conn, store_id=self.store)
        self.assertNotEqual(await self.leftovers(self.store), {})

    async def test_purge_refuses_active_store(self):
        from app.bootstrap import purge
        with self.assertRaises(purge.PurgeNotDue):
            await purge.purge_store(self.conn, store_id=self.store)

    async def test_purge_empties_the_store_and_keeps_the_ledger(self):
        from app.bootstrap import purge
        await self.due(self.store, 1)
        removed = await purge.purge_store(self.conn, store_id=self.store)
        self.assertEqual(sorted(removed), sorted([self.owner, self.staff]))
        self.assertEqual(await self.leftovers(self.store), {})
        row = await self.conn.fetchrow("select owner_id, store_name, store_slug, deleted_at from stores where store_id = $1", self.store)
        self.assertEqual((row["owner_id"], row["store_name"], row["store_slug"]), (None, "삭제된 매장", None))
        self.assertIsNotNone(row["deleted_at"])
        self.assertEqual(await self.conn.fetchval("select count(*) from ai_usage_attempts where store_id = $1", self.store), 1)
        self.assertEqual(await self.conn.fetchval("select count(*) from users where user_id = any($1::bigint[])", [self.owner, self.staff]), 0)

    async def test_purge_twice_is_refused(self):
        from app.bootstrap import purge
        await self.due(self.store, 1)
        await purge.purge_store(self.conn, store_id=self.store)
        with self.assertRaises(purge.PurgeNotDue):
            await purge.purge_store(self.conn, store_id=self.store)

    async def test_other_store_untouched(self):
        from app.bootstrap import purge
        other = await self.conn.fetchval("insert into stores (store_name, business_type) values ('다른 합성 매장', 'CAFE') returning store_id")
        await self.conn.execute("set session_replication_role = replica")
        await seed_immutable(self.conn, other)
        # 알바는 다른 매장에도 속해 있다(R6)
        await self.conn.execute("insert into store_members (store_id, user_id, member_role) values ($1, $2, 'STAFF')", other, self.staff)
        await self.conn.execute("set session_replication_role = origin")
        before = await self.leftovers(other)
        await self.due(self.store, 1)
        removed = await purge.purge_store(self.conn, store_id=self.store)
        self.assertEqual(removed, [self.owner])
        self.assertEqual(await self.leftovers(other), before)
        self.assertEqual(await self.conn.fetchval("select name from users where user_id = $1", self.staff), "알바")

    async def test_failure_midway_rolls_everything_back(self):
        from app.bootstrap import purge
        await self.due(self.store, 1)
        before = await self.leftovers(self.store)
        original = purge.PURGE_ORDER
        purge.PURGE_ORDER = original[:10] + ("없는_표",) + original[10:]
        try:
            with self.assertRaises(Exception):
                await purge.purge_store(self.conn, store_id=self.store)
        finally:
            purge.PURGE_ORDER = original
        self.assertEqual(await self.leftovers(self.store), before)
        self.assertIsNone(await self.conn.fetchval("select deleted_at from stores where store_id = $1", self.store))
```

- [ ] **Step 3:** 실행. Expected: 11개 모두 FAIL(`app.bootstrap.purge` 없음)
- [ ] **Step 4:** `api/app/bootstrap/purge.py`를 위 Interfaces대로 쓴다.
- [ ] **Step 5:** 실행. Expected: `test_plan9_purge_db.py` 18 passed(Task 5의 7개 포함)
- [ ] **Step 6:** `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/bootstrap`. Expected: 새 위반 0(사용자 삭제 한 곳은 사유가 달린 면제)

---

### Task 7 (9C): Storage 파일 삭제와 묶음 실행

DB를 먼저 지우면 파일 경로를 잃는다. 그래서 **파일을 먼저 지우고**, 다 지워졌을 때만 DB를 지운다. 중간에 실패하면 다음 번에 처음부터 다시 한다(파일 삭제는 여러 번 해도 같다).

**Files:** Modify `api/app/ingest/preprocess/storage.py`, `api/app/bootstrap/purge.py`. Test `api/tests/test_plan9_purge_db.py`(추가), `api/tests/test_plan9_storage.py`(새).

**Interfaces — Produces:**
- `async def delete_objects(bucket: str, paths: list[str]) -> None`(storage.py): Supabase Storage `DELETE {supabase_url}/storage/v1/object/{bucket}` 본문 `{"prefixes": paths}`, service key. 100개씩 끊어 보낸다. 200이 아니면 `RuntimeError`. 빈 목록이면 요청하지 않는다
- `def split_object_path(file_url: str) -> tuple[str, str]`(storage.py): `"sources/1/scan/a.pdf"` → `("sources", "1/scan/a.pdf")`. 같은 파일의 `_object_url`이 쓰는 규칙과 같게 한다
- `async def purge_due_stores(pool, *, delete_objects=storage.delete_objects) -> list[int]`(purge.py): 기한이 지난 매장마다 파일 삭제 → `purge_store`. 한 매장이 실패하면 로그에 예외 **종류만** 남기고 다음 매장으로 간다. 지운 매장 번호를 돌려준다. 계획 8 Task 7의 `withdrawal_loop`가 이것을 부른다

`purge_due_stores`의 매장 하나 처리:
1. `select store_id from stores where purge_due_at <= now() and deleted_at is null order by store_id` (`# store-isolation-ok: 기한이 지난 매장을 찾는 운영 작업`)
2. 그 매장의 `select file_url from sources where store_id = $1 and file_url is not null`, 멤버 중 이 매장에만 속한 사용자의 `avatar_path`
3. 버킷별로 `delete_objects`
4. `purge_store(conn, store_id=…)`

- [ ] **Step 1: 실패하는 테스트**

`api/tests/test_plan9_storage.py`:

```python
import pytest
from app.ingest.preprocess import storage


def test_split_object_path():
    assert storage.split_object_path("sources/1/scan/a.pdf") == ("sources", "1/scan/a.pdf")


def test_split_object_path_rejects_bare_name():
    with pytest.raises(ValueError):
        storage.split_object_path("a.pdf")
```

`test_plan9_purge_db.py`의 `PurgeStoreTest`에 추가:

```python
    async def pool(self):
        import asyncpg
        from tests._plan7_db import _db_url
        return await asyncpg.create_pool(_db_url(self.name), min_size=1, max_size=2)

    async def test_due_store_files_are_deleted_then_rows(self):
        from app.bootstrap import purge
        await self.due(self.store, 1)
        calls = []

        async def fake(bucket, paths):
            calls.append((bucket, sorted(paths)))
        pool = await self.pool()
        try:
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=fake), [self.store])
        finally:
            await pool.close()
        self.assertEqual(calls, [("sources", ["1/scan/a.pdf"])])
        self.assertEqual(await self.leftovers(self.store), {})

    async def test_storage_failure_keeps_db(self):
        from app.bootstrap import purge
        await self.due(self.store, 1)
        before = await self.leftovers(self.store)

        async def broken(bucket, paths):
            raise RuntimeError("storage down")
        pool = await self.pool()
        try:
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=broken), [])
        finally:
            await pool.close()
        self.assertEqual(await self.leftovers(self.store), before)

    async def test_not_due_store_is_skipped(self):
        from app.bootstrap import purge
        await self.due(self.store, -1)

        async def fake(bucket, paths):
            raise AssertionError("기한 전에는 파일을 지우지 않는다")
        pool = await self.pool()
        try:
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=fake), [])
        finally:
            await pool.close()
```

- [ ] **Step 2:** 실행. Expected: 5 failed(함수 없음)
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** 실행. Expected: `test_plan9_storage.py` 2 passed, `test_plan9_purge_db.py` 21 passed. 전체 pytest 통과. `check_store_id.py api/app/bootstrap api/app/ingest` 결과를 적는다.

실제 Storage 호출(`delete_objects`의 HTTP)은 로컬 Supabase가 떠 있을 때만 손으로 확인한다. 확인하지 못했으면 보고에 그렇게 적는다.

---

### Task 8 (9D): Parameter Store

지금은 서버의 `/home/ubuntu/askbuddy.env` 파일에 비밀값이 평문으로 있다. 값을 Parameter Store에 두고 배포 때마다 파일을 새로 만든다. 앱 코드는 바뀌지 않는다(여전히 env를 읽는다).

**Files:** Create `deploy/render_env.py`, `api/tests/test_render_env.py`. Modify `deploy/remote_deploy.sh`.

**Interfaces — Produces:** `render(parameters: list[dict], prefix: str) -> str`. `aws ssm get-parameters-by-path`의 `Parameters` 배열을 받아 `KEY=value` 줄을 이름순으로 돌려준다.

- [ ] **Step 1: 실패하는 테스트**

```python
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("render_env", Path(__file__).resolve().parents[2] / "deploy" / "render_env.py")
render_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_env)
P = "/askbuddy/prod/"


def test_renders_sorted_key_value_lines():
    params = [{"Name": P + "JWT_SECRET", "Value": "s3"}, {"Name": P + "DATABASE_URL", "Value": "postgresql://x"}]
    assert render_env.render(params, P) == "DATABASE_URL=postgresql://x\nJWT_SECRET=s3\n"


def test_rejects_newline_in_value():
    with pytest.raises(ValueError):
        render_env.render([{"Name": P + "A", "Value": "x\ny"}], P)


def test_rejects_name_outside_prefix_or_not_env_shaped():
    for name in ["/other/A", P + "nested/A", P + "lower"]:
        with pytest.raises(ValueError):
            render_env.render([{"Name": name, "Value": "x"}], P)


def test_empty_result_is_an_error():
    with pytest.raises(ValueError):
        render_env.render([], P)
```

- [ ] **Step 2:** `python -m pytest tests/test_render_env.py -q`. Expected: FAIL(파일 없음)
- [ ] **Step 3:** `deploy/render_env.py`를 쓴다. 표준 라이브러리만 쓴다. `__main__`은 stdin의 JSON(`{"Parameters": [...]}`)을 읽어 stdout에 쓴다. 키는 `^[A-Z][A-Z0-9_]*$`만 받는다. 값에 `#`이 있어도 그대로 둔다(불변식 10: 주석을 만들지 않는다).
- [ ] **Step 4:** `deploy/remote_deploy.sh`에서 `docker compose up` 앞에 넣는다.

```bash
# 비밀값은 Parameter Store 가 정본이다. 배포 때마다 env 파일을 새로 만든다
ENV_FILE="${ASKBUDDY_ENV_FILE:-/home/ubuntu/askbuddy.env}"
if [ "${ASKBUDDY_ENV_FROM_SSM:-0}" = "1" ]; then
  umask 077
  aws ssm get-parameters-by-path --path /askbuddy/prod/ --with-decryption --output json \
    | python3 render_env.py > "${ENV_FILE}.new"
  mv "${ENV_FILE}.new" "$ENV_FILE"
fi
```

`ASKBUDDY_ENV_FROM_SSM`이 1이 아니면 지금과 똑같이 돈다. 값을 다 옮긴 뒤에 켠다.

- [ ] **Step 5:** 실행. Expected: 4 passed. `bash -n deploy/remote_deploy.sh`. Expected: 출력 없음
- [ ] **Step 6 (사용자, 운영 서버):**
  1. EC2 인스턴스 역할에 `ssm:GetParametersByPath`(리소스 `arn:aws:ssm:<리전>:<계정>:parameter/askbuddy/prod/*`)와 기본 키 `kms:Decrypt`를 더한다
  2. 서버의 env 파일 한 줄마다 `aws ssm put-parameter --name /askbuddy/prod/<KEY> --type SecureString --value '<값>'`
  3. 서버에서 `aws ssm get-parameters-by-path --path /askbuddy/prod/ --with-decryption --output json | python3 render_env.py | diff - <(sort /home/ubuntu/askbuddy.env)`. Expected: 차이 없음
  4. 배포 명령 환경에 `ASKBUDDY_ENV_FROM_SSM=1`을 넣고 배포한 뒤 `/health` 확인

---

### Task 9 (9D): CloudWatch 로그와 알람

**Files:** Modify `deploy/compose.yml`.

- [ ] **Step 1:** `api` 서비스의 `logging`을 바꾼다. 리전은 env 파일이 아니라 배포 셸의 `AWS_REGION`에서 온다.

```yaml
    logging:
      driver: awslogs
      options:
        awslogs-region: ${AWS_REGION:?AWS_REGION 이 필요하다}
        awslogs-group: /askbuddy/api
        awslogs-create-group: "true"
        tag: "api-{{.ID}}"
```

- [ ] **Step 2:** `AWS_REGION=ap-northeast-2 docker compose -f deploy/compose.yml config >/dev/null`. Expected: exit 0. `AWS_REGION` 없이 돌리면 `AWS_REGION 이 필요하다`로 실패
- [ ] **Step 3 (사용자, AWS):**
  1. EC2 인스턴스 역할에 `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`(리소스 `/askbuddy/api`)를 더한다
  2. 배포 뒤 로그 그룹 `/askbuddy/api`에 줄이 쌓이는지 본다. 보존 기간을 30일로 정한다: `aws logs put-retention-policy --log-group-name /askbuddy/api --retention-in-days 30`
  3. 오류 수 지표: `aws logs put-metric-filter --log-group-name /askbuddy/api --filter-name api-errors --filter-pattern '" ERROR "' --metric-transformations metricName=ApiErrors,metricNamespace=AskBuddy,metricValue=1,defaultValue=0`
  4. SNS 주제를 만들고 운영자 이메일을 구독시킨 뒤 알람: `aws cloudwatch put-metric-alarm --alarm-name askbuddy-api-errors --namespace AskBuddy --metric-name ApiErrors --statistic Sum --period 300 --evaluation-periods 1 --threshold 5 --comparison-operator GreaterThanOrEqualToThreshold --treat-missing-data notBreaching --alarm-actions <SNS ARN>`

로그 줄에는 지금도 본문을 남기지 않는다(`metadata_retention.py`의 '예외 종류만' 규칙). CloudWatch로 보내도 같은 규칙이 적용된다. 30일 보존은 처리방침(계획 8 Task 9)에 적는다.

---

### Task 10 (9D): SES로 문의, 의견 알림 (계획 8 Task 6 뒤)

운영자가 DB를 열어 보지 않아도 문의가 왔다는 것을 안다. 메일에는 **글을 싣지 않는다**(종류와 번호만). 글은 DB에서 본다.

**Files:** Create `api/app/bootstrap/feedback_mail.py`, `api/tests/test_feedback_mail.py`. Modify `api/app/config.py`, `api/requirements.txt`(한 줄 append: `boto3>=1.34`), 계획 8의 `account_router.py` 의견 저장 끝점.

**Interfaces**
- Consumes: 계획 8 Task 6의 `POST /app/feedback`이 저장한 `feedback_id`, `kind`
- Produces: `async def notify_feedback(*, feedback_id: int, kind: str, client=None) -> bool`. 설정이 비어 있으면 보내지 않고 `False`. 보내다 실패하면 로그에 예외 종류만 남기고 `False`. 저장 응답은 메일 성패와 무관하다
- 설정: `feedback_mail_from: str = ""`, `feedback_mail_to: str = ""`, `aws_region: str = ""`

- [ ] **Step 1: 실패하는 테스트**

```python
import asyncio
from unittest.mock import patch
from app.bootstrap import feedback_mail


class FakeSes:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send_email(self, **kwargs):
        if self.fail:
            raise RuntimeError("ses down")
        self.sent.append(kwargs)


def settings(**over):
    base = dict(feedback_mail_from="noreply@example.com", feedback_mail_to="ops@example.com", aws_region="ap-northeast-2")
    return type("S", (), {**base, **over})()


def test_sends_kind_and_id_without_body():
    ses = FakeSes()
    with patch.object(feedback_mail, "get_settings", lambda: settings()):
        assert asyncio.run(feedback_mail.notify_feedback(feedback_id=7, kind="INQUIRY", client=ses)) is True
    mail = ses.sent[0]
    assert mail["FromEmailAddress"] == "noreply@example.com"
    assert mail["Destination"] == {"ToAddresses": ["ops@example.com"]}
    assert mail["Content"]["Simple"]["Subject"]["Data"] == "[AskBuddy] 문의 #7"
    assert "7" in mail["Content"]["Simple"]["Body"]["Text"]["Data"]


def test_idea_subject():
    ses = FakeSes()
    with patch.object(feedback_mail, "get_settings", lambda: settings()):
        asyncio.run(feedback_mail.notify_feedback(feedback_id=8, kind="IDEA", client=ses))
    assert ses.sent[0]["Content"]["Simple"]["Subject"]["Data"] == "[AskBuddy] 의견 #8"


def test_unset_config_sends_nothing():
    ses = FakeSes()
    with patch.object(feedback_mail, "get_settings", lambda: settings(feedback_mail_to="")):
        assert asyncio.run(feedback_mail.notify_feedback(feedback_id=7, kind="INQUIRY", client=ses)) is False
    assert ses.sent == []


def test_failure_is_swallowed():
    with patch.object(feedback_mail, "get_settings", lambda: settings()):
        assert asyncio.run(feedback_mail.notify_feedback(feedback_id=7, kind="INQUIRY", client=FakeSes(fail=True))) is False
```

- [ ] **Step 2:** 실행. Expected: FAIL(모듈 없음)
- [ ] **Step 3:** 구현. `client`가 없으면 `boto3.client("sesv2", region_name=settings.aws_region)`. boto3는 동기라 `asyncio.to_thread`로 감싼다. 의견 저장 끝점은 커밋 뒤 `asyncio.create_task(notify_feedback(...))`로 부르고 기다리지 않는다.
- [ ] **Step 4:** 실행. Expected: 4 passed. 전체 pytest 통과.
- [ ] **Step 5 (사용자, AWS):**
  1. SES에서 보내는 주소와 받는 주소를 인증한다(샌드박스에서는 인증된 주소로만 간다. 운영자 자신에게 보내는 것이라 샌드박스로 충분하다)
  2. EC2 인스턴스 역할에 `ses:SendEmail`을 더한다
  3. Parameter Store에 `FEEDBACK_MAIL_FROM`, `FEEDBACK_MAIL_TO`, `AWS_REGION`을 넣는다

---

## 배포 순서 (사용자가 한다)

1. Task 2의 확인 쿼리 두 개를 운영 DB에서 돌려 둘 다 0인지 본다. 0이 아니면 migration이 멈춘다.
2. 9A, 9B는 **코드 먼저, migration 나중**이다. 칸을 읽는 옛 코드가 떠 있는 채 칸을 지우면 그 요청이 실패한다. 순서: API 배포 → migration 적용.
3. 9C는 **migration 먼저, 코드 나중**이다(새 칸을 코드가 읽는다).
4. 9C만으로는 아무것도 지워지지 않는다. `purge_due_at`을 채우는 것은 계획 8 Task 7이다.

## 이 계획이 하지 않는 것

- 사장님 탈퇴 화면과 API, 유예 중 접속 차단, 한 시간마다 도는 루프: 계획 8 Task 7, 8
- 알바생 혼자 탈퇴(매장은 활성): 익명화. 계획 8 Task 7
- 백업에 남은 사본의 파기 주기: Supabase 백업 보존 기간을 확인해 처리방침에 적는다(계획 8 Task 9)
- `is_verified` 칸 삭제, 배열 칸 쪼개기(R4, R5)
