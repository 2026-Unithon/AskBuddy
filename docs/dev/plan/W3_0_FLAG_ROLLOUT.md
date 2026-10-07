# W3-0 배포판 W2 플래그 켜기 절차 (사용자 실행)

> 설계: `docs/dev/plan/W3_0_FLAG_READINESS_DESIGN.md` §3-7. **이 문서의 명령은 사용자가 실행한다.** 개발 세션은 배포 환경 값을 바꾸지 않았고, 배포판 플래그는 아직 켜지지 않았다.
> 켜면 그 뒤로 처리되는 자료부터 대상·불변 판·occurrence·충돌·업로드 제안이 쌓인다. 기존 자료·카드는 소급 이관하지 않는다(2026-10-07 결정).

## 0. 켜기 전 확인

- W3-0 PR 이 main 에 머지되고 `Deploy API` 워크플로가 성공했다(GitHub Actions). 배포는 migration(`supabase db push`)을 서버 배포 **전에** 적용하므로 순서는 이미 맞다.
- 처리량 기록 [`docs/dev/review/W3_0_THROUGHPUT_20261007.md`](../review/W3_0_THROUGHPUT_20261007.md) 를 읽는다. 실제 모델 지연은 재지 않았다(합성 지연 0·1500 ms, 조건당 1회, 로컬 Docker). 모델 응답이 빠르면 자료 처리 시간의 대부분이 매장 lock 을 쥐고 보내는 시간이다(lock 보유 몫 0.71~0.92, 지연 0 ms). 모델이 느린 조건(1500 ms)에서는 0.07~0.15 였다. 같은 매장 자료의 구간이 차례로 처리될 수 있음을 받아들일지 정한다.
- 운영 서버 코드에 W3-0 이 들어갔는지(서버에서, ubuntu 사용자):

```bash
test -f ~/askbuddy/api/app/ingest/variant_split.py && echo "W3-0 코드 있음"
test -f ~/askbuddy/supabase/migrations/20261007090000_w_merge_cleanup_states.sql && echo "W3-0 migration 파일 있음"
```

## 1. 배포 DB 에 migration 이 적용됐는지

운영 DB 에 읽기 전용으로 접속해(`psql "$PROD_DB_URL"`) 확인한다.

```sql
-- 4행이어야 한다: W2 3개 + W3-0 1개
select version from supabase_migrations.schema_migrations
where version in ('20260930090000', '20260930100000', '20260930110000', '20261007090000')
order by version;

-- 표가 있어야 한다(모두 null 이 아님)
select to_regclass('public.knowledge_entities'), to_regclass('public.knowledge_entity_candidates'),
       to_regclass('public.knowledge_facts'), to_regclass('public.fact_revision_meta'),
       to_regclass('public.source_fact_revision_links'), to_regclass('public.fact_occurrences'),
       to_regclass('public.fact_conflicts'), to_regclass('public.upload_change_proposals'),
       to_regclass('public.upload_change_proposal_facts');

-- W3-0 이 넓힌 허용 값: 'MERGED', 'CANDIDATE_MOVED', 'PROPOSAL_MOVED' 가 보여야 한다
select conrelid::regclass, conname, pg_get_constraintdef(oid) from pg_constraint
where conrelid in ('knowledge_entity_candidates'::regclass, 'knowledge_entity_events'::regclass)
  and contype = 'c';
```

위 CHECK 목록에 `MERGED`·`CANDIDATE_MOVED`·`PROPOSAL_MOVED` 가 보여야 하고, status·action 을 옛 값으로만 제한하는 다른 CHECK 가 남아 있으면 안 된다(이름이 달라도 전부 본다). 하나라도 빠졌거나 어긋나면 켜지 않는다. `Deploy API` 의 migration 적용 단계 로그를 확인한다.

## 2. 서버 API 환경 값에 두 플래그 켜기

API 컨테이너는 `deploy/compose.yml` 의 `env_file: ${ASKBUDDY_ENV_FILE:-/home/ubuntu/askbuddy.env}` 를 읽는다.
기본은 `/home/ubuntu/askbuddy.env` 이고, ubuntu 로그인 셸 환경이나 `~/askbuddy/deploy/.env` 에 `ASKBUDDY_ENV_FILE` 가 있으면 그 경로다.
env 파일에는 비밀값이 있으므로 파일 전체를 출력하지 않는다. 값 뒤에 주석을 붙이지 않는다(CLAUDE.md 불변식 10).

```bash
# 서버에서 (SSM Session Manager 또는 SSH)
sudo -iu ubuntu
printenv ASKBUDDY_ENV_FILE                                   # 비어 있으면 기본 경로
grep -s '^ASKBUDDY_ENV_FILE=' ~/askbuddy/deploy/.env         # 없으면 기본 경로
ENV_FILE="${ASKBUDDY_ENV_FILE:-/home/ubuntu/askbuddy.env}"   # 위에서 다른 경로가 나오면 그 경로로 바꾼다
cp "$ENV_FILE" "$ENV_FILE.bak-$(date +%Y%m%d%H%M%S)"
grep -n '^W_ENTITY_REVISION_ENABLED=\|^W_UPLOAD_PROPOSALS_ENABLED=' "$ENV_FILE"
```

- 위 grep 에 줄이 나오면 그 줄의 값을 `true` 로 고친다. 안 나오면 두 줄을 더한다:

```bash
printf '%s\n' 'W_ENTITY_REVISION_ENABLED=true' 'W_UPLOAD_PROPOSALS_ENABLED=true' >> "$ENV_FILE"
```

- `W_UPLOAD_PROPOSALS_ENABLED=true` 는 `W_ENTITY_REVISION_ENABLED=true` 를 요구한다. 하나만 켜면 설정 검증이 막아 API 가 시작하지 않는다. 두 줄을 함께 넣는다.
- 설정은 프로세스 시작 때 한 번 읽는다(`get_settings` 캐시). 컨테이너를 다시 만든다:

```bash
cd ~/askbuddy/deploy && docker compose up -d --force-recreate api
docker compose exec api python -c "from app.config import get_settings as g; s = g(); print(s.w_entity_revision_enabled, s.w_upload_proposals_enabled)"
# 기대 출력: True True
```

- 다음 배포(`remote_deploy.sh`)도 같은 env 파일을 읽으므로 값은 유지된다. 코드 기본값은 계속 꺼짐이다.

## 3. 켠 뒤 확인

새 업로드 1건을 처리한 뒤(점주 화면에서 합성·테스트용 자료 1건 업로드 권장):

```sql
-- 최근 1시간에 끝난 자료
select source_id, store_id, source_type, status, processed_at
from sources where status = 'DONE' and processed_at >= now() - interval '1 hour'
order by source_id desc limit 5;

-- 아래 `\set` 줄의 `<고른 source_id>` 자리표시자를 위 결과의 실제 source_id 숫자로 바꾸고, 이어지는 `\set` 과 `select` 는 같은 psql 세션에서 실행한다(세션이 바뀌면 변수가 사라진다).
-- 위에서 고른 자료 하나 (psql: \set source_id <고른 source_id>)
select s.source_id,
  (select count(*) from source_facts f where f.store_id = s.store_id and f.source_id = s.source_id) as ledger_facts,
  (select count(*) from source_fact_revision_links l join source_facts f
     on f.store_id = l.store_id and f.fact_id = l.source_fact_id
   where f.store_id = s.store_id and f.source_id = s.source_id) as linked_facts,
  (select count(*) from fact_occurrences o where o.store_id = s.store_id and o.source_id = s.source_id) as occurrences,
  (select count(*) from upload_change_proposals p where p.store_id = s.store_id and p.source_id = s.source_id) as proposals,
  (select count(*) from knowledge_entities e where e.store_id = s.store_id) as store_entities
from sources s where s.source_id = :source_id;
```

- 기대: `linked_facts` = `ledger_facts`(대상 이름을 정규화할 수 없는 사실만 빠지고 로그 `대상 결정 불가` 가 남는다), `occurrences` ≥ `linked_facts`, `proposals` ≥ 1, `store_entities` ≥ 1. 한 자료에 HOT/ICE 가 함께 나온 사실은 원장에서 규격별 두 사실로 나뉘므로 `ledger_facts` 가 원래 추출 건수보다 많을 수 있다. 이 `linked_facts` = `ledger_facts` 확인은 플래그를 켠 뒤 새로 올린 자료에만 적용된다. 켜기 전에 처리된 자료를 다시 처리하면 옛 원장 행은 잇지 않은 채 남으므로(backfill 없음) `linked_facts` < `ledger_facts` 가 정상이다.
- 오류·처리 시간 로그:

```bash
cd ~/askbuddy/deploy && docker compose logs --since 1h api | grep -E "W2 연결|W2 업로드 제안|W3-0 제안 정리|대상 결정 불가|ingest DONE|ingest FAILED|Traceback"
```

- `ingest DONE source=… cards=… 구간 …/… 실패 N.Ns` 의 마지막 초가 처리 시간이다. 켜기 전 같은 크기 자료와 비교하고 처리량 기록의 숫자와 함께 본다.

## 4. 되돌리기

- env 파일의 두 줄을 `false` 로 바꾸고(또는 지우고) §2 의 `docker compose up -d --force-recreate api` 를 다시 실행한다. 확인 출력은 `False False`.
- 끄면 **새 쓰기만** 멈춘다. 이미 쌓인 대상·판·occurrence·충돌·제안 행은 지우지 않는다(불변 원장). 다시 켜면 그 행 위에 이어서 쌓인다.
- 백업한 env 파일(`$ENV_FILE.bak-…`)로 되돌려도 된다.
