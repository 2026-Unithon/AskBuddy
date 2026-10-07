# W 다음 작업 계획 — W1 잔여 · W2 · W3 · J2 · W5 (2026-09-28)

> **새 Claude Code 세션용.** 이 문서만 읽고 시작할 수 있게 썼다. 단계(Phase)마다 새 세션을 열어도 된다.
> 구현은 `superpowers:subagent-driven-development`(권장) 또는 `superpowers:executing-plans` 로 Task 단위로 진행한다.
> 체크박스(`- [ ]`)로 진행을 표시한다.

## 0. 세션 시작 절차

1. 저장소 루트 `CLAUDE.md` 를 읽는다. 이어서 이 문서의 해당 Phase 와 §1·§2 를 읽는다.
2. `git switch main && git pull --ff-only` 뒤 **같은 폴더에서** `git switch -c w/<phase-이름>` 으로 브랜치를 판다.
   별도 worktree 폴더를 만들지 않는다.
3. 작업을 마치면 변경 요약과 브랜치 이름만 보고하고 멈춘다.
   **`git commit`·`git push` 를 하지 않고, 커밋할지 묻지도 않는다.** 사용자가 직접 PR 을 올리고 main 에 머지한다.
4. 사용자에게 보고는 한국어로, 쉬운 말로 한다. 사용자는 W(쓰기 파이프라인) 담당자다.
5. §3 의 "사람이 정할 것" 에 걸리면 추정해서 진행하지 말고 `AskUserQuestion` 으로 묻는다.

## 1. 순서와 의존

| 순서 | Phase | 한 줄 목표 | 선행 | 크기 |
|---|---|---|---|---|
| 1 | **W1 잔여** | 추출이 잘못돼도 원인을 되짚을 수 있게 한다 — 원래 응답 저장, 잘린 출력 복구, 재사용 키, 근거 위치 | 없음 | 중 |
| 2 | **W2** | 여러 자료의 같은 대상 사실을 한 대상으로 모으고, 수정은 불변 revision 으로 남긴다 | W1 잔여 | 대 |
| 3 | **W3** | 카드를 모델 문장이 아니라 **사실 참조**로 조립하고 서버가 검증·렌더링한다. 검수 화면 | W2 | 최대 |
| — | **J2** | 업로드 처리를 `BackgroundTasks` 에서 영속 worker 로 옮긴다 | 없음(병행 가능) | 중 |
| 5 | **W5** | 품질 실험 — W3 전후 비교 | W3 직전 기준선 태그 | 실행·비용 |

- W1 잔여 → W2 → W3 는 순서대로 한다. 각 단계의 산출물이 다음 단계의 입력이다.
- J2 는 파이프라인 내부와 겹치지 않아 병행할 수 있다. 실제 매장 배포 전까지만 끝나면 된다.
  단, `api/app/ingest/job_worker.py`·`pipeline.py` 를 같은 시기에 두 브랜치가 고치면 충돌한다. 병행하면 W 단계와 파일 경계를 먼저 맞춘다.
- **W3 를 main 에 머지하기 직전**에 그 시점 main 에 git 태그 `w-baseline-pre-w3` 를 붙인다(사용자에게 요청).
  태그가 없으면 W3 이후 "나아졌나" 를 잴 기준선을 다시 돌릴 방법이 없다(옛 구조 BASE 가 그렇게 사라졌다).

## 2. 전 단계 공통 제약

저장소 `CLAUDE.md` 가 우선한다. 특히:

- **매장 격리**: 모든 DB 함수는 `store_id` 필수 인자, `WHERE store_id = ...` 없는 조회 금지, store_id 는 JWT·worker 신뢰 범위에서 온다.
  `api/app/`·`supabase/migrations/` 를 건드리면 보고 전에
  `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/<폴더>` 를 돌린다.
  `api/app/ingest/repository.py` 에는 원래 있던 위반 15건이 있다 — 새 위반만 막는다.
- **R 소유 파일은 수정하지 않는다**: `api/app/reg/*`, `api/app/learn/router.py`, `answering.py`, `answer_storage.py`,
  `owner_handoff.py`, `owner_publication.py`, `approved_renderer.py`, `v2_router.py`, `knowledge_loop.py`(주 편집자 R), auth·notifications.
  호출·import 만 한다. R 이 바꿔야 할 것은 `docs/dev/plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md` 끝의 "R 이 할 일" 에 추가한다.
- **W 주 편집 파일**: `api/app/ingest/*`, `api/app/cards/*`, `api/app/learn/knowledge_apply.py`, `api/app/publish/*`,
  `api/app/team/extraction.py`·`scoring_rules.py`, `api/prompts/extract_facts.ko.txt`·`assemble_cards.ko.txt`, W 소유 migration.
- **공통 파일**(`api/app/config.py`, `api/app/main.py`, `api/app/contracts/*`, `api/scripts/verify_r_schema_rebuild.py`)은 가산 변경만 한다.
  `contracts/*` 계약을 바꾸면 R 검토가 필요하다 — 바꾸기 전에 사용자에게 알린다.
- **migration 은 가산형**만. 적용된 migration 파일을 고치지 않는다. 이름은 `supabase/migrations/YYYYMMDDHHMMSS_w_<주제>.sql`.
- 이미 발행된 snapshot 의 hash 가 바뀌면 안 된다. canonical payload 에 새 필드는 값이 있을 때만 싣는다.
- 모델명·차원·임계값·상한은 `api/app/config.py` 가 단일 출처. 프롬프트는 `api/prompts/` 파일. 주석은 한국어.
- LLM 호출마다 소요 시간·토큰을 원장(`ai_usage_attempts`)에 남긴다. 외부 모델 호출 동안 DB 연결을 쥐지 않는다(`app.db_session.ShortSession`).
- 새 기능은 **플래그 뒤에** 넣고 기본값은 꺼 둔다. 인증·매장 격리·승인 확인을 끄는 플래그는 만들지 않는다.
- **평가용 실제 자료의 브랜드·상호·메뉴 고유명을 문서·주석·테스트·커밋 메시지 어디에도 쓰지 않는다.** `평가용 카페 자료 A` 처럼 쓴다.
- `docs/release/` 는 요청 없이 읽거나 고치지 않는다.
- `docs/experience/` 는 사용자가 요청할 때만 쓴다(사람의 결정만, STAR 형식).

검증 명령(보고 전에 해당하는 것을 모두 돌리고 결과를 사실대로 적는다):

```bash
cd api && .venv/bin/python -m pytest -q tests          # 기준: 1502 passed, 4 xfailed (2026-09-29)
docker run -d --rm --name askbuddy-w-verify -p 127.0.0.1:55439:5432 \
  -e POSTGRES_PASSWORD=synthetic-local-test -e POSTGRES_DB=usage_verify pgvector/pgvector:pg17
cd api && PYTHONPATH=. PYTHONUTF8=1 .venv/bin/python -B scripts/verify_r_schema_rebuild.py   # 실제 DB 전체 검증
docker stop askbuddy-w-verify
cd web && pnpm check                                     # web 을 건드렸을 때. 단위 테스트 러너 없음 — "테스트 통과" 라고 쓰지 않는다
python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest api/app/cards api/app/publish
```

W 공개 경로의 실제 DB 검증은 `api/scripts/verify_w_publication_flow.py`(재구축 스크립트가 부른다)에 시나리오를 더한다.
유료 모델을 부르는 실측(`INGEST_MODE=real`)은 사용자 승인 없이 돌리지 않는다. 합성 대역으로 검증한다.

## 3. 사람이 정할 것 (만나면 멈추고 묻는다)

| Phase | 결정 | 추천 |
|---|---|---|
| W1 | 모델 원래 응답의 보관 기간·삭제 방식(개인정보가 섞일 수 있다) | 자료 tombstone 과 같이 보존, 물리 삭제는 개인정보 삭제 절차 |
| W2 | 두 대상 이름이 같은 대상인지 서버가 정하는 규칙 | 매장별 정규화 이름 + 별칭 표. 단어 유사도만으로 합치지 않고 애매하면 검수로 |
| W2 | 자료끼리 값이 충돌할 때 검수 화면에서 무엇을 기본으로 보여줄지 | 양쪽 값·출처·날짜를 나란히, 기본 선택 없음(권위·최신성은 정렬 참고만) |
| W3 | 카드 편집으로 업무 의미가 바뀌면 새 점주 작성 사실로 기록하고 재승인 — 편집 화면 설계 | 값·조건 편집은 사실 편집 UI, 문구만 바꾸는 편집은 표시 문구로 분리 |
| W3 | `contracts/*` 계약 변경이 필요해지면 R 합의 | 가능한 한 현재 계약(`CardPlan`·`CardBlock`·`FactRevision`) 안에서 해결 |
| J2 | 동시 처리 수·재시도 횟수·lease 길이 | 동시 1~2, 재시도 3, lease 5분 + heartbeat |
| W5 | 요율표(`config/rate_card.json` 모델 단가), 예산 상한, 실행 수 | W1 기준선 3회 + 대조 3회 × 2매장 = 12회, W3 후 같은 12회 |

---

## 4. 지금 상태 (2026-09-28, main `630db77`)

추측하지 말고 필요한 곳은 직접 열어 확인한다. 아래는 계획을 쓸 때 확인한 사실이다.

**파이프라인** (`api/app/ingest/pipeline.py`)
- `process_source` → 전처리(`_preprocess_*`: 영상 프레임·STT, 음성 STT, 카톡, 스캔/PDF) → `_extract_facts_all`(구간별 사실 추출) →
  `_persist_ledger`(조립 **전에** `source_facts` 원장 저장) → `assemble_assertions`(자료 **하나 단위**로 조립) → `_persist`(카드 저장, `card_facts` 연결).
- 조립이 자료 단위라 **다른 자료의 같은 대상 사실이 한 카드로 모이지 않는다.** 사람 검토에서 실제로 확인됐다
  (스캔 표의 원칙과 음성의 응대 방법이 카드 두 장으로 갈림 — `docs/dev/review/W_USER_DECISIONS_20260928.md`). W2·W3 가 푼다.
- 구간 실패는 `ingest_job_sources.failed_segment_ids`·`recovery_state` 로 PARTIAL 재시도한다(`api/app/ingest/recovery.py`).

**모델 호출** (`api/app/ingest/extract/gemini.py`)
- `_call` 은 `response.text` 와 usage 만 돌려준다. **원래 응답을 저장하지 않는다.**
- `finish_reason`(출력 잘림)을 보지 않는다. 잘리면 JSON 파싱 실패 → 그 구간 전체를 잃는다(`tenacity` 재시도는 호출 예외에만 걸린다).
- 원장 `ai_usage_attempts` 에 토큰은 남지만 요율표가 없어 비용은 비어 있다.

**원장·revision 스키마** (M1 migration `supabase/migrations/20260916100000_m1_revision_publication.sql`)
- 이미 있는 테이블: `fact_revisions`(불변, `entity_id` 필수, `supersedes_revision_id`), `fact_revision_requires`, `fact_occurrences`
  (`disposition` LINKED/REVIEW_PENDING/EXCLUDED, 사유 필수), `raw_spans`, `card_version_blocks`, `card_block_facts`, 공개판 테이블.
- **W 수집 파이프라인은 아직 `fact_revisions`·`fact_occurrences` 에 쓰지 않는다.** `source_facts`·`card_facts` 만 쓴다.
  대상(entity) 테이블은 없다.
- `source_facts` 열: subject·variant·attribute·value·unit·polarity·conditions·exceptions·step_order·requires·local_ref·segment_id·
  locator_type·locator·assembly_state·extract_version·confidence·original_assertion. 비영상 자료의 locator 는 대부분 `WHOLE_SOURCE` 다.

**공개** (`api/app/publish/content.py`·`approval.py`)
- 카드 버전 원문을 RAW 블록으로 고정해 공개한다. `PublishedCard.entity_id` 에는 **카드 ID 를 임시로** 넣고 `fact_revisions=()` 다.
- R 렌더러(`api/app/learn/approved_renderer.py`)는 **사실 참조 블록을 이미 그릴 수 있다** — `selected.fact_revision_ids` 를 돌며
  `fact.assertion`·조건·예외를 출력하고 fact 단위로 인용한다. 계약(`api/app/contracts/card.py`·`snapshot.py`)도 준비돼 있다.
  W3 는 계약을 새로 만들기보다 **채우는** 작업이다.

**작업 처리**
- 업로드 작업: `POST /ingest/jobs` 가 `BackgroundTasks` 로 `job_worker.process_ingest_job` 을 돌린다. 재시작하면 처리 중 작업이 사라진다.
  `ingest_jobs` 에 lease 칸이 없다. 카테고리 재분류도 같은 방식(`api/app/categories/router.py`).
- 점주 답변 worker(`api/app/cards/owner_answer_worker.py`)가 claim/heartbeat/finish·lease 유실 처리의 **본보기**다.

**채점기** (`api/app/team/extraction.py`·`scoring_rules.py`, `w_fact_score/v4`)
- 공통 규칙 + 업종(카페) 규칙. 사람·AI 검토 68건 기준표 대비 맞게 담음 40, 틀리게 담음 0.
- 정답지 278건, 평가 정책 `api/eval/policies/w_user_confirmed_20260927.json`. 기록은 `docs/dev/review/W_SCORER_V4_20260928.md`.

---

## Phase W1 잔여 — 원래 응답 저장 · 잘린 출력 복구 · 재사용 키 · 근거 위치

**목표:** 추출 결과가 이상할 때 "모델이 실제로 뭐라고 답했나" 를 되짚을 수 있고, 출력이 잘려도 조용히 잃지 않으며,
같은 입력을 다시 돌릴 때 비용·중복이 생기지 않는다.

TODO 근거: `docs/dev/DEV_TODO_CURRENT.md` W1 절(원시 응답 보존·잘림 복구, 상한, 재시도 중복, 재사용 키, occurrence 보존).

### Task W1-1. 모델 원래 응답 저장
- [x] migration: `extraction_raw_responses`(store_id 필수, source_id, job_id, run_tag, segment_id, stage `EXTRACT|ASSEMBLE`,
      model, prompt_hash, schema_version, reuse_key, finish_reason, response_text, usage jsonb, parsed_ok, error, created_at).
      자료 삭제(D20)와 같은 보존 원칙 — 자료 tombstone 으로 지우지 않는다. 보관 기간은 §3 에서 사용자 확인. (실제 DB 검증 통과)
- [x] `gemini.py` 의 `_call`/`_measured_call` 이 응답 텍스트·`finish_reason` 을 함께 돌려주게 하고, **파싱 전에** 저장한다.
      저장은 짧은 연결로(모델 호출 중 연결 보유 금지). 저장 실패는 멈춘다(`RawResponseWriteError`, docstring 에 사유 명시).
- [x] mock 경로(`extract/mock.py`)도 같은 기록을 남긴다(테스트·재현용).
- 검증: 파싱 실패 응답도 행이 남는다. 다른 매장 행이 보이지 않는다. 단위 테스트 + 실제 DB 시나리오.

### Task W1-2. 잘린 출력 감지·복구
- [x] `config.py` 에 추출·조립 출력 token 상한을 두고 `GenerateContentConfig(max_output_tokens=...)` 로 넘긴다. 기본값은 None(공급자 기본) — 실측 전이라 숫자를 가정하지 않음.
- [~] `finish_reason` 이 `MAX_TOKENS` 면 성공으로 처리하지 않는다(항상 켜짐, 재시도에 안 걸림). 구간을 반으로 나눠 다시 뽑고 끝까지 잘리면 실패 구간으로 기록해 PARTIAL 로 드러낸다 — **구현은 완료했으나 분할 재추출은 `extract_truncation_split_max_depth` 기본 0(꺼짐)·실제 모델 미실측.**
- [x] 구간 분할의 크기·겹침·동시 호출 수·timeout 을 설정으로 모은다(`video_segment_overlap_sec`·`extract_segment_concurrency`·`gemini_file_active_timeout_sec`·`gemini_file_poll_sec`; 기존 값은 옮김).
- 검증: 합성 대역이 첫 호출에 잘린 응답을 주면 분할 재추출로 사실이 모두 모인다. 계속 잘리면 PARTIAL 과 실패 구간 ID 가 남는다.

### Task W1-3. 재사용 키와 중복 방지
- [x] 재사용 키 = sha256(매장, 원본/구간 내용 hash, 첨부 hash, 모델, 프롬프트 hash, 추출 schema 버전, 온도·PDF 모드 등 설정).
      **평가 정답을 런타임 입력에 넣지 않는다.**(테스트로 고정)
- [~] 같은 키로 성공한 원래 응답이 있으면 모델을 다시 부르지 않고 그 응답을 파싱해 쓴다(원장에 재사용으로 기록, 비용 0).
      모델·프롬프트·설정이 바뀌면 키가 바뀌어 새 실행으로 남는다. — **구현·실제 DB 검증 완료, 제품 경로 기본 켜짐(평가 실행 제외)·실제 모델 미실측.**
- [~] 같은 작업 재시도가 `source_facts` 를 중복 생성하지 않는다(기존 `unique(source_id, content_hash)` + 재사용 키로 멱등, 실제 DB 확인). 기존 PARTIAL 재시도와 충돌 없음. 제품 경로는 재사용 기본 켜짐이라 같은 입력 재시도는 모델 호출 1회다(평가 실행은 매번 호출).
- 검증: 같은 자료 두 번 처리 → 모델 호출 1회, 사실 중복 없음. 프롬프트 파일 한 글자 변경 → 새 호출.

### Task W1-4. 근거 위치(occurrence) 보존
- [~] 비영상 자료도 가능한 위치를 남긴다: PDF 페이지(`PAGE`), 카톡 줄/메시지(`LINE`), 음성 구간(`TIMESTAMP`). 구간 정보를 locator 로 옮긴다. — 음성 `TIMESTAMP` 는 기존대로 항상 동작. PDF `PAGE`·카톡 `LINE` 은 리뷰 후 `extract_locator_hints` 플래그 뒤로 옮겨 **기본 꺼짐**(꺼짐이면 모델 입력·schema 는 이전과 바이트 단위로 동일, 위치는 `WHOLE_SOURCE`) — 실제 모델 미실측.
- [~] 같은 사실이 여러 구간·자료에 나와도 **각 근거 위치를 모두** 남긴다(`source_fact_occurrences`, 플래그 무관 항상 켜짐, 중복 사실로 합치며 버리지 않는다). W2 의 `fact_occurrences` 로 이어진다. 남은 것(2026-09-29): 쪽·메시지 단위 위치는 `extract_locator_hints=True` 일 때만 갈린다 — 기본은 PDF·카톡이 `WHOLE_SOURCE` 한 행이다.
- [x] 존재하지 않는 구간(`requires`) 참조·지어낸 단위/규격을 거절하는 서버 검사를 넣는다(`validate_assertions`, 항상 켜짐, TODO W1: 추정 채우기 거절). 쪽·줄 범위 검사는 위치 표지 플래그를 켰을 때만 적용된다.
- 검증: 한 PDF 두 페이지에 같은 사실 → 사실 하나, 근거 위치 둘.

**W1 완료 조건:** 위 검증 + 실제 DB 재구축 통과 + `docs/dev/DEV_TODO_CURRENT.md` W1 절 체크 갱신(부분 구현은 `[~]` 와 남은 것 한 줄).

---

## Phase W2 — 서버 대상 ID · 불변 사실 revision · 충돌 보존

**목표:** 사실이 "어느 대상(메뉴·장비·업무)에 대한 것인지" 를 서버가 정하고, 여러 자료의 같은 대상 사실을 모으며,
값이 다르면 양쪽을 모두 남긴다. 수정은 옛 사실을 덮지 않고 새 revision 으로 남긴다.

TODO 근거: W2 절 전체. 스키마는 M1 의 `fact_revisions`·`fact_occurrences` 를 **쓴다**(새로 만들지 않는다). 대상 테이블만 새로 만든다.

> 2026-09-29 상태: 구현·단위 테스트(전체 1502 passed, 4 xfailed)·실제 DB 검증(`api/scripts/verify_w_entity_revision.py`, 스키마 재구축 통과)을 마쳤다.
> **수집 경로의 W2 동작은 모두 플래그 `w_entity_revision_enabled`·`w_upload_proposals_enabled` 뒤에 있고 기본 꺼짐이다(제안 플래그는 앞 플래그가 있어야 켠다). 실제 모델(`INGEST_MODE=real`)로는 재지 않았다.**
> 기존 카드·사실은 소급 채우지(backfill) 않는다. 새 표는 `20260930090000`·`20260930100000`·`20260930110000` migration 이다.

### Task W2-1. 대상(entity) 도입
- [x] migration: `knowledge_entities`(store_id, entity_id, canonical_name, kind, created_at) +
      `knowledge_entity_aliases`(store_id, alias_norm, entity_id, origin `SYSTEM|OWNER`, 매장 안에서 alias 유일).
      `knowledge_cards.entity_id` nullable 추가(기존 카드는 비워 두고 이관은 별도 Task).
      (`api/app/ingest/entities.py`·`entity_names.py`. 기존 카드는 비어 있다.)
- [x] 대상 결정 규칙은 §3 결정에 따른다. 기본: 정규화 이름·별칭 일치만 자동, 애매하면 새 대상 + 검수 대기.
      **규격(HOT/ICE·사이즈)은 대상 이름에 섞지 않는다** — `variant_temperature`·`variant_size` 로 따로 둔다.
      (이름이 비슷하면 '같은 대상일 수 있음' 후보로만 제안하고 자동 병합하지 않는다.)
- [x] 매장 격리: 별칭 표는 매장별이다. 다른 매장 별칭이 섞이지 않는 실제 DB 검사.

### Task W2-2. 원장 → 사실 revision·occurrence 연결
- [~] `_persist_ledger` 뒤(같은 트랜잭션)에서 각 사실을 대상에 붙이고 `fact_revisions` 한 판 + `fact_occurrences` 한 건을 만든다.
      같은 대상·규격·속성·값이면 같은 `fact_id` 의 새 occurrence(재추출 중복 금지), 값이 다르면 다른 `fact_id` 로 **둘 다** 남기고 충돌로 표시한다.
      (`api/app/ingest/fact_ledger.py`, 플래그 꺼짐이면 DB 쓰기가 이전과 같다. 합성 데이터 실제 DB 검증.)
      **남은 것: 플래그 `w_entity_revision_enabled` 기본 꺼짐, 실제 모델 미실측.**
- [x] `source_facts` 는 이관 호환을 위해 당분간 계속 쓴다. 두 표의 연결 키를 남긴다. (연결 키 스키마는 실제 DB 검증. 키가 채워지는 것은 플래그 켜짐일 때다.)
- [~] 점주 답변(OWNER_ANSWER)에서 온 사실은 파일 출처를 만들지 않는다 — 점주 답변 출처로 남긴다.
      출처는 `fact_occurrences` 가 아니라 W 소유 `fact_revision_meta`·`fact_owner_answer_links` 에 있다(공유 M1 표의 `source_id` 제약을 풀지 않음).
      **남은 것: `record_owner_answer_fact` 를 부르는 곳(점주 답변 worker) 없음.**

### Task W2-3. 수정은 새 revision
- [~] 점주 정정·편집은 `supersedes_revision_id` 로 이어지는 새 판을 만든다. 옛 판은 불변(트리거가 막는다).
      추출 원문·점주 정정·적용 시점을 구분한다. `corrected_value` 는 이관 입력일 뿐 공개 근거 포인터가 아니다.
      (`api/app/ingest/fact_revisions.py`. 서비스 함수·불변 트리거는 실제 DB 검증.)
      **남은 것: `revise_fact` 호출 경로(정정 API·검수 화면) 없음. 옛 `corrected_value` 이관이 점주 정정 위에 쌓일 수 있음 — W3 로.**

### Task W2-4. 영향받는 카드만 다시 조립
- [~] 새 사실의 대상·규격·의존 조건으로 영향 카드 목록을 계산한다. 영향 없는 카드의 ID·공개 버전·수동 분류(`assignment_type='MANUAL'`)는 건드리지 않는다.
      (`api/app/ingest/impact.py`. 영향 카드를 계산해 제안에 담기만 하고 기존 카드 행은 쓰지 않는다. **남은 것: 실제 재조립은 W3. 플래그 `w_upload_proposals_enabled` 기본 꺼짐.**)
- [~] 업로드도 기존 `IDENTICAL | NEW | SUPPLEMENT | CONFLICT` 제안을 재사용해 검수로 보낸다(점주 답변 쪽 구현 `knowledge_apply.py` 참고).
      (`upload_change_proposals` 별도 표. 관계 어휘·판정 순서만 재사용하고 점주 답변 제안 표와는 분리.)
      **남은 것: 제안 저장까지만. 네 관계·카드·근거를 보여주는 API·검수 화면 없음, 플래그 `w_upload_proposals_enabled` 기본 꺼짐.**
- [~] 잘못 합친 대상의 분리·재연결도 이력을 남기고 공개본을 자동 변경하지 않는다.
      (`api/app/ingest/entity_admin.py`: 병합·분리·재연결. 서비스 함수는 실제 DB 검증.)
      **남은 것: 서비스 함수만 있다. 호출 경로(API·검수 화면) 없음.**

**W2 검증:** 영상의 순서 + PDF 수량이 한 대상으로 모인다. HOT/ICE 는 분리된다. 수치 충돌은 양쪽이 남는다. 매장별 별칭 격리.
같은 자료 재투입은 중복이 없다. 사람 검토 사례(스캔 표 원칙 + 음성 응대 방법 → 한 대상)를 합성 데이터로 재현해 테스트한다.

---

## Phase W3 — 사실 참조로 카드 조립 · 서버 렌더링 · 검수 화면

**목표:** 조립 모델은 "어느 사실을 어느 블록에 둘지" 만 고르고, 수량·단위·조건·부정·예외를 새로 쓰지 않는다.
서버가 검증하고 카드 문장을 렌더링한다. R 이 "이 카드의 이 줄" 을 fact 단위로 인용할 수 있게 공개판에 `fact_revisions` 를 싣는다.

TODO 근거: W3 절 + W4 의 "fact_revision 블록 고정" 남은 것. **이 Phase 는 새 플래그(예: `W_FACT_ASSEMBLY`, 기본 false) 뒤에 넣는다.**

### Task W3-1. 조립 출력 = CardPlan
- [ ] `api/prompts/assemble_cards.ko.txt` 를 사실 참조 방식으로 바꾼 새 프롬프트 파일을 만든다(옛 것은 플래그 OFF 경로용으로 둔다).
      출력은 `app.contracts.card.CardPlan`(대상·규격·제목·블록: `QUANTITIES|STEPS|NOTES|RAW`, 블록마다 `fact_revision_ids`).
- [ ] 조립 입력은 **대상 단위**로 모은 사실 revision 이다(W2). 자료 단위가 아니다.

### Task W3-2. 서버 검증·렌더링
- [ ] 참조 허용 목록(같은 매장·같은 대상 묶음의 revision 만), 규격 일치(HOT 블록에 ICE 사실 금지), 필수 조건·예외 포함,
      STEPS 의 순서·선행(`requires`, 순환 금지)을 검사한다. 어기면 그 카드를 검수 대기로 보낸다 — 문장을 지워 완성 카드로 위장하지 않는다.
- [ ] 줄 문법: 제목 → 수치 → 순서 → 목록 → 근거. 없는 블록은 생략. 고정 필드·분량 때문에 사실을 버리지 않는다. 큰 대상은 의미 단위로 관련 카드로 나눈다.
- [ ] `card_version_blocks`·`card_block_facts` 에 블록을 고정하고, 카드 `content` 는 렌더링 결과로 채운다(기존 화면 호환).

### Task W3-3. occurrence 처분 기록
- [ ] 추출 occurrence 마다 `LINKED`(카드·블록) / `REVIEW_PENDING`(사유) / `EXCLUDED`(사유) 를 `fact_occurrences` 에 남긴다.
      처리 결과 없이 사라지는 occurrence 가 없어야 한다. 과도한 제외·대기를 품질 향상으로 세지 않도록 건수를 함께 보고한다.

### Task W3-4. 공개판에 사실 싣기
- [ ] `api/app/publish/content.py` 가 사실 블록 카드에 대해 `fact_revisions` 와 실제 `entity_id` 를 싣는다. RAW 블록 레거시 카드는 그대로.
      이미 발행된 snapshot 의 hash 는 바뀌지 않아야 한다(새 필드는 값이 있을 때만).
- [ ] **R 필수 검토**: R 렌더러·색인·인용 검증이 사실 블록 공개판을 받는지 R 과 확인한다. 인계 문서에 요청을 적는다.

### Task W3-5. 검수 화면
- 2026-10-05 사용자 확정: [W/R 공유 기준](../review/WR_CARD_EDIT_FACT_REVIEW_20261005.md)의 **사실·문장 단위 추가·수정·삭제·순서 변경**을 따른다. 기존 fact 값만 편집하도록 제한하지 않는다. 새 사실은 텍스트로 입력·확인하며 표현만의 편집은 이번 범위에 포함하지 않는다. 아래 §3의 편집 화면 질문은 이 방향으로 확정됐다.
- [ ] 점주 카드 검수 화면(`web/app/owner/cards/[cardId]/page.tsx`, 목업 `UI/`)에 값·규격·조건·예외·순서·근거 원문을 모두 보인다.
      숫자가 없는 금지·예외도 숨기지 않는다. 수정·추가·제외를 허용한다.
- [ ] 생성 시 카드 표시 내용과 fact의 연결을 보존하고, 새 입력의 사실 확인과 추가·수정·삭제·순서 변경 저장을 연결한다. 삭제는 새 초안에서 참조 제외로 처리하고 과거 승인본·인용·다른 카드의 사실을 보존한다. 마지막 사실 삭제는 카드 제외·정상 빈 상태와 연결한다.
- [ ] 편집으로 업무 의미가 바뀌면 새 점주 작성 사실 revision 으로 기록하고 재승인한다(§3 결정).
- [ ] web 변경 후 `pnpm check` 와 저장소 스킬 `web-async-state-check`·`ui-state-walkthrough` 를 쓴다. 브라우저를 못 띄웠으면 그렇게 보고한다.

### W2 에서 넘어온 것
- [x] 병합 뒤 재처리하면 병합된 대상 아래의 옛 PENDING 업로드 제안과 남은 대상 아래의 새 PENDING 제안이 중복된다. — W3-0 §3-3-2: 병합된 대상의 PENDING 제안을 그 자료에 살아 있는 대상 제안이 없으면 **옮기고(MOVED)**, 살아 있는 제안이 PENDING_REVIEW 이면 옛 제안을 **SUPERSEDED** 로 닫고, 그 밖의 경우(살아 있는 제안이 이미 결정됨)는 옛 제안을 PENDING 으로 **남겨 둔다(KEPT_PENDING)**. 모두 `PROPOSAL_MOVED` 이력이 남고 결정된 제안은 건드리지 않는다.
- [x] 병합된 대상이 낀 다른 PENDING 같은 대상 후보(병합된 것, 제3 대상)가 그대로 PENDING 으로 남는다. — W3-0 §3-3-1: 남은 대상 쪽으로 옮기거나 `MERGED` 로 닫고 이력 `CANDIDATE_MOVED`(migration `20261007090000_w_merge_cleanup_states.sql`).
- [x] `import_legacy_correction` 이 점주 정정 판 위에 더 오래된 `corrected_value` 를 새 head 로 얹을 수 있다(적용 시각과 head 순서 불일치). — W3-0 §3-2: head 가 EXTRACTION 이 아니면 건너뜀(None, 로그).
- [x] 같은 순위로 다시 처리하면 제안의 `matched_cards` 가 갱신되지 않는다. — W3-0 §3-3-3: 같은 순위여도 `matched_cards` 가 달라졌으면 새 계산으로 갱신.
- [x] 기존 카드·사실은 소급 채우지 않았다(`knowledge_cards.entity_id` 비어 있음, 옛 `source_facts` 의 대상·판 없음). — 2026-10-07 사용자 결정: 소급 이관하지 않는다. 플래그를 켠 뒤 올라온 자료만 새 구조로 간다(W3-0 설계 §2).

**플래그 켜기 전 점검** (`w_entity_revision_enabled`·`w_upload_proposals_enabled`)
- [x] 한 자료에 HOT/ICE 가 함께 나오면 규격 없음 slot 으로 들어간다. — W3-0 §3-1: 원장 단계에서 규격별 두 사실로 나눈다(`api/app/ingest/variant_split.py`, 플래그 켜짐일 때만).
- [x] 연결·같은 대상 후보 처리량이 매장 advisory lock 하나에 묶인다. — W3-0 §3-5 측정(합성 모델 지연, 조건당 1회, 로컬 Docker): `docs/dev/review/W3_0_THROUGHPUT_20261007.md`. 실제 모델 지연은 재지 않았다.
- [x] `owner_answer_id` FK 는 R 소유 `owner_answers` 에 대해 `on delete restrict` 다. — W3-0 §3-4 확인: R 트리거가 R revision 있는 답변의 삭제를 막고 앱에 답변 삭제 경로가 없어 새로 막히는 경로 없음. 코드 변경 없음(인계 문서 R 이 할 일 8, 닫힘).
- [x] 호출 경로를 붙이기 전에 `import_legacy_correction` 적용 순서(위 항목)를 먼저 고친다. — W3-0 §3-2.
- [x] 두 플래그를 모두 켜고 구간을 동시에 처리하는 합성 종단 검증을 한 번 돌린다. — `api/scripts/verify_w3_flag_readiness.py`(40개 검사, 재구축 검증이 부른다). 구간 동시성 2 에서 구간이 겹쳤음은 처리량 측정의 lock 대기 시간(lock_wait)으로 추정했다(구간별 시각 기록은 없음).
- [ ] 배포판에서 두 플래그 켜기 — **사용자 실행**: `docs/dev/plan/W3_0_FLAG_ROLLOUT.md`. 아직 켜지 않았다.

**W3 검증:** 다른 매장/존재하지 않는 참조, HOT/ICE 수치 교환, 부정·조건·예외 삭제, 순서 변경을 차단한다.
승인 미리보기와 저장 콘텐츠가 같다. occurrence 가 처리 결과 없이 사라지지 않는다. 실제 DB 로 사실 블록 카드 승인 → R 검색·답변 인용까지(`verify_w_publication_flow.py`).

---

## Phase J2 — 업로드 처리 영속 worker

**목표:** 서버가 재시작돼도 업로드 작업이 사라지지 않고, 멈춘 작업은 회수·재시도된다.

TODO 근거: J2 절의 worker 항목. 본보기는 `api/app/cards/owner_answer_worker.py`(claim·heartbeat·finish·lease 유실).

- [ ] migration: `ingest_jobs` 에 lease 칸(`lease_token`, `lease_expires_at`, `attempt_count`, `next_attempt_at`) 또는 별도 lease 테이블. 가산형.
- [ ] worker 루프: 대기 작업 claim(`for update skip locked`) → 처리 중 heartbeat → 완료/실패 finish. 만료 lease 회수, 재시도(지수 backoff, 상한), 상한 초과 시 FAILED 와 사유.
- [ ] `config.py` 에 `W_INGEST_WORKER_ENABLED`(기본 false)·동시 수·lease 길이·재시도 상한. `main.py` lifespan 에서 켜고 끈다.
      플래그 ON 이면 라우트는 작업을 **큐에 넣기만** 하고 `BackgroundTasks` 를 쓰지 않는다. OFF 면 지금과 같다.
- [ ] 모델 호출 중 DB 연결을 쥐지 않는다. 기존 구간 체크포인트(`recovery_state`)·PARTIAL 재시도와 이어지게 한다.
- [ ] 옛 호환 트리거가 만드는 `legacy-adapter` 작업(자료 등록마다 QUEUED 로 생김)을 worker 가 집어 가지 않게 한다.
- 검증: 처리 도중 프로세스 종료 주입 → lease 만료 후 다른 worker 가 이어서 완료, 중복 카드 없음. 두 worker 경합 시 한 쪽만 처리.
  카테고리 재분류 작업도 같은 방식으로 옮길지 사용자에게 묻는다.

---

## Phase W5 — 품질 실험 (W3 전후 비교)

**목표:** W3 가 실제로 나아졌는지 같은 조건으로 잰다. 결과를 보기 전에 조건을 고정한다(D17·D18, `docs/dev/plan/W1_MEASUREMENT_PLAN.md` ⑤).

- [ ] 선행: 사용자가 요율표 `config/rate_card.json`(모델 단가)을 채우고 예산 상한을 승인한다. 없으면 원가 미관측으로 캠페인이 실패한다.
- [ ] W3 머지 직전 main 에 태그 `w-baseline-pre-w3`(사용자에게 요청).
- [ ] 사전등록 캠페인 파일(`docs/dev/plan/W_EVAL_CAMPAIGN_V1.md` 형식, Git 제외 경로): 채점기 `w_fact_score/v4`·`COMMON+CAFE`,
      정답지 hash(278건), 평가 정책 `w_user_confirmed_20260927.json`, 후보 CONTROL(기준선)·CONTROL_REPEAT(대조)·CANDIDATE(W3), 후보마다 3회, seed, 예산.
- [ ] 실행: 기준선 3 + 대조 3 × 2매장(12회)은 태그 버전으로, W3 3 + 대조 3 × 2매장(12회)은 W3 버전으로. `run_extract_eval.py --campaign ...`.
      A 매장에는 38분 영상이 있어 1회 비용이 크다 — 예산표에 반영한다.
- [ ] 판정: 반복별 순증의 **중앙값**(성능), 매번 성공/실패/변동(안정성), 모든 반복의 악화(안전성)를 따로 보고한다.
      채점 기준 변화(v3→v4)로 오른 수치를 모델 개선으로 보고하지 않는다.
- [ ] 결과는 `docs/dev/review/` 에 새 기록으로, 원시 결과는 Git 제외 경로에.

---

## 5. 참고 문서

- 정본: `docs/dev/ASKBUDDY_MVP_CURRENT.md`(§30·§31), 할 일: `docs/dev/DEV_TODO_CURRENT.md`(W1·W2·W3·W4·W5·J2 절)
- 측정: `docs/dev/plan/W1_MEASUREMENT_PLAN.md`, `docs/dev/review/W_SCORER_V4_20260928.md`, `docs/dev/review/W_USER_DECISIONS_2026092{7,8}.md`
- 공개 연결·R 인계: `docs/dev/plan/W_PUBLICATION_LINK_PLAN_20260927.md`, `docs/dev/plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md`,
  `docs/dev/plan/R_W_NEXT_AFTER_INDEX_REUSE_20260927.md`, 공동 절차 `docs/dev/plan/WR_JOINT_WORKFLOW.md`
- 계약: `api/app/contracts/card.py`(CardPlan·CardBlock·OccurrenceDisposition), `snapshot.py`(FactRevision·PublishedCard)
