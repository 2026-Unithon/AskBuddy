# Phase A 배포 절차 (사용자 실행)

> 설계: `docs/dev/plan/W_PHASE_A_FACT_ONLY_DESIGN_20261010.md`. 구현 브랜치: `w/phase-a-fact-only`. 2026-10-10 작성.
> **이 문서의 명령은 사용자가 실행한다.** 개발 세션은 배포 환경을 바꾸지 않았다.
> **이번 배포는 지식·자료를 한 번 전부 지운다.** 되돌리는 방법은 배포 워크플로가 migration 직전에 만드는 DB 백업뿐이다. 코드만 되돌리면 지워진 데이터는 돌아오지 않는다.

## 0. 머지 전 확인

1. R 담당자가 인계 문서 12번 (a) "W3-4 필수 검토"를 끝냈는지 확인한다(`W_TO_R_PUBLICATION_HANDOFF_20260927.md`, R 이 할 일 10·12). 배포 뒤에는 모든 카드가 사실 블록 카드라서 R 이 그것을 받는지가 곧 서비스 전체 동작이다. 끝나지 않았으면 배포를 미룬다.
2. **Phase B 를 같이 배포하지 않으면 체크리스트는 다시 연결하지 않는다**(설계 §7). 체크리스트 재연결은 Phase B 머지 뒤다.
3. **평가 기록 확인(중요).** 운영 DB 에서 아래가 0 이어야 한다.

```sql
select count(*) from quality_evaluations;
```

   `quality_evaluations` 는 `ingest_jobs` 를 지우지 못하게 막는 연결(RESTRICT)을 갖고 있고, 평가 기록은 지우지 않는 것이 원칙이다. 그래서 1회 삭제 migration 은 이 표에 행이 하나라도 있으면 **오류를 내고 멈춘다(아무것도 지우지 않는다).** 배포가 migration 단계에서 실패하는 모양이다.
   0 이 아니면 배포하지 말고 먼저 정한다: 평가 행을 지울지, 연결 방식을 바꿀지, 그 행이 가리키는 작업을 남길지.

4. **배포 전 개수를 적어 둔다(필수).** 삭제 뒤 "남아야 할 것이 그대로인지" 비교하는 기준이다. 운영 DB 에서:

```sql
select
  (select count(*) from pending_questions)  as pending_questions,
  (select count(*) from owner_answers)      as owner_answers,
  (select count(*) from chat_messages)      as chat_messages,
  (select count(*) from ai_usage_attempts)  as ai_usage_attempts,
  (select count(*) from sources)            as sources,         -- 삭제 뒤 0 이 된다
  (select count(*) from knowledge_cards)    as knowledge_cards; -- 삭제 뒤 0 이 된다
```

   여섯 숫자를 날짜와 함께 적어 둔다. §4 에서 같은 쿼리로 비교한다.

## 1. 배포 워크플로 실행과 백업 확인

0. **배포 동안 업로드·점주 답변을 멈춘다(필수).** migration 적용부터 새 서버 health 확인까지는 Phase A 이전 서버가 바뀐 스키마 위에서 돈다. 이 사이에 들어온 업로드·점주 답변은 1회 삭제 **뒤**에 쓰여 지워지지도 않고, 삭제 migration 의 테이블 잠금과도 부딪친다. 점검 공지를 띄우고 점주에게 자료 올리기·답변을 미뤄 달라고 알린다. 가능하면 옛 서버의 worker(`W_OWNER_ANSWER_WORKER_ENABLED`)도 끈다. §4 확인을 마친 뒤 다시 연다.
1. GitHub Actions 에서 `Deploy API`(`.github/workflows/deploy-api.yml`)를 main 에서 실행한다(머지 뒤 자동 실행되기도 한다).
2. 순서는 `운영 DB 백업` → migration 확인 → migration 적용 → 서버 배포 → health 확인이다.
3. **`운영 DB 백업` 단계가 초록색인지 먼저 확인한다.** 실패했으면 그 뒤 단계가 돌지 않아야 한다. 이미 돌았다면 멈추고 개발자와 상의한다. 로그 마지막 줄 `backup: s3://<버킷>/db/<시각>-<커밋>.dump` 를 적어 둔다.
4. 백업은 `public`·`supabase_migrations` 스키마만 담는다. **Storage 파일(원본 자료)은 백업에 없다.** 6단계의 Storage 정리는 되돌릴 수 없다는 점을 기억한다.

## 2. migration 적용 확인

운영 DB 에 읽기 전용으로 접속해 확인한다(`psql "$PROD_DB_URL"`).

```sql
select version from supabase_migrations.schema_migrations where version like '20261010%' order by 1;
```

세 줄이 나와야 한다.

- `20261010090000` 점주 답변 ↔ 자료 연결 표(`owner_answer_sources`)
- `20261010110000` 1회 삭제
- `20261010120000` 옛 카드 판 트리거 제거(1회 삭제 **뒤**에 적용된다)

**0단계 가드로 멈춘 경우.** migration 은 버전별로 따로 적용되므로 `20261010090000` 만 적용됐고 `20261010110000` 이 실패해 `20261010120000` 은 적용되지 않은 상태다. 옛 카드 판 트리거가 남아 있으므로 그대로 도는 Phase A 이전 서버의 카드 생성은 깨지지 않는다(`20261010090000` 은 새 표를 더할 뿐이다). 서버 배포는 돌지 않았다. 평가 행은 **사람이 직접 처리**(지우거나 연결을 바꾸거나 해당 작업을 남기는 결정)한 뒤 `Deploy API` 를 다시 실행해야 한다. 처리하지 않고 다시 실행하면 같은 가드에서 또 멈춘다.

삭제 migration 이 하는 일(알아 둘 것):
- 지식·자료와 R 표(`r_answer_citations`·`r_answer_receipts`·`message_citations`·`knowledge_snapshots`·`snapshot_card_versions`·`r_index_*`)를 비운다. 불변 트리거는 그 트랜잭션 안에서만 잠깐 끈다.
- **`knowledge_publications` 행은 지우지 않고 `current_snapshot_id` 만 비운다.** 공개판 번호(revision)가 뒤로 가지 않게 하려는 구현 결정이다. 첫 직원 질문에서 `ensure_initial_publication` 이 빈 공개판을 다시 만든다.
- `operations` 중 `operation='PUBLISH'` 인 행(`r-initial-empty` 포함)은 지운다. `VISIBILITY` 멱등 기록은 남긴다.
- 질문·점주 답변·채팅 문장·비용 원장은 남긴다. `quality_evaluations` 는 위 0단계 때문에 비어 있어야 한다.
- R 표 중 이 migration 이 건드리지 않는 것: `r_evaluation_budgets`·`r_evaluation_reservations`·`r_owner_answer_deliveries`·`r_owner_answer_revisions`·`r_owner_knowledge_states`·`r_question_contexts`·`r_request_leases`·`r_search_lexicons`. 이 중 `r_owner_knowledge_states` 등은 지워진 카드에 대한 상태 글을 그대로 가질 수 있다. R 인계에 적어 두었다.

## 3. 서버 배포·env 확인

1. 워크플로의 `서버 배포`와 `health 확인`이 성공했는지 본다.
2. 서버 env 에서 `W_OWNER_ANSWER_WORKER_ENABLED=true` 를 확인한다(점주 답변 → 사실 순환이 이 worker 로 돈다).
3. 아래 W 플래그 줄은 서버 env 에서 지워도 되고, 남아 있어도 무시된다: `W_ENTITY_REVISION_ENABLED`·`W_UPLOAD_PROPOSALS_ENABLED`·`W_FACT_ASSEMBLY_ENABLED`·`W_FACT_CARD_EDIT_ENABLED`·`W_OWNER_ANSWER_RAW_PUBLISH`. 새로 추가할 플래그는 없다.

## 4. 삭제 결과 확인 SQL

```sql
select
  (select count(*) from knowledge_cards)       as cards,        -- 0
  (select count(*) from card_versions)         as card_versions, -- 0
  (select count(*) from sources)               as sources,       -- 0
  (select count(*) from ingest_jobs)           as jobs,          -- 0
  (select count(*) from r_answer_citations)    as citations,     -- 0
  (select count(*) from pending_questions)     as questions,     -- 배포 전과 같다
  (select count(*) from owner_answers)         as owner_answers; -- 배포 전과 같다
```

앞의 다섯은 0, 뒤의 둘은 0단계 4번에 적어 둔 숫자와 같아야 한다.

초안 판이 없는 깨진 카드가 없는지도 본다. 트리거가 사라진 뒤 옛 서버가 카드를 만들었다면 여기서 드러난다.

```sql
select count(*) from knowledge_cards where draft_version_id is null; -- 0 이어야 한다
```

0 이 아니면 Storage 정리로 가지 말고 멈춘다(배포 중 업로드·답변이 들어왔다는 뜻이다. 그 카드들의 자료를 확인하고 개발자와 상의한다). 추가로 0단계 4번의 여섯 숫자 쿼리를 다시 돌려 `pending_questions`·`owner_answers`·`chat_messages`·`ai_usage_attempts` 가 그대로이고 `sources`·`knowledge_cards` 가 0 인지 본다. 다르면 Storage 정리(6단계)로 가지 말고 멈춘다.

## 5. 데모 매장 참고

데모 시드(`api/scripts/demo_seed.py`)는 이제 카드를 만들지 않는다. 카드는 자료를 올려서 만든다. 시연 때는 로컬에서 자료를 올려 카드를 만든다.

## 6. Storage 정리

원본 파일이 버킷 `sources` 에 남아 있다. SQL 로는 못 지우므로 스크립트를 쓴다. **기본은 지우지 않는 dry-run 이다.**

```bash
cd api
# 1) 목록만 본다(아무것도 지우지 않는다)
python scripts/wipe_storage_sources.py --all-stores
# 2) 한 매장만: --store-id N
# 3) 목록이 맞으면 실제 삭제
python scripts/wipe_storage_sources.py --all-stores --apply
```

- **운영 값으로 실행해야 한다.** 스크립트는 `SUPABASE_URL`·`SUPABASE_SERVICE_KEY`·`SUPABASE_DB_URL`(`api/.env` 또는 환경변수)을 읽는다. 로컬 값이면 로컬(또는 데모) 버킷을 보고도 "성공" 으로 끝난다. 세 값을 운영 것으로 넘기는 방법(키를 파일·셸 기록에 남기지 않는 방식)은 사용자가 정한다. dry-run 에서 나온 매장 목록과 파일 수가 운영 것인지 확인한 뒤에 `--apply` 한다.
- 종료 코드: 0 정상, 1 목록 조회나 삭제 중 오류, 2 `SUPABASE_SERVICE_KEY` 없음. 1 이 나오면 다시 실행해 남은 파일이 없는지 확인한다.
- **지금 DB 의 `sources.file_url` 이 가리키는 파일은 지우지 않는다.** 스크립트는 매장마다 DB 에서 그 매장 자료의 `file_url` 을 읽어 삭제 목록에서 뺀다. 배포 뒤 점주가 새로 올린 원본이 지워지지 않게 하려는 것이다. 출력의 `kept` 수가 그 파일 수다. 1회 삭제 직후라면 0 이고, §1 에서 업로드를 다시 연 뒤라면 그 뒤 올라온 수만큼 나온다. DB 를 읽지 못하면 아무것도 지우지 않고 종료 코드 1 로 멈춘다.
- 이 단계는 되돌릴 수 없다(백업에 Storage 가 없다). 4단계 확인이 끝난 뒤에 한다.

## 7. 종단 확인

1. 자료를 다시 올린다(예: 문서 1건). 카드가 검수 대기로 나오는지 본다.
2. 카드를 검수·공개한다. 직원 계정으로 질문 1건을 한다 — 답변과 "근거 보기" 가 나오는지 확인한다. 첫 질문에서 빈 공개판이 만들어진 뒤 새 공개판이 이어지는지 본다.
3. 대기 질문 1건에 점주 답변을 한다. 새 대상이면 사실 카드가 자동 공개되는지, 이미 공개된 카드의 대상이면 그 카드의 새 초안이 승인 대기로 뜨는지 본다. **답변부터 공개(또는 승인 대기)까지 걸린 시간을 적어 둔다.**
4. 이상이 있으면 멈추고 개발자에게 알린다. 되돌리려면 9단계.

## 8. 체크리스트

Phase A 는 체크리스트를 다시 연결하지 않는다. Phase B 머지 뒤에 연결한다.

## 9. 되돌리기

**먼저 읽을 경고: 복원한 DB 는 `20261010110000` 적용 이력이 없는 상태로 돌아간다. 그 상태에서 main 을 다시 배포하면(배포는 항상 `supabase db push --include-all` 을 돌린다) 삭제 migration 이 다시 실행되어 데이터가 한 번 더 지워진다.** `Deploy API` 는 main 에서만 돌고 특정 커밋을 고를 수 없으므로 아래 순서를 지킨다.

1. **자동 배포를 먼저 막는다.** GitHub Actions 에서 `Deploy API` 워크플로를 비활성화한다(`R validation` 성공 뒤 자동으로 이어지는 배포도 막힌다). main 에 다른 머지를 하지 않는다.
2. 1단계에서 적어 둔 백업(`s3://<버킷>/db/<시각>-<커밋>.dump`)으로 DB 를 복원한다. 복원 방법은 배포 설계 문서 `docs/release/plan/API_AUTO_DEPLOY_DESIGN.md` 의 복원 절차를 따른다(release 영역이라 이번 작업에서 열어 보지 않았다).
3. **main 에서 Phase A 머지를 되돌리는 커밋(revert)을 올려** `20261010110000` 파일(그리고 Phase A 코드)이 main 에 없게 한다. 복원 DB 는 `20261010090000`·`20261010120000` 도 모르는 상태이므로 revert 로 셋 다 빠지는지 확인한다. 이 revert 가 main 에 들어가기 전에는 어떤 경로로도 `Deploy API` 를 켜지 않는다.
4. revert 가 main 에 들어간 뒤 `Deploy API` 를 다시 활성화해 실행한다. 서버 코드가 Phase A 이전으로 돌아가고 스키마와 맞는다.
5. Storage 파일을 6단계에서 이미 지웠다면 되돌릴 수 없다. 자료는 다시 올려야 한다.
6. **코드만 되돌리면 지워진 데이터는 돌아오지 않는다.** DB 복원이 반드시 함께 필요하다. 반대로 DB 만 복원하고 main 을 그대로 두면 다음 배포에서 다시 지워진다.
