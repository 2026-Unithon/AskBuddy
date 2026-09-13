---
name: store-isolation-check
description: AskBuddy 의 API·DB 변경을 검증한다. 새 라우터·쿼리·migration 을 만들었거나 고쳤을 때, 매장 격리(store_id)·migration 절차·오류 계약이 지켜졌는지 실제로 실행해서 확인한다. api/app/, supabase/migrations/, db/ 를 건드렸다면 작업을 마치기 전에 반드시 쓴다.
---

# 매장 격리·API·migration 검증

AskBuddy 는 **RLS 를 쓰지 않는다(D1).** 매장 A 사용자가 매장 B 데이터를 못 보게 막는 것은
전적으로 API 코드다. 그래서 "코드를 읽어보니 맞다" 는 검증이 아니다. **실행해서 확인한다.**

## 언제 쓰는가

- `api/app/` 아래 라우터·repository·쿼리를 추가하거나 고쳤을 때
- `supabase/migrations/` 에 새 파일을 만들었을 때
- 기존 테이블에 컬럼·제약·트리거를 추가했을 때

## 하지 말 것

- 이미 적용된 migration 파일을 고치는 것. 새 파일을 만든다
- 운영 DB 에 `db reset`·seed 를 실행하는 것
- 사용자가 명시적으로 요청하기 전에 운영 DB 에 적용하는 것. 로컬까지가 기본이다
- `store_id` 를 요청 본문에서 읽는 것. **JWT 에서만 꺼낸다**
- `store_id` 에 기본값이나 `Optional` 을 주는 것

---

## 1. 정적 검사 — 격리 누락 찾기

grep 으로는 안 된다. 시그니처가 여러 줄로 걸쳐 있어서 전부 위반으로 찍힌다.
이 스킬에 붙은 AST 검사기를 쓴다.

```bash
# 바꾼 폴더만
python3 .claude/skills/store-isolation-check/check_store_id.py api/app/<바꾼폴더>

# 전체
python3 .claude/skills/store-isolation-check/check_store_id.py api/app
```

검사기가 찾는 것:

| 검사 | 위반 조건 |
|---|---|
| 함수 시그니처 | DB 커넥션을 받는데 `store_id` 인자가 없다 |
| 기본값 | `store_id` 에 기본값이나 `Optional` 이 있다 |
| 라우트 핸들러 | 인증 정보를 받는데 본문이 `store_id` 로 좁히지 않는다 |
| SQL 문자열 | `store_id` 컬럼이 있는 테이블을 건드리는데 조건이 없다 |

**검토를 마친 정당한 예외**는 해당 줄 위에 사유와 함께 못 박는다.

```python
# store-isolation-ok: 로그인 전이라 아직 소속 매장이 없다
async def login(db: asyncpg.Connection, ...):
```

사유 없는 `# store-isolation-ok` 는 무시된다. 이유를 안 쓸 거면 면제도 없다.

새 테이블을 만들었으면 검사기 상단의 `TENANT_TABLES` 를 갱신한다 —
파일에 갱신용 SQL 이 주석으로 붙어 있다.

## 2. 단위·API 테스트

```bash
cd api && source .venv/bin/activate
python -m pytest tests/ -q
```

기능 변경에는 테스트를 **함께** 추가한다. 순수 판정 로직은 DB 없이 테스트할 수 있게
분리한다 (`app/team/metrics.py` 가 그 예다).

---

## 3. migration 로컬 적용과 가드 검증

로컬 DB 는 docker 컨테이너다. `psql` 이 PATH 에 없으므로 컨테이너로 들어간다.

```bash
# 적용
docker exec -i supabase_db_AskBuddy psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  < supabase/migrations/<새파일>.sql
```

**제약·트리거를 추가했다면 그것이 실제로 막는지 확인한다.** 통과 경로만 보고 끝내지 않는다.

```bash
docker exec -i supabase_db_AskBuddy psql -U postgres -d postgres <<'SQL'
\set ON_ERROR_STOP 0
-- 막혀야 하는 동작을 일부러 시도하고 ERROR 가 나는지 본다
<위반 시도 SQL>
SQL
```

검증용으로 넣은 행은 반드시 지운다. 동결 트리거 때문에 못 지우면
`alter table <t> disable trigger <name>` 으로 일시 해제하고 지운 뒤 다시 켠다.

---

## 4. 매장 격리 실측

**이게 이 스킬의 핵심이다.** 매장이 하나뿐이면 임시 매장을 만들어서라도 확인한다.

```bash
# API 기동
cd api && source .venv/bin/activate
uvicorn app.main:app --port 8011 &

# 토큰 2개 — 서로 다른 store_id
TOKEN_A=$(python scripts/dev_token.py --force)
TOKEN_B=$(python -c "from app.deps import create_token; print(create_token({'store_id':<다른매장>,'user_id':1,'role':'OWNER'}))")
```

확인할 4가지:

| 시도 | 기대 |
|---|---|
| 토큰 없이 호출 | 401 |
| 권한 없는 역할의 토큰 | 403 + 오류 envelope |
| 매장 B 토큰으로 목록 조회 | 매장 A 데이터가 **한 건도** 없다 |
| 매장 B 토큰으로 매장 A 리소스 id 직접 조회 | 404 (403 이 아니다 — 존재 여부를 알려주지 않는다) |

임시로 만든 매장은 지운다. `stores` 삭제가 시스템 카테고리 보호 트리거에 막히면
`alter table task_categories disable trigger user` 로 풀고 지운 뒤 되돌린다.

---

## 5. 오류 계약

새 라우터는 `app/errors.py` 의 `new_api` 접두사 목록에 들어가야 422 가 공통 envelope 로 나간다.

```bash
curl -s -X POST localhost:8011/<새경로> -H "Authorization: Bearer $TOKEN_A" \
  -H 'Content-Type: application/json' -d '{}' | head -c 200
```

`{"error":{"code":"VALIDATION_ERROR",...}}` 가 아니라 FastAPI 기본 `{"detail":...}` 가 나오면
접두사 등록이 빠진 것이다. `app/errors.py` 와 `app/main.py` 는 **공용 파일이라 수정 전에 사람에게 묻는다.**

---

## 6. 운영 반영 (사용자가 요청했을 때만)

순서를 건너뛰지 않는다.

```bash
# 1) 백업 — Git 제외 경로로
# 2) 로컬 재구축·검증 SQL·테스트 통과
# 3) 예상 migration 만 확인
supabase db push --linked --dry-run
# 4) 적용 후 migration list 와 읽기 전용 verify SQL 확인
```

15단계 이후에는 사용자가 다시 명시하기 전까지 **dry-run 까지만** 한다.

---

## 완료 판정

- [ ] `check_store_id.py` 가 새로 건드린 폴더에서 위반 0건이다 (면제는 사유를 달았다)
- [ ] `pytest tests/ -q` 통과
- [ ] migration 이 로컬에 적용됐고, 추가한 가드가 실제로 막는 것을 확인했다
- [ ] 매장 B 토큰으로 매장 A 데이터가 목록·직접조회 모두에서 안 보인다
- [ ] 401·403·404·422 가 의도한 대로 나온다
- [ ] 검증용 임시 데이터를 지웠다
