# Phase A — 사실→카드 단일 경로 · 1회 삭제 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RAW 카드를 만드는 W 경로 셋(업로드 옛 조립·점주 답변 RAW 카드·점주 자유 본문 편집)과 W 플래그 다섯 개를 지우고, 점주 답변도 사실→원장→조립으로 보내며, 공개 카드에 새 사실이 붙으면 새 초안을 만들고, 배포 때 한 번 도는 삭제 migration 으로 기존 지식을 비운다.

**Architecture:** 업로드·점주 답변 모두 `추출 → 원장(_persist_ledger) → 대상 연결(fact_ledger) → 사실 조립(_prepare_fact_assembly/_persist_fact_cards) → 사실 블록 판` 한 길로 간다. 공개(`publish_cards`)는 사실 블록이 없는 판을 거절한다(fail closed). 판 1 은 트리거가 아니라 코드가 명시적으로 만든다. 공개 카드에 새 사실이 오면 모델 재조립 없이 "공개 판의 사실 + 이 자료의 새 사실"을 결정적으로 붙여 새 초안을 만든다.

**Tech Stack:** FastAPI·Python 3.12·asyncpg, PostgreSQL 15/17 + pgvector(Supabase migration), Next.js 16(web), pytest/unittest, Playwright(합성 API).

**Spec:** `docs/dev/plan/W_PHASE_A_FACT_ONLY_DESIGN_20261010.md` (설계). 시작 안내 `docs/dev/plan/W_FACT_ONLY_ROADMAP_20261010.md`. R 인계 `docs/dev/plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md` §13·R 이 할 일 12.

---

## 0. 계획 단계에서 정한 것 (2026-10-10 사용자 답)

| # | 질문 | 결정 |
|---|---|---|
| P-1 | R 인계 12-(d) 답이 없다. 옛 함수 3개(`publish_new_proposal`·`publish_existing_proposal`·`prepare_proposal`) 삭제는? | **코드 확인으로 삭제.** `api/app/learn/router.py` 는 세 함수를 import 하지 않는다(쓰는 곳은 W `scripts/verify_w_publication_flow.py` 뿐). **맨 뒤 과제(Task 13)** 로 지우고 인계 문서에 "코드로 확인, R 확인 대기" 로 적는다 |
| P-2 | v1 `/learn/pending/{id}/answer`(웹 `/owner/questions` 목록·`/owner/cards/proposals` 가 아직 씀)는 `approve_owner_proposal` 의 RAW 카드 만들기에 기댄다. 사실 초안이 없는 v1 제안은? | **거절하고 R 에 인계.** `approve_owner_proposal` 이 `ValueError`(R 라우트가 409 로 바꾼다). v1 NEW 는 R 라우트가 `FAILED` 로 남기고 점주 원문은 직원에게 그대로 전달된다. 새 v1 질문은 이미 `V2_REQUIRED` 로 막혀 있다 |
| P-3 | 트리거 제거·RAW 거절로 깨지는 R 소유 검증 3개(`verify_r_w3_consumer`·`verify_r_owner_candidates`·`verify_r_legacy_publication`)는? | **W 가 고치고 인계에 적는다.** 앞의 둘은 픽스처만, `legacy_publication` 은 "사실 초안 없는 v1 NEW → FAILED" 기대로 바꾼다. R 소유 파일 예외로 인계 문서에 변경을 남긴다 |

계획 단계에서 W 가 정한 것(사용자에게 알림, 되돌릴 수 있음):
- 점주 답변 자료 ↔ 답변 연결은 새 표 `owner_answer_sources`(가산 migration). `fact_owner_answer_links` 는 쓰지 않는다 — 그 표의 행은 근거를 "점주 답변 출처(파일 없음)" 로 만들어 공개 단계가 싣지 않는다. 새 경로의 근거는 `OWNER_TEXT` 자료 occurrence(`source_id`+`occurrence_id`)다.
- A-D4 새 초안은 **모델 재조립을 하지 않는다.** 공개 판에 고정된 사실 + 이 자료가 처음 가져온 사실을 블록 규칙대로 붙인다. 이유: 대상의 head 사실을 통째로 다시 조립하면 점주가 뺀 사실(W3b `OWNER_REMOVED`)이 되살아나고 공개 카드의 배치가 흔들린다. 공개 카드가 여러 장(` i/n`)인 대상·수동 배정·점주 초안이 있는 카드는 지금처럼 `EXISTING_CARD` 보류.
- 작업 완료 알림 문구("새 카드가 준비됐어요 / 검토할 업무 카드 N개")는 R 소유 `api/app/notifications/service.py` 라 고치지 않고 인계한다. W 소유 web 작업 상태 문구만 "반영된 카드" 로 바꾼다.
- `CardDetail.fact_edit_enabled` 응답 칸은 플래그와 함께 지운다(web 도 W 소유라 함께 고친다).

## Global Constraints

모든 Task 의 요구 사항에 이 절이 포함된다.

- **커밋·푸시 금지.** 사용자 규칙: `git commit`·`git push` 를 하지 않고 할지 묻지도 않는다. 각 Task 의 마지막 단계는 "변경 파일 목록 기록" 이다. 브랜치는 `w/phase-a-fact-only`(같은 폴더).
- **유료 호출 0.** `INGEST_MODE` 는 기본 `mock`. 모델·임베딩은 합성 대역(`patch`)으로 검증한다. 외부 API 를 부르지 않는다.
- **매장 격리(D1):** 새 DB 함수는 `store_id` 필수 인자, 모든 조회에 `where store_id = …`. store_id 는 JWT·worker 신뢰 범위에서만. `api/app/`·`supabase/migrations/` 를 건드린 Task 는 `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest api/app/cards api/app/publish api/app/learn/knowledge_apply.py` 를 돌린다. 기준: `api/app/ingest/repository.py` 기존 위반 15건 외 새 위반 0.
- **R 소유 파일은 수정하지 않는다:** `api/app/reg/*`, `api/app/learn/router.py`, `answering.py`, `answer_storage.py`, `owner_handoff.py`, `owner_publication.py`, `owner_delivery.py`, `approved_renderer.py`, `v2_router.py`, `knowledge_loop.py`, `api/app/auth/*`, `api/app/notifications/*`, `api/app/contracts/*`. **예외(P-3):** `api/scripts/verify_r_w3_consumer.py`·`verify_r_owner_candidates.py`·`verify_r_legacy_publication.py` 의 픽스처·기대값만.
- **R 이 import 하는 W 이름을 지키기:** `approve_owner_proposal(pool, *, store_id, member_id, actor_user_id, proposal_id, usage_context, notify_r=None) -> PublishCardsResult`, `app.publish.approval.PublishCardsResult`·`CardChange`·`publish_cards`, `app.cards.owner_answer_worker._index_ready`·`index_status`(R 테스트 `test_r_w3_consumption.py` 가 patch), `app.publish.empty.ensure_initial_publication`.
- **공통 파일**(`api/app/config.py`, `api/app/main.py`, `api/scripts/verify_r_schema_rebuild.py`)은 가산 변경만. 예외: 사용자 결정 A-U1 에 따른 `config.py` 플래그 삭제.
- **migration:** 적용된 파일을 고치지 않는다. 새 파일 이름 `supabase/migrations/YYYYMMDDHHMMSS_w_<주제>.sql`. 이 계획의 새 파일: `20261010090000_w_owner_answer_sources.sql`, `20261010120000_w_drop_legacy_card_version_trigger.sql`, `20261010110000_w_wipe_knowledge_once.sql`.
- **설정·프롬프트:** 모델명·임계값은 `config.py`, 프롬프트는 `api/prompts/`. 이 계획은 **추출 프롬프트 파일을 바꾸지 않는다**(재사용 키가 바뀐다). 점주 답변 문맥은 입력 글 안에 머리말로 넣는다.
- **LLM 호출 중 DB 연결을 쥐지 않는다**(짧은 연결·`ShortSession`). 원가 원장은 기존 경로 그대로.
- **주석·문서는 한국어.** 평가용 실제 자료의 브랜드·상호·메뉴 고유명을 어디에도 쓰지 않는다. 합성 이름(`음료Z`·`합성 카드`)만.
- **web:** 단위 테스트 러너가 없다. "테스트 통과" 라고 쓰지 않는다. `cd web && pnpm check` 와 합성 API Playwright 확인을 구분해 보고한다.
- **테스트 명령:** `cd api && .venv/bin/python -m pytest -q tests/<파일>`. 전체: `cd api && .venv/bin/python -m pytest -q tests`(기준 2176 passed, 6 skipped, 4 xfailed — 이 계획에서 레거시 테스트를 지우므로 수가 줄 수 있다. 줄어든 이유를 보고한다).
- **실제 DB 검증:**
  ```bash
  docker run -d --rm --name askbuddy-w-verify -p 127.0.0.1:55439:5432 \
    -e POSTGRES_PASSWORD=synthetic-local-test -e POSTGRES_DB=usage_verify pgvector/pgvector:pg17
  cd api && PYTHONPATH=. PYTHONUTF8=1 .venv/bin/python -B scripts/verify_r_schema_rebuild.py
  docker stop askbuddy-w-verify
  ```
  **Task 2~6 사이에는 재구축 검증의 RAW 픽스처 구간이 빨갛다**(Task 2 가 RAW 공개를 막고, Task 7 이 픽스처를 고친다). Task 2~6 은 단위 테스트와 각 Task 가 지정한 시나리오만 초록이면 된다. **Task 7 끝부터 재구축 검증 전체가 초록이어야 한다.**

## Review Focus

테스트가 직접 다루지 않지만 사람에게 가장 먼저 닥칠 입력·상황(가능성 높은 순). 각 줄의 테스트는 해당 Task 에 넣었다.

1. **점주 답변이 질문만 되풀이하거나 인사뿐이다**(사실 0개) → 카드·공개판이 바뀌지 않고 R 에는 `REVIEW`, 제안 승인 시 "사실을 찾지 못했어요" 409. → Task 6 `test_no_facts_reports_review_without_card`, Task 6 `test_approve_without_drafts_raises`.
2. **모델이 질문 문장을 사실로 뽑는다** → 질문에만 있는 원문은 원장에 들어가지 않는다. → Task 5 `test_drop_question_only_keeps_answer_facts`.
3. **같은 점주 답변 사건이 중간 실패 뒤 다시 돈다**(추출 뒤·조립 전 장애) → 사실이 두 번 쌓이지 않고 이어서 조립한다. → Task 5 `test_resume_skips_extraction_when_ledger_exists`.
4. **점주가 사실을 뺀 공개 카드에 새 자료가 같은 대상 사실을 가져온다** → 새 초안은 공개 판 사실 + 이 자료의 새 사실만, 뺀 사실은 되살아나지 않는다(이 자료가 다시 말한 경우만 들어간다). → Task 4 `test_append_facts_keeps_published_layout` / `test_new_fact_ids_only_from_this_source`.
5. **삭제 migration 이 평가 기록·비용 원장을 건드린다** → 비용 원장·평가 표 행 수 불변, 실패하면 멈추고 사용자에게 묻는다. → Task 9 시나리오 (a) 의 "남길 표 행 수 불변" 검사.

---

## 파일 구조

| 파일 | 책임 | Task |
|---|---|---|
| `api/app/config.py` | W 플래그 5개 삭제 | 1·2·3 |
| `api/app/ingest/pipeline.py` | 단일 사실 경로, 옛 조립 삭제, REDRAFT 분기, 운영 원가 실행 범위 | 1·4·5 |
| `api/app/ingest/extract/{__init__,gemini,mock}.py`, `api/prompts/assemble_cards.ko.txt` | 옛 조립 호출 삭제 | 1 |
| `api/app/ingest/schemas.py` | `ExtractedCard`·`ExtractionResult` 등 옛 조립 스키마 삭제 | 1 |
| `api/app/ingest/job_worker.py` | `card_count` = 이 자료가 이어진 카드 수 | 1 |
| `api/app/publish/content.py`, `approval.py` | RAW 삭제, 블록 없는 판 거절 | 2 |
| `api/app/cards/router.py`, `schemas.py`, `web/app/owner/cards/[cardId]/page.tsx`, `web/lib/api.ts`, `web/components/owner/fact-card/*` | 자유 본문 편집·편집 플래그 삭제 | 3 |
| `api/app/ingest/card_plan.py` | `append_facts`(공개 카드에 새 사실 붙이기, 순수) | 4 |
| `api/app/ingest/fact_cards.py` | `REDRAFT` 상태 판정, `redraft_published_card` | 4 |
| `api/scripts/_fact_card_fixture.py` | 검증용 사실 카드 만들기 도우미 | 4 |
| `api/scripts/verify_w_fact_only.py` | Phase A 실제 DB 시나리오 (a)~(d) | 4·6·7·9 |
| `web/components/owner/background-job-status.tsx` | "반영된 카드" 문구 | 4 |
| `supabase/migrations/20261010090000_w_owner_answer_sources.sql` | 점주 답변 ↔ OWNER_TEXT 자료 | 5 |
| `api/app/ingest/owner_text.py` | 점주 답변 자료 만들기·수집(추출→원장→조립)·결과 카드 조회 | 5 |
| `api/app/cards/owner_answer_worker.py` | 관계 분석 대신 사실 수집으로 교체 | 6 |
| `api/app/learn/knowledge_apply.py` | `approve_owner_proposal` 안쪽 = 사실 초안 공개 | 6 |
| `supabase/migrations/20261010120000_w_drop_legacy_card_version_trigger.sql`, `api/app/ingest/repository.py` | 트리거 제거, 판 1 명시 생성 | 7 |
| `supabase/migrations/20261010110000_w_wipe_knowledge_once.sql` | 1회 삭제 | 9 |
| `api/scripts/wipe_storage_sources.py` | Storage 정리(기본 dry-run) | 10 |
| `db/002_seed_demo.sql`, `api/scripts/demo_seed.py` | 카드 없는 데모 시드 | 11 |
| `docs/dev/plan/FACT_ONLY_ROLLOUT.md`, 인계·TODO 문서 | 절차서·인계 | 12 |

---

### Task 1: 업로드 단일 사실 경로 — 플래그 3개와 옛 조립 삭제

**Files:**
- Modify: `api/app/config.py` (`w_entity_revision_enabled`·`w_upload_proposals_enabled`·`w_fact_assembly_enabled` 필드·주석, 검증기 `config.py:245-248` 의 두 검사)
- Modify: `api/app/ingest/pipeline.py` (`process_source` 의 `fact_assembly_on` 분기, `_persist_ledger` 의 두 플래그 분기, `_persist_fact_cards` 의 제안 플래그 분기; 삭제: `assemble_assertions`·`_ledger_keys`·`_persist`)
- Modify: `api/app/ingest/job_worker.py:119-162` (`card_count` 단일 질의)
- Modify: `api/app/ingest/variant_split.py:15` (docstring 의 플래그 언급)
- Modify: `api/app/ingest/extract/__init__.py` (삭제 `assemble_cards`), `extract/gemini.py` (삭제 `assemble`·`render_assemble_prompt`·조립 프롬프트 경로 상수), `extract/mock.py` (삭제 `assemble`·`_assembled`)
- Delete: `api/prompts/assemble_cards.ko.txt`
- Modify: `api/app/ingest/schemas.py` (삭제 `ExtractedCard`·`ExtractionResult`; `ExtractedFact` 는 남은 사용처가 없을 때만 삭제 — `grep -rn ExtractedFact api/app api/scripts api/tests` 로 확인)
- Modify/Delete tests: `tests/test_w2_entity_names.py`, `test_w2_impact.py`, `test_w2_ledger_wiring.py`, `test_w3_variant_split.py`, `test_w3a_batching.py`, `test_w3a_pipeline_wiring.py`, `test_fact_pipeline_cleanup.py`, `test_ingest_*.py`, `test_raw_responses.py`, `test_truncation_recovery.py`, `test_layout_pipeline.py` 중 옛 조립·플래그를 쓰는 것
- Modify scripts: `api/scripts/verify_w_raw_responses.py`, `verify_w_entity_revision.py` (옛 조립 대역 → `assemble_plan` 대역), `probe_w3a_assemble_concurrency.py`(플래그 토글 삭제)
- Delete scripts: `api/scripts/verify_w3_flag_readiness.py`, `api/scripts/probe_w3_flag_throughput.py` (플래그 켜기/끄기 비교가 유일한 목적)
- Test: `api/tests/test_wa_upload_single_path.py` (새 파일)

**Interfaces:**
- Consumes: 없음
- Produces: `pipeline.process_source(...)` 는 항상 `_prepare_fact_assembly` → `_persist_fact_cards` 로 간다. `pipeline._persist_ledger(conn, store_id, source_id, source_type, assertions) -> dict[str, int]` 은 항상 `split_hot_ice` 후 `fact_ledger.link_source_facts` 를 부른다. `_persist_fact_cards` 는 항상 `impact.record_upload_proposals` 를 부른다.

- [ ] **Step 1: 실패하는 테스트 쓰기** — `api/tests/test_wa_upload_single_path.py`

```python
"""Phase A Task 1 — 업로드는 사실 경로 하나만 남는다."""
from __future__ import annotations

import inspect
from pathlib import Path

from app import config
from app.ingest import extract, pipeline, schemas
from app.ingest.extract import gemini, mock

REMOVED_FLAGS = ("w_entity_revision_enabled", "w_upload_proposals_enabled", "w_fact_assembly_enabled")


def test_settings_have_no_upload_flags():
    fields = config.Settings.model_fields
    for name in REMOVED_FLAGS:
        assert name not in fields, name


def test_legacy_assembly_is_gone():
    for module, name in ((pipeline, "assemble_assertions"), (pipeline, "_persist"),
                         (pipeline, "_ledger_keys"), (extract, "assemble_cards"),
                         (gemini, "assemble"), (gemini, "render_assemble_prompt"),
                         (mock, "assemble"), (mock, "_assembled"),
                         (schemas, "ExtractedCard"), (schemas, "ExtractionResult")):
        assert not hasattr(module, name), f"{module.__name__}.{name}"
    prompt = Path(pipeline.__file__).resolve().parents[2] / "prompts" / "assemble_cards.ko.txt"
    assert not prompt.exists()


def test_no_flag_reads_left_in_ingest():
    for module in (pipeline,):
        source = inspect.getsource(module)
        for name in REMOVED_FLAGS:
            assert name not in source, name
```

- [ ] **Step 2: 실패 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests/test_wa_upload_single_path.py` / Expected: 3 FAIL (`w_entity_revision_enabled` 가 fields 에 있음, `assemble_assertions` 존재 등)

- [ ] **Step 3: 구현**
  - `config.py`: 세 필드와 위 주석 줄을 지운다. 검증기에서 두 `if` 를 지운다. 검증기에 다른 검사가 없으면 검증기 함수째 지운다.
  - `pipeline.process_source`: `fact_assembly_on` 변수와 `else` 쪽(`assemble_assertions`·`result`)을 지우고 `_prepare_fact_assembly`·`_persist_fact_cards` 만 남긴다. 마지막 로그의 `unresolved_total if fact_assembly_on else len(result.unresolved)` → `unresolved_total`.
  - `_persist_ledger`: 두 `if getattr(s, "w_entity_revision_enabled", False):` 의 본문을 무조건 실행으로 바꾼다(들여쓰기만 줄인다).
  - `_persist_fact_cards`: `if getattr(get_settings(), "w_upload_proposals_enabled", False):` 본문을 무조건 실행.
  - `assemble_assertions`·`_ledger_keys`·`_persist` 와 그것만 쓰던 import(`split_refs`·`ExtractionResult` 등)를 지운다. 섹션 주석 `# ── W3a 대상 단위 사실 조립 (플래그 w_fact_assembly_enabled)` → `# ── 대상 단위 사실 조립`.
  - `job_worker.py:119-162`: `fact_assembly_on` 분기를 없애고 `fact_occurrences` 기준 두 질의만 남긴다(주석: "이 자료 occurrence 가 이어진 카드 수 — 다른 자료가 만든 카드에 실렸어도 이 자료의 결과다").
  - `extract/__init__.assemble_cards`, `gemini.assemble`·`render_assemble_prompt`·조립 프롬프트 경로 상수, `mock.assemble`·`_assembled`, `schemas.ExtractedCard`·`ExtractionResult` 삭제. 지운 뒤 `grep -rn -E "ExtractedCard|ExtractionResult|assemble_cards|render_assemble_prompt" api/app api/scripts api/tests` 가 비어야 한다.
  - 테스트·스크립트: 플래그를 `patch`·`replace` 로 켜던 줄은 지우고(이제 항상 켜짐), "꺼짐 = 옛 동작" 을 검사하던 테스트 함수는 지운다. 옛 조립(`assemble_assertions`·`_persist`)만 검사하던 테스트 함수는 지운다. 스크립트의 옛 조립 대역(`ExtractionResult(cards=[...])` 를 돌려주는 가짜 `gemini._call`)은 `CardPlanBatch` 를 돌려주는 사실 조립 대역으로 바꾸거나, 그 시나리오가 옛 조립 전용이면 지운다(지운 시나리오 이름을 보고에 적는다).
- [ ] **Step 4: 통과 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests` / Expected: 새 테스트 3 PASS, 전체 실패 0. 지운 테스트 수를 기록.
- [ ] **Step 5: 격리 검사** — Run: `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest` / Expected: 기존 15건 외 새 위반 0.
- [ ] **Step 6: 변경 파일 목록 기록**(커밋하지 않는다).

---

### Task 2: 공개 단계 RAW 제거 — 사실 블록 없는 판은 공개 거절

**Files:**
- Modify: `api/app/publish/content.py` (삭제: `_split_raw_spans`·`RAW_SPAN_MAX`(다른 사용처 없을 때)·`_resolve_provenance`·`ensure_raw_blocks`·`_raw_block`·레거시 판 분기·이름공간 가드·`allow_owner_answer` 인자; 모듈 docstring 갱신)
- Modify: `api/app/publish/approval.py` (`_fix_blocks` → `_check_cards`, `allow_owner_answer` 삭제)
- Modify: `api/app/config.py` (`w_owner_answer_raw_publish` 삭제)
- Modify: `api/app/learn/knowledge_apply.py:605-610` (플래그 검사 블록 삭제 — 안쪽 교체는 Task 6)
- Modify tests: `tests/test_w3a_publish_content.py` (`_LegacyConn`·`LegacyPathTest`·`_MixedConn`·`EntityNamespaceGuardTest` 삭제, `allow_owner_answer=` 인자 삭제), `tests/test_w_publish_content.py`, `tests/test_w_publish_approval.py`, `tests/test_w_owner_proposal_approval.py`(플래그 patch 삭제)
- Delete: `tests/test_w_raw_span_owner_answer.py`
- Test: `api/tests/test_wa_publish_fact_only.py` (새 파일)

**Interfaces:**
- Consumes: 없음
- Produces: `build_knowledge_content(conn, *, store_id: int, manifest: dict[int, int], glossary_version: str) -> KnowledgeContent` — 사실 블록 없는 판·RAW 블록 판이면 `InvalidContent`. 반환 `raw_spans` 는 항상 `()`. `card_version_fact_provenance` 의 점주 답변 출처 행(occurrence 없음)은 싣지 않는다(근거가 하나도 남지 않으면 `NoProvenance`). `publish_cards(...)` 시그니처 불변. 바뀐 카드가 블록 없는 판이면 `PublishCardsResult(status="INVALID_CONTENT")`, 바뀌지 않은 공개 카드가 그렇다면 manifest 에서 빼고 경고(지금 `_fix_blocks` 규칙 그대로).

- [ ] **Step 1: 실패하는 테스트 쓰기** — `api/tests/test_wa_publish_fact_only.py`

```python
"""Phase A Task 2 — 공개판은 사실 블록 카드만 싣는다."""
from __future__ import annotations

import inspect
import unittest
from decimal import Decimal

from app import config
from app.publish import approval, content
from app.publish.content import InvalidContent, NoProvenance, build_knowledge_content

HEX = "ab" * 32


class _Conn:
    """판 하나. blocks·facts·provenance 를 주어진 대로 돌려준다."""

    def __init__(self, *, blocks, facts, provenance=()):
        self.blocks, self.facts, self.provenance = blocks, facts, list(provenance)

    async def fetchrow(self, query, *args):
        if "from card_versions" in query:
            return {"title": "음료Z"}
        raise AssertionError(query)

    async def fetch(self, query, *args):
        if "from card_version_blocks" in query:
            return self.blocks
        if "from card_block_facts" in query:
            return self.facts
        if "from fact_revisions" in query:
            return [{"fact_revision_id": 10, "fact_id": 3, "entity_id": 4,
                     "original_assertion": "음료Z 물 225ml", "assertion": "음료Z 물 225ml",
                     "subject": "음료Z", "predicate": "물", "variant_temperature": None,
                     "variant_size": None, "quantity_value": Decimal("225"),
                     "quantity_unit": "ml", "value_text": None, "polarity": "AFFIRM",
                     "step_order": None, "conditions": "[]", "exceptions": "[]"}]
        if "from fact_revision_requires" in query:
            return []
        if "from card_version_fact_provenance" in query:
            return self.provenance
        raise AssertionError(query)


_FACT_BLOCK = [{"block_id": "b1", "kind": "QUANTITIES", "block_order": 1, "raw_span_id": None}]
_FACT_ROW = [{"block_id": "b1", "fact_revision_id": 10, "position": 1}]


def _occ_row():
    return {"provenance_id": 1, "fact_revision_id": 10, "occurrence_id": 5, "owner_answer_id": None,
            "source_id": 9, "source_content_hash": HEX, "locator_type": "LINE",
            "locator": '{"line": 1}'}


def _owner_row():
    return {"provenance_id": 2, "fact_revision_id": 10, "occurrence_id": None,
            "owner_answer_id": 7, "source_id": None, "source_content_hash": None,
            "locator_type": None, "locator": None}


class FactOnlyContentTest(unittest.IsolatedAsyncioTestCase):
    async def test_blockless_version_is_invalid(self):
        with self.assertRaises(InvalidContent):
            await build_knowledge_content(_Conn(blocks=[], facts=[]), store_id=7,
                                          manifest={1: 10}, glossary_version="glossary/v1")

    async def test_raw_block_version_is_invalid(self):
        raw = [{"block_id": "raw1", "kind": "RAW", "block_order": 1, "raw_span_id": 500}]
        with self.assertRaises(InvalidContent):
            await build_knowledge_content(_Conn(blocks=raw, facts=[]), store_id=7,
                                          manifest={1: 10}, glossary_version="glossary/v1")

    async def test_owner_answer_only_provenance_is_not_published(self):
        with self.assertRaises(NoProvenance):
            await build_knowledge_content(
                _Conn(blocks=_FACT_BLOCK, facts=_FACT_ROW, provenance=[_owner_row()]),
                store_id=7, manifest={1: 10}, glossary_version="glossary/v1")

    async def test_fact_card_publishes_without_raw_spans(self):
        result = await build_knowledge_content(
            _Conn(blocks=_FACT_BLOCK, facts=_FACT_ROW, provenance=[_occ_row(), _owner_row()]),
            store_id=7, manifest={1: 10}, glossary_version="glossary/v1")
        self.assertEqual(result.raw_spans, ())
        (fact,) = result.fact_revisions
        self.assertEqual([p.occurrence_id for p in fact.provenance], ["5"])


def test_raw_helpers_and_flag_are_gone():
    for name in ("ensure_raw_blocks", "_resolve_provenance", "_raw_block", "_split_raw_spans"):
        assert not hasattr(content, name), name
    assert not hasattr(approval, "_fix_blocks")
    assert "allow_owner_answer" not in inspect.signature(build_knowledge_content).parameters
    assert "w_owner_answer_raw_publish" not in config.Settings.model_fields
```

- [ ] **Step 2: 실패 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests/test_wa_publish_fact_only.py` / Expected: FAIL (블록 없는 판이 `ValueError`, RAW 판이 공개됨, 점주 답변 출처가 실림 등)
- [ ] **Step 3: 구현**
  - `content.build_knowledge_content`: `allow_owner_answer` 인자를 지운다. 판마다 블록 행을 읽고, (1) 블록이 없거나 (2) 어느 블록이든 `raw_span_id is not None` 이거나 (3) `card_block_facts` 행이 없으면 `raise InvalidContent(f"카드 판 {card_version_id} 은 사실 블록 카드가 아니다 — 사실 카드만 공개한다")`. 나머지는 `_fact_card` 경로만. 이름공간 가드(`legacy_entity_ids`·`fact_entity_ids`·`collided`)와 `spans_by_id` 를 지우고 `raw_spans=()` 로 돌려준다.
  - `_fact_card`: `spans_by_id`·`allow_owner_answer` 인자와 RAW 블록 분기를 지운다. 근거 행 중 `occurrence_id is None` 은 건너뛴다(주석: "점주 답변 출처(파일 없음)는 공개하지 않는다 — 점주 답변 근거는 OWNER_TEXT 자료 occurrence 로 온다").
  - `approval._fix_blocks` → `_check_cards(conn, *, store_id, manifest, changed_ids, glossary_version) -> dict[int, int]`: 카드마다 savepoint 안에서 `build_knowledge_content(conn, store_id=store_id, manifest={card_id: version_id}, glossary_version=glossary_version)` 만 부른다. 예외 처리 규칙(바뀐 카드면 `_ChangedWithoutProvenance`/`_ChangedInvalidContent`, 아니면 manifest 에서 빼고 경고)은 그대로. docstring 을 "사실 블록 카드인지 한 장씩 확인한다" 로.
  - `publish_cards`: `allow_owner_answer` 줄과 인자 전달을 지운다.
  - `config.py`: `w_owner_answer_raw_publish` 와 위 주석 삭제.
  - `knowledge_apply.approve_owner_proposal`: `if not get_settings().w_owner_answer_raw_publish: ... return PublishCardsResult(status="NO_PROVENANCE")` 블록 삭제(나머지는 Task 6 이 바꾼다). `get_settings` import 가 남는 곳이 없으면 지운다.
  - `grep -rn -E "ensure_raw_blocks|allow_owner_answer|w_owner_answer_raw_publish|W_OWNER_ANSWER_RAW_PUBLISH" api/app api/tests` 가 비어야 한다. `api/scripts` 에 남은 것은 Task 7 이 정리한다(이 Task 에서는 목록만 기록).
  - 테스트: `test_w3a_publish_content.py` 의 레거시·혼합 클래스 삭제, `allow_owner_answer=True` 인자 삭제(점주 답변 출처 순서 검사 `test_single_card_provenance_order_matches_merge_rule` 은 점주 답변 행을 빼고 occurrence 순서만 검사하도록 기대값 수정). `test_w_raw_span_owner_answer.py` 삭제. `test_w_publish_content.py`·`test_w_publish_approval.py` 에서 RAW·`ensure_raw_blocks`·`_fix_blocks` 를 검사하던 테스트는 지우거나 `_check_cards` 로 이름만 바꾼다(검사 의미가 "블록 고정" 이면 지운다).
- [ ] **Step 4: 통과 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests` / Expected: 실패 0.
- [ ] **Step 5: 격리 검사** — `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/publish api/app/learn/knowledge_apply.py` / 새 위반 0.
- [ ] **Step 6: 변경 파일 목록 기록.** 재구축 검증의 RAW 픽스처 구간은 이 Task 뒤 빨갛다(Task 7 이 고친다) — 보고에 그렇게 적는다.

---

### Task 3: 점주 자유 본문 편집 삭제 — 사실 단위 편집만

**Files:**
- Modify: `api/app/cards/router.py` (삭제: `PATCH /{card_id}/draft` `update_draft`; `_detail` 의 `fact_edit_enabled`; `get_card_facts`·`parse_card_facts`·`save_card_facts` 의 `w_fact_card_edit_enabled` 검사)
- Modify: `api/app/cards/schemas.py` (삭제 `DraftUpdateRequest`, `CardDetail.fact_edit_enabled`; `CardFactsView`·`build_facts_view` 의 `flag_on` 인자가 있으면 삭제)
- Modify: `api/app/config.py` (`w_fact_card_edit_enabled` 삭제)
- Modify: `web/lib/api.ts` (삭제 `updateProductCardDraft`, `CardDetailDto.fact_edit_enabled`)
- Modify: `web/app/owner/cards/[cardId]/page.tsx` (자유 편집 상태·폼·`saveDraft`·`startEdit`·편집 화면 분기 삭제. `card.fact_card` 가 false 인 카드(1회 삭제 뒤엔 없다)는 읽기 전용 `NumberedContent` 만 보이고 "고치기" 버튼이 없다)
- Modify: `web/components/owner/fact-card/fact-card-panel.tsx`, `fact-messages.ts` (`fact_edit_enabled`·`FACT_EDIT_DISABLED` 문구 삭제)
- Delete/Modify tests: `tests/test_w3b_patch_guard.py` (아래 새 테스트로 대체 후 삭제), `test_w3b_fact_edit_save.py`·`test_w3b_fact_parse.py`·`test_w3b_schemas.py` 의 플래그 patch·`FACT_EDIT_DISABLED` 검사 삭제
- Test: `api/tests/test_wa_card_text_edit_removed.py` (새 파일)

**Interfaces:**
- Consumes: 없음
- Produces: `CardDetail` 에 `fact_card: bool` 은 남고 `fact_edit_enabled` 는 없다. `/cards/{id}/facts`·`/facts/parse`·`PUT /facts` 는 플래그 없이 열려 있다(인증·매장·점주 검사는 그대로). `cards.repository.create_draft` 는 이 Task 에서 남긴다(`knowledge_apply` 가 아직 쓴다 — Task 6 이 지운다).

- [ ] **Step 1: 실패하는 테스트 쓰기** — `api/tests/test_wa_card_text_edit_removed.py`

```python
"""Phase A Task 3 — 자유 본문 PATCH 와 편집 플래그가 없다."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import config
from app.cards import schemas
from app.main import app


def test_draft_patch_route_is_gone():
    paths = {(r.path, m) for r in app.routes for m in getattr(r, "methods", set())}
    assert ("/cards/{card_id}/draft", "PATCH") not in paths
    spec = TestClient(app).get("/openapi.json").json()
    assert "/cards/{card_id}/draft" not in spec["paths"]


def test_fact_edit_flag_is_gone():
    assert "w_fact_card_edit_enabled" not in config.Settings.model_fields
    assert "fact_edit_enabled" not in schemas.CardDetail.model_fields
    assert not hasattr(schemas, "DraftUpdateRequest")
```

  (라우터가 `/cards` 접두사가 아닌 다른 접두사로 붙어 있으면 `app.routes` 를 출력해 실제 경로로 바꾼다.)
- [ ] **Step 2: 실패 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests/test_wa_card_text_edit_removed.py` / Expected: 2 FAIL
- [ ] **Step 3: API 구현** — 위 Files 대로 지운다. `get_card_facts` 의 `build_facts_view(state, rows, heads, flag_on=flag_on)` 는 `flag_on` 인자를 함수에서 없애고 "편집 가능" 판정이 플래그에 기대던 부분은 항상 켜진 쪽으로 둔다. `test_w3b_patch_guard.py` 의 내용(사실 카드 PATCH 409)은 라우트가 없어졌으므로 파일째 지운다.
- [ ] **Step 4: 통과 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests` / Expected: 실패 0.
- [ ] **Step 5: web 구현** — `page.tsx` 에서 `editing`·`form`·`saveDraft`·`startEdit`·`updateProductCardDraft` import 와 그 화면 분기를 지운다. 버튼 영역은:

```tsx
{card.fact_card && factEditor.canEdit && (
  <Button variant={canPublish ? "secondary" : "primary"} onClick={factEditor.start}>
    고치기
  </Button>
)}
```

  본문 영역은 `card.fact_card ? <FactCardPanel …/> : <Surface …><NumberedContent content={content} /></Surface>` 를 유지한다(옛 카드 읽기 전용). 주석 "사실 카드가 아닌 옛 카드는 아래 자유 글 편집을 그대로 쓴다" → "사실 카드가 아닌 카드는 읽기만 한다(1회 삭제 뒤엔 없다)". `fact-card-panel.tsx:236` 은 `view.entity_problem ? ENTITY_TEXT : "지금은 이 카드를 사실 단위로 고칠 수 없어요."` 로.
- [ ] **Step 6: web 확인** — Run: `cd web && pnpm check` / Expected: 오류 0. 이어서 저장소 스킬 `web-async-state-check`, `ui-state-walkthrough`(합성 API Playwright: 카드 상세에서 자유 편집 textarea 가 없고 사실 카드 "고치기" 가 사실 편집 시트를 연다, 403·409 오류 상태가 깨지지 않는다)를 쓰고 결과를 정적 검사와 구분해 기록한다. 브라우저를 못 띄웠으면 그렇게 적는다.
- [ ] **Step 7: 격리 검사·변경 파일 목록 기록.**

---

### Task 4: 공개 카드 대상에 새 사실 → 새 초안 (A-D4) · 검증 도우미 · "반영된 카드"

**Files:**
- Modify: `api/app/ingest/card_plan.py` (새 순수 함수 `append_facts`)
- Modify: `api/app/ingest/fact_cards.py` (`_classify_rows` 분리, 모드 `REDRAFT`, `REVIEW_NEW_FACTS`, `new_fact_ids_for_source`, `redraft_published_card`)
- Modify: `api/app/ingest/pipeline.py` (`_prepare_fact_assembly` 가 REDRAFT 대상을 모델 입력에서 뺀다, `_persist_fact_cards` 의 REDRAFT 분기)
- Modify: `api/app/ingest/job_worker.py:19-20` (`NO_NEW_CARD_PENDING_MESSAGE` = "카드에 반영되지 않고 검수할 사실이 남았습니다.")
- Modify: `web/components/owner/background-job-status.tsx:114` ("생성 카드" → "반영된 카드")
- Create: `api/scripts/_fact_card_fixture.py`
- Create: `api/scripts/verify_w_fact_only.py` (시나리오 (c))
- Modify: `api/scripts/verify_r_schema_rebuild.py` (가산: `verify_w_fact_only` 호출 한 줄)
- Test: `api/tests/test_wa_redraft.py` (새 파일)

**Interfaces:**
- Consumes: Task 1 의 단일 경로(`_prepare_fact_assembly`·`_persist_fact_cards` 항상 실행).
- Produces:
  - `card_plan.append_facts(layout: Sequence[tuple[str, tuple[int, ...]]], group: EntityGroup, new_ids: Sequence[int], *, category_name: str) -> ValidatedCard` — `layout` 은 공개 판의 `(kind, fact_revision_ids)` 블록 순서. 새 판 id 를 같은 종류·같은 규격의 첫 블록 뒤에 붙이고(STEPS 는 `(step_order, fact_revision_id)` 로 다시 정렬), 맞는 블록이 없으면 그 종류의 새 블록을 끝에 둔다. 결과는 `validate_proposals(group, [ProposedCard(category_name, blocks)])` 의 유일한 카드. 실패하면 `PlanInvalid`.
  - `fact_cards.EntityCardState.mode` ∈ `{"NEW","REASSEMBLE","REDRAFT","DEFER"}`. REDRAFT 조건: 관련 카드가 **정확히 1장**이고 `published_version_id is not None` · `draft_version_id == published_version_id` · `assignment_type == 'AUTOMATIC'` · `review_status == 'APPROVED'` · 초안 판에 블록 사실 있음 · 대상이 병합 사슬 안.
  - `fact_cards.REVIEW_NEW_FACTS = "NEW_FACTS"`.
  - `fact_cards.new_fact_ids_for_source(conn, store_id, *, source_id, entity_id, pinned_fact_ids) -> list[int]` — 이 자료의 `REVIEW_PENDING` occurrence 가 가리키는 이 대상의 사실 중 공개 판에 없는 것(fact_id 오름차순).
  - `fact_cards.redraft_published_card(conn, store_id, *, source_id, state: EntityCardState) -> WrittenEntity` — 호출자가 트랜잭션·매장 지식 잠금을 쥔다. 잠금 아래 다시 판정해 REDRAFT 가 아니면 `deferred_reason=REASON_EXISTING_CARD`. 새 사실이 없으면 새 판 없이 이 자료의 해당 occurrence 만 그 카드로 LINKED(`new_version_ids=()`). 있으면 `create_extraction_draft` → `pin_card_version` → `write_version_evidence` → `replace_legacy_facts` → 카드 `needs_review_reason = 'NEW_FACTS'`(review_status 는 APPROVED 그대로) → 붙인 사실의 occurrence LINKED.
  - `scripts/_fact_card_fixture.seed_fact_card(pool, *, store_id: int, owner_user_id: int, assertions: list[ExtractedAssertion], title: str = "합성 자료") -> tuple[int, int]` — OWNER_TEXT 자료를 만들고 원장·조립(mock 조립)을 거쳐 사실 카드 초안을 만든다. `(card_id, draft_version_id)` (카드가 여러 장이면 card_id 최소). 공개는 하지 않는다.
  - `scripts/_fact_card_fixture.publish_card(pool, *, store_id, member_id, actor_user_id, card_id) -> PublishCardsResult` — 합성 벡터로 `publish_cards`.

- [ ] **Step 1: 실패하는 테스트 쓰기** — `api/tests/test_wa_redraft.py`

```python
"""Phase A Task 4 — 공개 카드에 새 사실을 결정적으로 붙인다."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.ingest import fact_cards
from app.ingest.card_plan import EntityGroup, PlanFact, PlanInvalid, append_facts


def _fact(rid, fid, *, predicate="물", qty=None, step=None, temp=None, polarity="AFFIRM"):
    return PlanFact(fact_revision_id=rid, fact_id=fid, entity_id=4, subject="음료Z",
                    predicate=predicate, variant_temperature=temp, variant_size=None,
                    quantity_value=Decimal(qty) if qty else None,
                    quantity_unit="ml" if qty else None,
                    value_text=None if qty else "가득", polarity=polarity, step_order=step,
                    conditions=(), exceptions=(), original_assertion=f"음료Z {predicate}",
                    assertion=f"음료Z {predicate}")


def test_append_facts_keeps_published_layout():
    a, b, c = _fact(10, 1, qty="225"), _fact(11, 2, predicate="얼음", step=1), _fact(12, 3, qty="30", predicate="시럽")
    group = EntityGroup(entity_id=4, canonical_name="음료Z", facts=(a, b, c))
    card = append_facts([("QUANTITIES", (10,)), ("STEPS", (11,))], group, [12], category_name="기타")
    assert [(blk.kind, blk.fact_revision_ids) for blk in card.blocks] == [
        ("QUANTITIES", (10, 12)), ("STEPS", (11,))]


def test_append_step_resorts_by_order():
    s2, s1 = _fact(20, 1, predicate="젓기", step=2), _fact(21, 2, predicate="붓기", step=1)
    group = EntityGroup(entity_id=4, canonical_name="음료Z", facts=(s1, s2))
    card = append_facts([("STEPS", (20,))], group, [21], category_name="기타")
    assert [blk.fact_revision_ids for blk in card.blocks] == [(21, 20)]


def test_append_new_kind_goes_to_new_block():
    q, note = _fact(10, 1, qty="225"), _fact(13, 4, predicate="주의", polarity="NEGATE")
    group = EntityGroup(entity_id=4, canonical_name="음료Z", facts=(q, note))
    card = append_facts([("QUANTITIES", (10,))], group, [13], category_name="기타")
    assert [(blk.kind, blk.fact_revision_ids) for blk in card.blocks] == [
        ("QUANTITIES", (10,)), ("NOTES", (13,))]


def test_append_rejects_fact_outside_group():
    group = EntityGroup(entity_id=4, canonical_name="음료Z", facts=(_fact(10, 1, qty="225"),))
    with pytest.raises(PlanInvalid):
        append_facts([("QUANTITIES", (10,))], group, [99], category_name="기타")


def _row(**over):
    row = dict(card_id=5, published_version_id=50, draft_version_id=50,
               assignment_type="AUTOMATIC", review_status="APPROVED", change_source="EXTRACTION",
               has_block_facts=True, in_merged=True)
    row.update(over)
    return row


@pytest.mark.parametrize("over, mode", [
    ({}, "REDRAFT"),
    ({"change_source": "OWNER_EDIT"}, "REDRAFT"),
    ({"draft_version_id": 51}, "DEFER"),          # 점주 초안이 따로 있다
    ({"assignment_type": "MANUAL"}, "DEFER"),     # 불변식 12
    ({"has_block_facts": False}, "DEFER"),
    ({"published_version_id": None, "draft_version_id": 51, "review_status": "PENDING"}, "REASSEMBLE"),
])
def test_classify_rows(over, mode):
    assert fact_cards._classify_rows(4, [_row(**over)]).mode == mode


def test_two_published_cards_defer():
    rows = [_row(), _row(card_id=6, published_version_id=60, draft_version_id=60)]
    assert fact_cards._classify_rows(4, rows).mode == "DEFER"


def test_no_rows_is_new():
    assert fact_cards._classify_rows(4, []).mode == "NEW"
```

- [ ] **Step 2: 실패 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests/test_wa_redraft.py` / Expected: ImportError(`append_facts`) 로 FAIL.
- [ ] **Step 3: `card_plan.append_facts` 구현**

```python
def _kind_of(f: PlanFact) -> str:
    """fallback_cards 와 같은 종류 규칙."""
    if f.step_order is not None:
        return "STEPS"
    if f.polarity == "AFFIRM" and f.quantity_value is not None:
        return "QUANTITIES"
    return "NOTES"


def append_facts(layout: Sequence[tuple[str, tuple[int, ...]]], group: EntityGroup,
                 new_ids: Sequence[int], *, category_name: str) -> ValidatedCard:
    """공개 판 배치를 그대로 두고 새 사실만 붙인다. 모델을 부르지 않는다(A-D4).

    새 사실은 같은 종류·같은 규격의 첫 블록 끝에 붙는다. STEPS 는 순서로 다시 줄 세운다.
    맞는 블록이 없으면 그 종류의 새 블록을 끝에 둔다. 검증은 validate_proposals 가 한다.
    """
    by_id = {f.fact_revision_id: f for f in group.facts}
    blocks: list[tuple[str, list[int]]] = [(kind, list(ids)) for kind, ids in layout]
    for rid in new_ids:
        f = by_id.get(rid)
        if f is None:
            raise PlanInvalid(PLAN_OUTSIDE_GROUP, f"new={rid}")
        kind = _kind_of(f)
        target = next((ids for k, ids in blocks
                       if k == kind and ids and by_id[ids[0]].variant == f.variant), None)
        if target is None:
            blocks.append((kind, [rid]))
            continue
        target.append(rid)
        if kind == "STEPS":
            target.sort(key=lambda r: (by_id[r].step_order, r))
    proposal = ProposedCard(category_name, tuple(ProposedBlock(k, tuple(ids)) for k, ids in blocks))
    (card,) = validate_proposals(group, [proposal])
    return card
```

  `validate_proposals` 가 카드를 여러 장으로 나누면(상한 초과) `PlanInvalid(DATA_TOO_LARGE)` 를 올린다: `cards = validate_proposals(...)`; `if len(cards) != 1: raise PlanInvalid(DATA_TOO_LARGE, "append")`.
- [ ] **Step 4: `fact_cards` 구현**
  - `_card_state` 의 select 에 `c.draft_version_id` 를 더하고, 판정은 순수 함수 `_classify_rows(entity_id: int, rows: Sequence[Mapping]) -> EntityCardState` 로 옮긴다(위 테스트 규칙: 행 없음 NEW → 전부 교체 가능 REASSEMBLE → 1장·위 REDRAFT 조건 → 나머지 DEFER `REASON_EXISTING_CARD`). REDRAFT 의 `card_ids` 는 그 1장, `reason=None`.
  - `new_fact_ids_for_source`:

```python
async def new_fact_ids_for_source(conn, store_id: int, *, source_id: int, entity_id: int,
                                  pinned_fact_ids: Sequence[int]) -> list[int]:
    rows = await conn.fetch(
        "select distinct r.fact_id from fact_occurrences o "
        "join fact_revisions r on r.store_id = o.store_id "
        "  and r.fact_revision_id = o.fact_revision_id "
        "join knowledge_facts k on k.store_id = r.store_id and k.fact_id = r.fact_id "
        "where o.store_id = $1 and o.source_id = $2 and o.disposition = 'REVIEW_PENDING' "
        "  and k.entity_id = $3 and not (r.fact_id = any($4::bigint[])) "
        "order by r.fact_id",
        store_id, source_id, entity_id, sorted({int(f) for f in pinned_fact_ids}))
    return [int(r["fact_id"]) for r in rows]
```

  - `redraft_published_card(conn, store_id, *, source_id, state)`:
    1. `locked = await _card_state(conn, store_id, state.entity_id, lock=True)`; `locked.mode != "REDRAFT" or locked.card_ids != state.card_ids` 이면 이 대상 사실을 `mark_pending(..., REASON_EXISTING_CARD)` 하고 `WrittenEntity(..., deferred_reason=REASON_EXISTING_CARD)`.
    2. `(card_id,) = state.card_ids`; 카드 행에서 `published_version_id` 를 읽어 `fact_edit_repo.load_card_fact_state(conn, store_id, card_id, published_version_id)`(함수 안에서 import — `app.cards` ↔ `app.ingest` 순환 import 를 피한다). `None` 이거나 `entity_problem` 이 있으면 보류(`REASON_EXISTING_CARD`).
    3. `pinned_fact_ids = {p.fact.fact_id for p in state_v.pinned}`; `new_fids = await new_fact_ids_for_source(...)`.
    4. 새 사실이 없으면: 이 자료의 occurrence 중 고정 사실을 가리키는 것을 그 카드·첫 블록으로 LINKED(`write_entity_cards` 의 처분 UPDATE 와 같은 문장, `o.source_id = $source_id` 조건 추가) → `WrittenEntity(card_ids=(card_id,), new_version_ids=(), linked_fact_ids=…)`.
    5. 있으면: `loaded = await fact_assembly.load_entity_groups(conn, store_id, [state.entity_id])` 에서 새 사실의 head 판(`PlanFact`)을 꺼낸다. 고정 판 `PlanFact` 는 `state_v.pinned`. `group = EntityGroup(entity_id, state_v.entity_name, facts=tuple(sorted(pinned + new, key=fact_sort_key)))`. `layout = [(kind, tuple(rids)) …]` 를 `state_v.blocks` 순서·`pinned` position 순서로 만든다. 카드 분류 이름은 `task_categories` 에서 카드 `category_id` 의 이름. `card = append_facts(layout, group, [new head rid…], category_name=…)`; `PlanInvalid` 면 `mark_pending(…, reason=e.code)` 후 보류 반환.
    6. 렌더링·근거·판 쓰기는 `write_entity_cards` 의 카드 한 장 경로와 같다: `provenance_for` → `render_card`·`render_missing` → `create_extraction_draft(conn, store_id, card_id, title=card.title, content=…, confidence=…, entity_id=card.entity_id)` → `pin_card_version` → `write_version_evidence` → `replace_legacy_facts`. 그 공통부(근거·자료 이름·신뢰도 계산과 렌더링)는 `write_entity_cards` 에서 `_render_one(conn, store_id, card, facts, provenance, …)` 같은 내부 함수로 뽑아 둘이 같이 쓴다(복붙 금지).
    7. `update knowledge_cards set needs_review_reason = 'NEW_FACTS' where store_id=$1 and card_id=$2` (review_status 는 건드리지 않는다 — 공개판은 승인 전까지 그대로).
    8. 붙인 사실과 고정 사실 중 이 자료 occurrence 를 LINKED(카드·블록) + `repo.set_assembly_state(…, "LINKED")`.
  - `pipeline._prepare_fact_assembly`: `[e for e in entity_ids if states[e].mode not in ("DEFER", "REDRAFT")]` 만 읽고 모델에 보낸다.
  - `pipeline._persist_fact_cards`: `now.mode == "DEFER"` 검사 다음에

```python
        if now.mode == "REDRAFT" or before.mode == "REDRAFT":
            if now.mode != before.mode:
                await pending(fact_cards.REASON_CONCURRENT)
                continue
            written = await fact_cards.redraft_published_card(
                conn, store_id, source_id=source_id, state=now)
            if written.deferred_reason is None:
                created += len(written.new_version_ids)
            continue
```

- [ ] **Step 5: 단위 통과 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests/test_wa_redraft.py tests` / Expected: 새 테스트 PASS, 전체 실패 0. 기존 `test_w3a_*` 중 "공개 카드 = DEFER" 를 검사하던 경우는 REDRAFT 기대로 바꾼다(바꾼 테스트 이름을 기록).
- [ ] **Step 6: 검증 도우미** — `api/scripts/_fact_card_fixture.py`

```python
"""실제 DB 검증용 사실 카드 도우미. 유료 호출 없음(INGEST_MODE=mock 조립, 합성 벡터)."""
from __future__ import annotations

from unittest.mock import patch

from app.ingest import pipeline
from app.ingest import repository as repo
from app.ingest.schemas import Evidence, ExtractedAssertion
from app.publish.approval import CardChange, publish_cards


def assertion(ref: str, subject: str, attribute: str, value: str, *, unit: str = "",
              source_id: int = 0) -> ExtractedAssertion:
    return ExtractedAssertion(local_ref=ref, original_assertion=f"{subject} {attribute} {value}{unit}",
                              subject=subject, attribute=attribute, value=value, unit=unit or None,
                              confidence=0.95, evidence=Evidence(source_id=source_id, timestamp_sec=0))


async def seed_fact_card(pool, *, store_id: int, owner_user_id: int,
                         assertions: list[ExtractedAssertion], title: str = "합성 자료") -> tuple[int, int]:
    async with pool.acquire() as conn:
        source_id = int(await conn.fetchval(
            "insert into sources (store_id, uploaded_by, source_type, title, file_url, content_hash, "
            "status, processed_at) values ($1, $2, 'OWNER_TEXT', $3, null, null, 'PROCESSING', now()) "
            "returning source_id", store_id, owner_user_id, title))
        async with conn.transaction():
            await pipeline._persist_ledger(conn, store_id, source_id, "OWNER_TEXT", assertions)
        categories = await repo.enabled_categories(conn, store_id)
    prepared = await pipeline._prepare_fact_assembly(
        pool, store_id, source_id, categories=list(categories), glossary=[], usage_sink=None,
        usage_base=None, raw_sink=None, strict=True)
    async with pool.acquire() as conn, conn.transaction():
        version = int(await conn.fetchval(
            "select category_version from stores where store_id = $1", store_id))
        await pipeline._persist_fact_cards(conn, store_id, source_id, categories, prepared,
                                           job_id=None, category_version=version)
        await repo.set_status(conn, store_id, source_id, "DONE")
        row = await conn.fetchrow(
            "select k.card_id, k.draft_version_id from fact_occurrences o "
            "join knowledge_cards k on k.store_id = o.store_id and k.card_id = o.card_id "
            "where o.store_id = $1 and o.source_id = $2 and o.disposition = 'LINKED' "
            "order by k.card_id limit 1", store_id, source_id)
    if row is None:
        raise RuntimeError("합성 사실 카드가 만들어지지 않았다")
    return int(row["card_id"]), int(row["draft_version_id"])


async def _vectors(texts, **kwargs):
    return [[1.0] + [0.0] * 1535 for _ in texts]


async def publish_card(pool, *, store_id: int, member_id: int, actor_user_id: int, card_id: int):
    async with pool.acquire() as conn:
        draft = int(await conn.fetchval(
            "select draft_version_id from knowledge_cards where store_id = $1 and card_id = $2",
            store_id, card_id))
    from app.contracts.usage import UsageContext
    context = UsageContext(store_id=str(store_id), stage="EMBED", cost_phase="OPERATING",
                           cost_purpose="PRODUCT", logical_call_id=f"fixture-publish:{card_id}:{draft}")
    with patch("app.reg.index_preparation.recorded_embeddings", _vectors):
        return await publish_cards(pool, store_id=store_id, member_id=member_id,
                                   actor_user_id=actor_user_id,
                                   changes=[CardChange(card_id, draft, draft)],
                                   idempotency_key=f"fixture:{card_id}:{draft}",
                                   usage_context=context)
```

  (`UsageContext` 필수 칸이 다르면 `api/app/contracts/usage.py` 를 읽고 맞춘다. 이 파일은 고치지 않는다.)
- [ ] **Step 7: 실제 DB 시나리오 (c)** — `api/scripts/verify_w_fact_only.py` 를 만든다. 구조는 `verify_w3a_fact_assembly.py` 처럼 `check(name, ok)` 로 PASS/FAIL 을 찍고 하나라도 FAIL 이면 예외. 진입점 `async def verify(pool, db)`.
  - 합성 매장(점주·멤버·'기타' 카테고리)을 만든다.
  - (c-1) `seed_fact_card(…, [assertion("f1","음료Z","물","225",unit="ml")])` → `publish_card` → `PUBLISHED`. 공개판 카드 판 = v1.
  - (c-2) 두 번째 자료: `seed_fact_card(…, [assertion("f1","음료Z","물","225",unit="ml"), assertion("f2","음료Z","시럽","30",unit="ml")])`. 확인: 같은 카드 id, `draft_version_id != published_version_id`, `needs_review_reason='NEW_FACTS'`, `review_status='APPROVED'`, 새 판 블록 사실 = 물·시럽, **공개판 snapshot 의 카드 판은 여전히 v1**.
  - (c-3) `publish_card` 로 승인 → 공개판 카드 판 = 새 판, `needs_review_reason is null`.
  - (c-4) 세 번째 자료가 같은 사실만 가져오면(물 225ml) 새 판이 없고 그 자료 occurrence 가 그 카드로 LINKED.
  - (c-5) 카드가 `assignment_type='MANUAL'` 이면 새 자료 사실은 `REVIEW_PENDING`·`EXISTING_CARD` 이고 새 판이 없다.
  - `verify_r_schema_rebuild.py` 의 `verify_checklist` 다음 줄에 가산: `from verify_w_fact_only import verify as verify_w_fact_only` / `await verify_w_fact_only(pool, fresh)`.
- [ ] **Step 8: 실제 DB 확인** — Global Constraints 의 docker 명령으로 재구축 검증을 돌린다. Expected: `verify_w_fact_only` (c) 전부 PASS. 다른 RAW 픽스처 구간의 빨강은 기록만(Task 7).
- [ ] **Step 9: web·격리** — `cd web && pnpm check`. 격리 검사. 변경 파일 목록 기록.

---

### Task 5: 점주 답변 → OWNER_TEXT 자료 → 사실 수집

**Files:**
- Create: `supabase/migrations/20261010090000_w_owner_answer_sources.sql`
- Create: `api/app/ingest/owner_text.py`
- Modify: `api/app/ingest/pipeline.py` (`_usage_context`: 작업 없는 실행 범위 `r{run_tag}:` 가산)
- Test: `api/tests/test_wa_owner_text.py` (새 파일)

**Interfaces:**
- Consumes: Task 1 (`_persist_ledger`·`_prepare_fact_assembly`·`_persist_fact_cards`), Task 4 (REDRAFT 는 `_persist_fact_cards` 안에서 자동).
- Produces (`app.ingest.owner_text`):
  - `QUESTION_HEADER: str`, `ANSWER_HEADER: str`, `compose_text(question: str, answer: str) -> str`
  - `drop_question_only(assertions: list[ExtractedAssertion], *, question: str, answer: str) -> list[ExtractedAssertion]`
  - `async ensure_owner_answer_source(conn, store_id: int, *, owner_answer_id: int, actor_id: int, question: str, answer: str) -> tuple[int, str]` — `(source_id, status)`. 멱등.
  - `async owner_answer_source(conn, store_id: int, *, owner_answer_id: int) -> int | None`
  - `async ingest_owner_text(pool, *, store_id: int, source_id: int, question: str, answer: str, run_tag: int) -> int` — 이 자료에서 원장에 남은 사실 수(필터 뒤). 추출·조립 모델 호출 중 연결을 쥐지 않는다. 끝에 자료 `DONE`.
  - `@dataclass(frozen=True) class AnswerCard: card_id: int; draft_version_id: int; published_version_id: int | None; review_status: str; needs_review_reason: str | None`
  - `async answer_cards(conn, store_id: int, *, source_id: int) -> list[AnswerCard]` — 이 자료 occurrence 가 LINKED 로 이어진, 제외되지 않은 카드(card_id 순).
  - `async answer_fact_count(conn, store_id: int, *, source_id: int) -> int` — `source_fact_occurrences` 행 수.
- Produces (`pipeline`): `_usage_context(...)` 는 `job_id is None and extraction_run_id is None and run_tag` 이면 scope `r{run_tag}:`.

- [ ] **Step 1: migration 쓰기** — `supabase/migrations/20261010090000_w_owner_answer_sources.sql`

```sql
-- Phase A — 점주 답변을 사실로 바꾸기 위한 파일 없는 자료(OWNER_TEXT) 연결.
-- 답변 하나에 자료 하나. 근거는 그 자료의 occurrence(source_id + occurrence_id)로 공개된다.
-- 가산 변경만 한다.
create table if not exists owner_answer_sources (
  store_id bigint not null references stores(store_id),
  owner_answer_id bigint not null references owner_answers(answer_id) on delete restrict,
  source_id bigint not null references sources(source_id) on delete restrict,
  created_at timestamptz not null default now(),
  primary key (store_id, owner_answer_id),
  unique (source_id)
);

create or replace function askbuddy_owner_answer_source_store_check()
returns trigger language plpgsql as $$
begin
  -- 답변·자료가 모두 이 매장 것이어야 한다(D1). owner_answers 는 store_id 가 없어 질문을 거친다
  if not exists (select 1 from owner_answers oa join pending_questions pq on pq.question_id = oa.question_id
                 where oa.answer_id = new.owner_answer_id and pq.store_id = new.store_id)
     or not exists (select 1 from sources s where s.source_id = new.source_id
                    and s.store_id = new.store_id and s.source_type = 'OWNER_TEXT') then
    raise exception '점주 답변 자료 연결의 매장이 맞지 않는다 (store=%, answer=%, source=%)',
      new.store_id, new.owner_answer_id, new.source_id;
  end if;
  return new;
end $$;

drop trigger if exists trg_owner_answer_source_store_check on owner_answer_sources;
create trigger trg_owner_answer_source_store_check
before insert or update on owner_answer_sources
for each row execute function askbuddy_owner_answer_source_store_check();

comment on table owner_answer_sources is '점주 답변 → 사실 수집용 OWNER_TEXT 자료 (Phase A)';
```

- [ ] **Step 2: 실패하는 테스트 쓰기** — `api/tests/test_wa_owner_text.py`

```python
"""Phase A Task 5 — 점주 답변 글을 사실 수집 입력으로 만든다."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import owner_text, pipeline
from app.ingest.schemas import Evidence, ExtractedAssertion


def _a(ref, original):
    return ExtractedAssertion(local_ref=ref, original_assertion=original, subject="음료Z",
                              attribute="물", value="225", confidence=0.9,
                              evidence=Evidence(source_id=1, timestamp_sec=0))


def test_compose_text_marks_question_as_context():
    text = owner_text.compose_text(" 음료Z 물 얼마나? ", " 225ml 넣어요 ")
    assert text.startswith(owner_text.QUESTION_HEADER)
    assert "음료Z 물 얼마나?" in text and "225ml 넣어요" in text
    assert text.index(owner_text.QUESTION_HEADER) < text.index(owner_text.ANSWER_HEADER)


def test_drop_question_only_keeps_answer_facts():
    q, ans = "음료Z 물은 몇 ml 넣나요?", "음료Z 물은 225ml 넣어요"
    kept = owner_text.drop_question_only(
        [_a("f1", "음료Z 물은 몇 ml 넣나요"), _a("f2", "음료Z 물은 225ml 넣어요"), _a("f3", "")],
        question=q, answer=ans)
    assert [x.local_ref for x in kept] == ["f2", "f3"]


def test_usage_scope_without_job_uses_run_tag():
    ctx = pipeline._usage_context(7, 11, None, "EXTRACT", "OPERATING", "PRODUCT", None, run_tag=99)
    assert ctx.logical_call_id == "r99:src11:extract"
    ctx = pipeline._usage_context(7, 11, 5, "EXTRACT", "REGISTRATION", "PRODUCT", None, run_tag=99)
    assert ctx.logical_call_id == "job5r99:src11:extract"


class _Pool:
    """acquire() 가 같은 가짜 연결을 돌려준다."""

    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


class _Conn:
    def __init__(self, ledger_exists):
        self.ledger_exists = ledger_exists
        self.executed = []

    async def fetchval(self, query, *args):
        if "from source_facts" in query:
            return self.ledger_exists
        if "category_version" in query:
            return 1
        if "count(*)" in query:
            return 2
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.executed.append(query)

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False
        return _Tx()


@pytest.mark.asyncio
async def test_resume_skips_extraction_when_ledger_exists():
    conn = _Conn(ledger_exists=True)
    extract = AsyncMock()
    with patch("app.ingest.extract.extract_facts", extract), \
            patch.object(owner_text.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})), \
            patch.object(owner_text.repo, "glossary", AsyncMock(return_value=[])), \
            patch.object(owner_text.repo, "set_status", AsyncMock()), \
            patch.object(owner_text.pipeline, "_prepare_fact_assembly", AsyncMock()), \
            patch.object(owner_text.pipeline, "_persist_fact_cards", AsyncMock(return_value=0)):
        await owner_text.ingest_owner_text(_Pool(conn), store_id=7, source_id=11,
                                           question="질문", answer="답", run_tag=1)
    extract.assert_not_awaited()
```

  (가짜 연결이 받지 않는 조회로 `AssertionError` 가 나면 그 조회에 맞는 분기를 더한다 — 구현이 실제로 치는 조회만큼만.)
- [ ] **Step 3: 실패 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests/test_wa_owner_text.py` / Expected: ImportError(`owner_text`).
- [ ] **Step 4: 구현** — `api/app/ingest/owner_text.py`

```python
"""점주 답변 → 파일 없는 자료(OWNER_TEXT) → 사실 수집 (Phase A, A-D3).

업로드와 같은 길을 탄다: 추출 → 원장(_persist_ledger) → 대상 연결 → 사실 조립 → 사실 카드.
질문 문장은 답변을 이해하기 위한 맥락일 뿐 사실로 저장하지 않는다. 추출 프롬프트 파일은
바꾸지 않고(재사용 키 보존) 입력 글 머리말로 알린다. 질문에만 나온 원문은 서버가 버린다.

모든 DB 함수는 store_id 를 필수로 받고 모든 조회가 store_id 로 좁힌다(D1).
모델 호출 중에는 DB 연결을 쥐지 않는다.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from app.ingest import pipeline
from app.ingest import repository as repo
from app.ingest.schemas import ExtractedAssertion

logger = logging.getLogger(__name__)

QUESTION_HEADER = "[직원 질문 — 답변을 이해하기 위한 맥락이다. 여기서는 사실을 뽑지 않는다]"
ANSWER_HEADER = "[점주 답변 — 사실은 여기서만 뽑는다]"
SOURCE_TITLE = "점주 답변 · {question}"
_TITLE_QUESTION_MAX = 80


def compose_text(question: str, answer: str) -> str:
    return f"{QUESTION_HEADER}\n{question.strip()}\n\n{ANSWER_HEADER}\n{answer.strip()}"


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def drop_question_only(assertions: list[ExtractedAssertion], *, question: str,
                       answer: str) -> list[ExtractedAssertion]:
    """원문이 답변에는 없고 질문에만 있는 사실을 버린다. 원문이 비면 판단하지 않고 남긴다."""
    q, a = _norm(question), _norm(answer)
    kept = []
    for x in assertions:
        original = _norm(x.original_assertion)
        if original and original not in a and original in q:
            logger.info("점주 답변 — 질문에만 있는 원문을 버린다 ref=%s", x.local_ref)
            continue
        kept.append(x)
    return kept
```

  이어서 같은 파일에:
  - `ensure_owner_answer_source`: 매장 지식 잠금 없이 `owner_answer_sources` 를 `store_id`·`owner_answer_id` 로 찾고 있으면 `(source_id, status)`. 없으면 `insert into sources (store_id, uploaded_by, source_type, title, file_url, content_hash, status) values ($1,$2,'OWNER_TEXT',$3,null,$4,'PROCESSING')`(title = `SOURCE_TITLE.format(question=question.strip()[:80])`[:200], content_hash = `hashlib.sha256(answer.encode()).hexdigest()`) → `insert into owner_answer_sources …`. 동시 실행 대비로 `on conflict (store_id, owner_answer_id) do nothing` 뒤 다시 읽는다(진 쪽이 만든 자료 행은 같은 트랜잭션이라 롤백되도록 호출자가 트랜잭션 안에서 부른다).
  - `owner_answer_source`: `select source_id from owner_answer_sources where store_id=$1 and owner_answer_id=$2`.
  - `ingest_owner_text(pool, *, store_id, source_id, question, answer, run_tag)`:
    1. 짧은 연결: `has_ledger = await conn.fetchval("select exists (select 1 from source_facts where store_id=$1 and source_id=$2)", …)`; `glossary = await repo.glossary(conn, store_id)`.
    2. `usage_base = (store_id, None, "OPERATING", "PRODUCT", None, run_tag)`.
    3. `has_ledger` 가 아니면(연결 없이) `from app.ingest.extract import extract_facts`; `result = await extract_facts(source_id=source_id, source_type="OWNER_TEXT", text=compose_text(question, answer), glossary=glossary, media=[], usage_sink=DbUsageSink(pool, resilient=True), usage_context=pipeline._ctx_for(usage_base, source_id, "EXTRACT"), raw_sink=DbRawResponseSink(pool, run_tag=run_tag))`; `assertions = drop_question_only(list(result.assertions), question=…, answer=…)`; 사실 local_ref 앞에 `seg1:` 을 붙이지 않는다(구간 없음). 그 뒤 트랜잭션에서 `await pipeline._persist_ledger(conn, store_id, source_id, "OWNER_TEXT", assertions)`.
    4. 짧은 연결로 `categories = await repo.enabled_categories(conn, store_id)` → 연결 없이 `prepared = await pipeline._prepare_fact_assembly(pool, store_id, source_id, categories=list(categories), glossary=glossary, usage_sink=…, usage_base=usage_base, raw_sink=…, strict=True)`.
    5. 트랜잭션: `category_version` 읽기 → `await pipeline._persist_fact_cards(conn, store_id, source_id, categories, prepared, job_id=None, category_version=…)` → `await repo.set_status(conn, store_id, source_id, "DONE")`.
    6. `return await answer_fact_count(conn, store_id, source_id=source_id)`.
  - `answer_cards`:

```python
async def answer_cards(conn, store_id: int, *, source_id: int) -> list[AnswerCard]:
    rows = await conn.fetch(
        "select distinct k.card_id, k.draft_version_id, k.published_version_id, "
        "       k.review_status, k.needs_review_reason "
        "from fact_occurrences o "
        "join knowledge_cards k on k.store_id = o.store_id and k.card_id = o.card_id "
        "where o.store_id = $1 and o.source_id = $2 and o.disposition = 'LINKED' "
        "  and k.review_status <> 'EXCLUDED' and k.draft_version_id is not null "
        "order by k.card_id", store_id, source_id)
    return [AnswerCard(card_id=int(r["card_id"]), draft_version_id=int(r["draft_version_id"]),
                       published_version_id=(int(r["published_version_id"])
                                             if r["published_version_id"] is not None else None),
                       review_status=r["review_status"],
                       needs_review_reason=r["needs_review_reason"]) for r in rows]
```

  - `answer_fact_count`: `select count(*) from source_fact_occurrences where store_id=$1 and source_id=$2`.
  - `pipeline._usage_context`: `scope = (f"run{extraction_run_id}:" if extraction_run_id else job_scope if job_id else f"r{run_tag}:" if run_tag else "")`. 주석: "작업 없는 운영 수집(점주 답변)은 실행 표지로 재시도를 가른다".
- [ ] **Step 5: 통과 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests/test_wa_owner_text.py tests` / Expected: PASS, 실패 0.
- [ ] **Step 6: 격리 검사**(`api/app/ingest`)·**변경 파일 목록 기록.**

---

### Task 6: 점주 답변 worker 교체 · `approve_owner_proposal` 안쪽 교체 · v1 거절

**Files:**
- Modify: `api/app/cards/owner_answer_worker.py` (`build_knowledge_plan`·`create_owner_answer_card` import 와 `_record_plan`·`_insert_proposal(plan=…)` 삭제 → 사실 수집 흐름)
- Modify: `api/app/learn/knowledge_apply.py` (`approve_owner_proposal` 안쪽 교체; 삭제: `_stage_proposal_card`·`_is_staged_draft`·`_mark_owner_answer_version`·`_read_version`·`_owner_answer_draft`·`_lock_target_card`. **남김**(Task 13 에서 지움): `prepare_proposal`·`publish_new_proposal`·`publish_existing_proposal`·`create_owner_answer_card`·`resolve_owner_answer_category`)
- Modify: `api/app/cards/repository.py` (`create_draft` 삭제 — `publish_existing_proposal` 이 쓰지 않는지 확인: 쓰지 않는다, 직접 insert 한다)
- Modify (R 소유 예외 P-3): `api/scripts/verify_r_legacy_publication.py` (v1 NEW 기대 `PUBLISHED` → `FAILED`, 이후 제외·복원 단계는 `_fact_card_fixture.seed_fact_card`+`publish_card` 로 만든 공개 카드로)
- Modify: `api/scripts/verify_w_publication_flow.py` §9 (worker 시나리오를 사실 경로로)
- Modify: `api/scripts/verify_w_fact_only.py` (시나리오 (b))
- Rewrite tests: `tests/test_w_owner_answer_worker.py`, `tests/test_w_owner_proposal_approval.py`
- Test: `api/tests/test_wa_owner_outcome.py` (새 파일)

**Interfaces:**
- Consumes: Task 5 (`ensure_owner_answer_source`, `owner_answer_source`, `ingest_owner_text`, `answer_cards`, `answer_fact_count`, `AnswerCard`), Task 4 (`REVIEW_NEW_FACTS`).
- Produces:
  - `owner_answer_worker.decide_outcome(fact_count: int, cards: Sequence[AnswerCard]) -> AnswerOutcome` (순수). `@dataclass(frozen=True) class AnswerOutcome: kind: str  # "NO_FACTS"|"FACTS_PENDING"|"REVIEW"|"PUBLISH"|"LINKED"; relation: str  # "NEW"|"SUPPLEMENT"|"IDENTICAL"; cards: tuple[AnswerCard, ...]; target: AnswerCard | None`.
  - `knowledge_apply.LEGACY_PROPOSAL_MESSAGE = "예전 방식 제안이라 카드로 만들 수 없어요. 카드 화면에서 직접 고쳐 주세요."`, `knowledge_apply.NO_DRAFT_MESSAGE = "이 답변에서 카드에 넣을 내용을 찾지 못했어요. 제안을 닫아 주세요."`
  - `approve_owner_proposal` 시그니처 불변. 이 답변 자료가 없으면 `ValueError(LEGACY_PROPOSAL_MESSAGE)`, 공개할 초안 카드가 없으면 `ValueError(NO_DRAFT_MESSAGE)`. 있으면 그 카드들 전부를 `publish_cards` 한 번으로.

규칙(설계 A-D3 를 카드 단위로 풀어 쓴 것):

| 상황 | kind | 제안 relation / status | R 보고 |
|---|---|---|---|
| 사실 0개 | NO_FACTS | NEW / PENDING_REVIEW, reason `NO_FACTS`, 제목=질문·본문=답변 | REVIEW |
| 사실은 있으나 이어진 카드 0 (보류) | FACTS_PENDING | NEW / PENDING_REVIEW, reason `FACTS_PENDING` | REVIEW |
| 공개 카드에 새 초안이 생겼거나, 새 카드가 검수 필요(NEEDS_REVIEW·사유 있음) | REVIEW | 공개 카드 변경이 있으면 SUPPLEMENT(target=첫 공개 카드·published 판) 아니면 NEW / PENDING_REVIEW. 대상 카드에 `needs_review_reason='OWNER_ANSWER_<relation>'` | REVIEW |
| 새 카드만 있고 모두 PENDING·사유 없음 | PUBLISH | NEW / ANALYZED → 공개 hook 에서 PUBLISHED | PUBLISHED (card=첫 새 카드) |
| 공개 카드에만 이어지고 바뀐 판 없음 | LINKED | IDENTICAL / LINKED (`_linked_target` 이 확인되면) | LINKED, 아니면 REVIEW |

- [ ] **Step 1: 실패하는 테스트 쓰기** — `api/tests/test_wa_owner_outcome.py`

```python
"""Phase A Task 6 — 점주 답변 결과 판정(순수)."""
from __future__ import annotations

from app.cards.owner_answer_worker import decide_outcome
from app.ingest.owner_text import AnswerCard


def card(cid, *, draft, published=None, status="PENDING", reason=None):
    return AnswerCard(card_id=cid, draft_version_id=draft, published_version_id=published,
                      review_status=status, needs_review_reason=reason)


def test_no_facts_reports_review_without_card():
    out = decide_outcome(0, [])
    assert (out.kind, out.relation, out.cards, out.target) == ("NO_FACTS", "NEW", (), None)


def test_facts_without_cards_is_pending():
    assert decide_outcome(2, []).kind == "FACTS_PENDING"


def test_new_cards_publish():
    out = decide_outcome(2, [card(5, draft=50), card(6, draft=60)])
    assert (out.kind, out.relation) == ("PUBLISH", "NEW")
    assert [c.card_id for c in out.cards] == [5, 6]


def test_new_card_needing_review_blocks_publish():
    out = decide_outcome(1, [card(5, draft=50, status="NEEDS_REVIEW", reason="NO_PROVENANCE")])
    assert (out.kind, out.relation) == ("REVIEW", "NEW")


def test_published_card_with_new_draft_is_supplement():
    changed = card(7, draft=71, published=70, status="APPROVED", reason="NEW_FACTS")
    out = decide_outcome(2, [changed, card(8, draft=80)])
    assert (out.kind, out.relation) == ("REVIEW", "SUPPLEMENT")
    assert out.target == changed
    assert [c.card_id for c in out.cards] == [7, 8]


def test_identical_facts_link():
    linked = card(9, draft=90, published=90, status="APPROVED")
    out = decide_outcome(1, [linked])
    assert (out.kind, out.relation, out.target) == ("LINKED", "IDENTICAL", linked)


def test_linked_and_new_publishes_new_only():
    out = decide_outcome(2, [card(9, draft=90, published=90, status="APPROVED"), card(10, draft=100)])
    assert out.kind == "PUBLISH"
    assert [c.card_id for c in out.cards] == [10]
```

  그리고 `tests/test_w_owner_proposal_approval.py` 를 다시 쓴다(가짜 pool/conn 은 지금 파일의 방식을 따른다). 최소 테스트:

```python
async def test_legacy_proposal_without_source_raises():
    # owner_answer_source 가 None → ValueError(LEGACY_PROPOSAL_MESSAGE), publish_cards 를 부르지 않는다

async def test_approve_without_drafts_raises():
    # 자료는 있으나 answer_cards 가 모두 draft == published → ValueError(NO_DRAFT_MESSAGE)

async def test_approve_publishes_all_answer_drafts_once():
    # answer_cards = [새 카드 5(초안 50), 공개 카드 7(초안 71·공개 70), 공개 카드 9(90=90)]
    # publish_cards 한 번, changes == [CardChange(5,50,50), CardChange(7,71,71)],
    # idempotency_key == "owner-proposal:<id>", hook 이 _finish_proposal(card_id=5, version_id=50)

async def test_already_published_proposal_is_already_applied():
    # 기존 테스트 유지
```

  (각 함수 본문은 기존 파일의 가짜 연결·`patch(f"{MOD}.publish_cards", …)` 방식으로 채운다. `MOD = "app.learn.knowledge_apply"`. `owner_answer_source`·`answer_cards` 는 `knowledge_apply` 모듈 이름공간에서 patch 한다.)
- [ ] **Step 2: 실패 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests/test_wa_owner_outcome.py tests/test_w_owner_proposal_approval.py` / Expected: ImportError(`decide_outcome`) 등 FAIL.
- [ ] **Step 3: `decide_outcome` 구현** (`owner_answer_worker.py`)

```python
@dataclass(frozen=True)
class AnswerOutcome:
    kind: str  # NO_FACTS | FACTS_PENDING | REVIEW | PUBLISH | LINKED
    relation: str  # NEW | SUPPLEMENT | IDENTICAL (knowledge_change_proposals.relation_type)
    cards: tuple[AnswerCard, ...]
    target: AnswerCard | None


def decide_outcome(fact_count: int, cards: Sequence[AnswerCard]) -> AnswerOutcome:
    """점주 답변 자료가 이어진 카드로 결과를 정한다. 표는 계획 Task 6 참조."""
    if fact_count == 0:
        return AnswerOutcome("NO_FACTS", "NEW", (), None)
    if not cards:
        return AnswerOutcome("FACTS_PENDING", "NEW", (), None)
    new = [c for c in cards if c.published_version_id is None]
    changed = [c for c in cards if c.published_version_id is not None
               and c.draft_version_id != c.published_version_id]
    linked = [c for c in cards if c.published_version_id is not None
              and c.draft_version_id == c.published_version_id]
    blocked = [c for c in new if c.review_status != "PENDING" or c.needs_review_reason]
    if changed or blocked:
        return AnswerOutcome("REVIEW", "SUPPLEMENT" if changed else "NEW",
                             tuple(changed + new), changed[0] if changed else None)
    if new:
        return AnswerOutcome("PUBLISH", "NEW", tuple(new), None)
    return AnswerOutcome("LINKED", "IDENTICAL", tuple(linked), linked[0])
```

- [ ] **Step 4: worker 흐름 교체** — `_apply` 를 아래 순서로 바꾼다(lease·실패 보고·`_finish_recorded`·`_linked_target`·`_finish`·`_finish_failed`·`_index_ready`·`run_owner_answer_worker`·`process_next_owner_event` 는 그대로).
  1. `context` 를 읽고 기존처럼 `proposal is not None and status != 'ANALYZED'` 면 `_finish_recorded`.
  2. `proposal is None` 이면: heartbeat → 트랜잭션에서 `source_id, status = await owner_text.ensure_owner_answer_source(conn, store_id, owner_answer_id=answer_id, actor_id=int(owner["user_id"]), question=source["question_text"], answer=source["answer_text"])`.
  3. `status != "DONE"` 이면 heartbeat → `await owner_text.ingest_owner_text(pool, store_id=store_id, source_id=source_id, question=…, answer=…, run_tag=int(time.time() * 1000))` → heartbeat.
  4. 트랜잭션에서 `cards = await owner_text.answer_cards(conn, …)`, `count = await owner_text.answer_fact_count(conn, …)`, `outcome = decide_outcome(count, cards)` → `_record_outcome(conn, …, outcome, question, answer)`:
     - 제안 행: `_insert_proposal(conn, store_id=…, answer_id=…, relation=outcome.relation, target_card_id=…, target_version_id=…, category_id=…, title=…, content=…, reason=…, status=…)` 로 인자를 명시적으로 받게 바꾼다(`plan` 인자 삭제). 제목·본문은 첫 카드의 **초안 판** `card_versions.title/content`, 카드가 없으면 질문[:200]/답변. `category_id` 는 첫 카드의 `category_id`, 없으면 `resolve_owner_answer_category(conn, store_id=…, category_id=None)`(시스템 '기타'). reason: NO_FACTS → `"NO_FACTS"`, FACTS_PENDING → `"FACTS_PENDING"`, 그 밖 → `f"OWNER_ANSWER_{kind}"`.
     - LINKED: `_linked_target(conn, store_id, card_id=outcome.target.card_id)` 이 있으면 status LINKED·`owner_answers.card_id` 갱신·`_finish(…"LINKED")`. 없으면 PENDING_REVIEW·REVIEW.
     - REVIEW/NO_FACTS/FACTS_PENDING: status PENDING_REVIEW, 대상 카드마다 `_flag_target_review(conn, store_id=…, card_id=c.card_id, relation=outcome.relation)`, `_finish(…"REVIEW")`.
     - PUBLISH: status ANALYZED, 보고하지 않고 `(None, proposal, outcome.cards)` 를 돌려준다.
  5. PUBLISH 면 `_publish_new(pool, …, cards=outcome.cards)`: `changes=[CardChange(c.card_id, c.draft_version_id, c.draft_version_id) for c in cards]`, hook 에서 `_set_proposal(…PUBLISHED, result_card_id=cards[0].card_id, result_version_id=cards[0].draft_version_id)` + `update owner_answers set card_id = $3 where answer_id = $2 and question_id in (select question_id from pending_questions where store_id = $1)` + `_finish(…"PUBLISHED", card_id=cards[0].card_id, …)`. 재시도로 `proposal.status == 'ANALYZED'` 인 채 들어오면 `answer_cards` 를 다시 읽어 같은 판정으로 이어간다(`card` 인자·`_owner_answer_card` 삭제). `NO_PROVENANCE` 결과 분기 주석을 "근거 없는 사실 카드(드문 경우)" 로 바꾼다.
  모듈 docstring 을 새 흐름으로 고친다("관계 분석(R knowledge_loop)을 부르지 않는다 — 점주 답변도 사실 수집 경로를 탄다").
- [ ] **Step 5: `approve_owner_proposal` 교체** (`knowledge_apply.py`)

```python
LEGACY_PROPOSAL_MESSAGE = "예전 방식 제안이라 카드로 만들 수 없어요. 카드 화면에서 직접 고쳐 주세요."
NO_DRAFT_MESSAGE = "이 답변에서 카드에 넣을 내용을 찾지 못했어요. 제안을 닫아 주세요."


async def approve_owner_proposal(pool, *, store_id, member_id, actor_user_id, proposal_id,
                                 usage_context, notify_r=None) -> PublishCardsResult:
    """점주 답변 제안을 승인한다 = 그 답변 자료가 만든 사실 카드 초안을 모두 공개한다.

    사실 초안이 없는 제안(v1 관계 분석 제안·사실 0개)은 ValueError — R 라우트가 409 로 바꾼다.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _lock_publication(conn, store_id)
            proposal = await _lock_proposal(conn, store_id=store_id, proposal_id=proposal_id)
            if proposal is None:
                raise LookupError("knowledge proposal not found")
            if (proposal["status"] == "PUBLISHED" and proposal["result_card_id"] is not None
                    and proposal["result_version_id"] is not None):
                return PublishCardsResult(status="ALREADY_APPLIED")
            if proposal["status"] not in APPROVABLE_PROPOSAL_STATUSES:
                raise ValueError("승인할 수 없는 상태의 제안입니다")
            source_id = await owner_answer_source(conn, store_id,
                                                  owner_answer_id=int(proposal["answer_id"]))
            if source_id is None:
                raise ValueError(LEGACY_PROPOSAL_MESSAGE)
            drafts = [c for c in await answer_cards(conn, store_id, source_id=source_id)
                      if c.published_version_id is None
                      or c.draft_version_id != c.published_version_id]
            if not drafts:
                raise ValueError(NO_DRAFT_MESSAGE)
    first = drafts[0]

    async def hook(conn, snapshot_id: int, knowledge_revision: int) -> None:
        current = await _lock_proposal(conn, store_id=store_id, proposal_id=proposal_id)
        if current is None or current["status"] not in APPROVABLE_PROPOSAL_STATUSES:
            raise ValueError("knowledge proposal changed during publication")
        await _finish_proposal(conn, store_id=store_id, proposal=current,
                               card_id=first.card_id, version_id=first.draft_version_id)
        if notify_r is None:
            logger.warning("R 완료 접점 미연결 — 인계 문서 참조 store=%s proposal=%s answer=%s",
                           store_id, proposal_id, current["answer_id"])
            return
        await notify_r(conn, int(current["answer_id"]), first.card_id, first.draft_version_id,
                       knowledge_revision)

    return await publish_cards(
        pool, store_id=store_id, member_id=member_id, actor_user_id=actor_user_id,
        changes=[CardChange(c.card_id, c.draft_version_id, c.draft_version_id) for c in drafts],
        idempotency_key=f"owner-proposal:{proposal_id}", usage_context=usage_context,
        in_transaction=hook)
```

  `_finish_proposal` 의 SUPPLEMENT/CONFLICT 사유 다시 표시는 `result card` 만이 아니라 `drafts` 의 공개 카드에도 필요하면 같은 SQL 을 카드마다 돈다(hook 안). import: `from app.ingest.owner_text import answer_cards, owner_answer_source`. 지운 함수가 쓰던 `card_repo` import 가 남는 곳이 없으면 지운다. `cards/repository.create_draft` 를 지운다(`grep -rn "create_draft" api/app api/scripts api/tests` 로 남은 호출이 없는지 확인 — `create_extraction_draft`·`create_owner_edit_version` 은 다른 함수다).
- [ ] **Step 6: worker 테스트 다시 쓰기** — `tests/test_w_owner_answer_worker.py` 의 `build_knowledge_plan`·`create_owner_answer_card` patch 를 `owner_text.ensure_owner_answer_source`·`ingest_owner_text`·`answer_cards`·`answer_fact_count` patch 로 바꾼다. 남길 검사: lease 상실 시 보고 없음, 결론 난 제안 재보고(`_finish_recorded`), 실패 코드 매핑(`_error_code`), NEW 공개 hook 안 보고, `ALREADY_APPLIED`·`STALE`·`INVALID_CONTENT` 처리, `_index_ready`. 새 검사: 자료 `DONE` 이면 `ingest_owner_text` 를 부르지 않는다, PUBLISH 는 카드 전부를 한 번에 공개한다.
- [ ] **Step 7: 통과 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests` / Expected: 실패 0 (`test_r_owner_review.py`·`test_r_w3_consumption.py` 포함 — R 테스트가 깨지면 멈추고 보고한다).
- [ ] **Step 8: 실제 DB 시나리오 (b) 와 검증 스크립트**
  - `verify_w_fact_only.py` (b): 합성 매장에서 v2 대기 질문을 넣고 R `app.learn.owner_delivery.submit_owner_answer(pool, store_id=…, member_id=…, question_id=…, request_id="wa-b", answer="음료Z 물은 225ml 넣어요", expected_revision=0)` → `app.ingest.extract.extract_facts` 를 `ExtractedAssertion(original_assertion="음료Z 물은 225ml 넣어요", subject="음료Z", attribute="물", value="225", unit="ml", …)` 하나를 돌려주는 대역으로 patch, 합성 벡터 patch(`app.reg.index_preparation.recorded_embeddings`) → `process_next_owner_event(pool, store_id=…)` == `"PUBLISHED"`. 확인: `owner_answer_sources` 1행·OWNER_TEXT 자료 `DONE`, 공개판에 사실 블록 카드, 사실 판 근거가 그 자료 occurrence(`source_id`=OWNER_TEXT 자료), R `r_owner_knowledge_states.status='PUBLISHED'`. 이어서 R 답변이 그 사실을 인용: `verify_w3a_fact_assembly.py:1656-1680` 과 같은 `hybrid_search` → `decide` → `save_answer` 로 `response.action == "ANSWER"`, 인용 `fact_revision_id`·`source_id` 가 공개판과 같다.
  - (b-2) 같은 대상에 두 번째 답변("음료Z 시럽은 30ml") → `"REVIEW"`, 제안 SUPPLEMENT·PENDING_REVIEW, 카드 새 초안, 공개판 그대로. R 라우트 대신 `approve_owner_proposal(…, notify_r=None)` 로 승인 → PUBLISHED, 공개판 카드 판 = 새 초안.
  - (b-3) 사실 0개(대역이 빈 목록) → `"REVIEW"`, 제안 reason `NO_FACTS`, 카드 수 불변, `approve_owner_proposal` 이 `ValueError(NO_DRAFT_MESSAGE)`.
  - `verify_w_publication_flow.py` §9: `fake_plan`·`plans`·`owner_answer_publish` 를 지우고 위 (b) 와 같은 extract 대역으로 IDENTICAL(이미 공개된 같은 사실 → LINKED)·NEW(→PUBLISHED)·SUPPLEMENT(→REVIEW 후 승인) 를 확인하도록 다시 쓴다. §9 이외 구간의 RAW 픽스처는 Task 7 이 고친다.
  - `verify_r_legacy_publication.py`(P-3 예외): 첫 v1 답변의 기대를 `result['knowledge']['status'] == 'FAILED'`·공개판 변화 없음으로 바꾸고 PASS 문구를 `'PASS legacy v1 NEW without fact draft fails closed (Phase A)'` 로. 그 뒤 제외·복원 단계에 필요한 공개 카드는 `seed_fact_card` + `publish_card` 로 만든다. `w_owner_answer_raw_publish` patch 줄을 지운다.
  - 재구축 검증을 돌려 (b)·§9·legacy_publication 이 PASS 인지 기록(다른 RAW 픽스처 빨강은 Task 7).
- [ ] **Step 9: 격리 검사**(`api/app/cards api/app/learn/knowledge_apply.py api/app/ingest`)·**변경 파일 목록 기록.**

---

### Task 7: 판 생성 트리거 제거 · 판 1 명시 생성 · 검증 픽스처 정리

**Files:**
- Create: `supabase/migrations/20261010120000_w_drop_legacy_card_version_trigger.sql`
- Modify: `api/app/ingest/repository.py` `insert_card` (판 1 명시 생성)
- Modify: `api/app/learn/knowledge_apply.py` `create_owner_answer_card` (Task 13 까지 살아 있으므로 판 1 명시 생성)
- Modify (R 소유 예외 P-3): `api/scripts/verify_r_w3_consumer.py:63-64`, `api/scripts/verify_r_owner_candidates.py:36-49`
- Modify (W): `api/scripts/verify_w_publication_flow.py`(§9 밖 RAW 카드 픽스처), `verify_checklist.py`, 그리고 `grep -rln "insert into knowledge_cards" api/scripts` 결과 중 판 포인터를 읽거나 공개하는 W 스크립트(`verify_cp04.py`·`verify_p7_integration.py`·`verify_w_embedding_service.py`·`verify_w_entity_revision.py`·`verify_w3a_fact_assembly.py`·`verify_w3b_card_fact_edit.py`·`verify_w_raw_responses.py`)
- Modify: `api/scripts/verify_w_fact_only.py` (시나리오 (d))
- Test: `api/tests/test_wa_insert_card.py` (새 파일)

**Interfaces:**
- Consumes: Task 4 `seed_fact_card`·`publish_card`.
- Produces: `repo.insert_card(conn, store_id, *, category_id, source_id, title, content, confidence, origin_job_id=None, category_version=1, entity_id=None) -> int` 시그니처 불변, 카드 행과 `card_versions` 판 1(`change_source='EXTRACTION'`)을 만들고 `draft_version_id` 를 그 판으로 둔다. DB 에서 `knowledge_cards` INSERT·title/content UPDATE 는 더 이상 판을 만들지 않는다.

- [ ] **Step 1: migration** — `supabase/migrations/20261010120000_w_drop_legacy_card_version_trigger.sql`

```sql
-- Phase A — 카드 행 쓰기가 블록 없는 판을 몰래 만들던 레거시 트리거를 없앤다(설계 A-D2, F2).
-- 이제 카드 판은 코드가 명시적으로 만든다(ingest/repository.insert_card, fact_cards, fact_edit).
-- 함수는 다른 트리거가 쓰지 않으면 함께 지운다.
drop trigger if exists trg_knowledge_cards_version_legacy_write on knowledge_cards;
drop function if exists askbuddy_version_legacy_card_write();
```

  적용 전 `grep -rn "askbuddy_version_legacy_card_write" supabase/migrations` 로 다른 트리거가 그 함수를 쓰지 않는지 확인한다(쓰면 함수 삭제 줄을 빼고 이유를 주석으로).
- [ ] **Step 2: 실패하는 테스트 쓰기** — `api/tests/test_wa_insert_card.py`

```python
"""Phase A Task 7 — 카드 판 1 은 코드가 만든다."""
from __future__ import annotations

import pytest

from app.ingest import repository as repo


class _Conn:
    def __init__(self):
        self.calls = []

    async def fetchval(self, query, *args):
        self.calls.append(query)
        if "insert into knowledge_cards" in query:
            return 5
        if "insert into card_versions" in query:
            return 50
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.calls.append(query)


@pytest.mark.asyncio
async def test_insert_card_creates_version_one_and_points_draft():
    conn = _Conn()
    card_id = await repo.insert_card(conn, 7, category_id=1, source_id=11, title="음료Z",
                                     content="음료Z 물 225ml", confidence=90.0, entity_id=4)
    assert card_id == 5
    joined = "\n".join(conn.calls)
    assert "insert into card_versions" in joined
    assert "'EXTRACTION'" in joined
    assert "draft_version_id" in joined
```

  (`insert_card` 가 `fetchrow` 를 쓰면 가짜 연결에 맞춰 더한다.)
- [ ] **Step 3: 실패 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests/test_wa_insert_card.py` / Expected: FAIL (`insert into card_versions` 없음).
- [ ] **Step 4: 구현** — `insert_card` 에서 카드 INSERT 뒤:

```python
    version_id = await conn.fetchval(
        "insert into card_versions (store_id, card_id, version_no, title, content, change_source) "
        "values ($1, $2, 1, $3, $4, 'EXTRACTION') returning version_id",
        store_id, card_id, title, content)
    # 레거시 트리거가 없어졌다 — 판 1 과 초안 포인터를 여기서 잇는다(Phase A)
    await conn.execute(
        "update knowledge_cards set draft_version_id = $3 where store_id = $1 and card_id = $2",
        store_id, card_id, version_id)
```

  `card_versions.created_by`·`created_at` 기본값이 필요한지 스키마를 보고 맞춘다. `create_owner_answer_card` 도 같은 방식(`change_source='OWNER_ANSWER'`, `created_by`·`owner_answer_id` 를 INSERT 에 바로 넣고 뒤의 `update card_versions` 를 지운다).
- [ ] **Step 5: 통과 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests` / Expected: 실패 0.
- [ ] **Step 6: 검증 픽스처 정리**
  - `verify_r_w3_consumer.py:63-64`: 카드 INSERT 뒤 `insert into card_versions (store_id, card_id, version_no, title, content, change_source) values ($1,$2,1,'라테',$3,'EXTRACTION') returning version_id` 로 판을 만들고 `update knowledge_cards set draft_version_id=$3 …` 를 한 뒤 그 id 를 `vid` 로 쓴다(블록 INSERT 는 그대로).
  - `verify_r_owner_candidates.py:36-49`: RAW 카드 INSERT·공개를 `seed_fact_card(pool, store_id=sid, owner_user_id=uid, assertions=[assertion("f1", <그 스크립트의 카드 제목>, "안내", <원래 content>)])` + `publish_card(...)` 로 바꾼다. 이후 후보 검색 기대값(카드 id·제목)이 사실 카드 제목(대상 정식 이름)과 맞는지 확인하고, 다르면 기대값만 고친다.
  - W 스크립트: RAW 카드를 직접 넣고 공개하던 픽스처는 `seed_fact_card`+`publish_card` 로, 판만 필요하던 곳은 위 `card_versions` 명시 INSERT 로. 레거시 RAW 동작 자체를 검사하던 check 는 지운다(지운 check 이름 기록). `grep -rn -E "w_owner_answer_raw_publish|ensure_raw_blocks|raw_spans|w_fact_assembly_enabled|w_entity_revision_enabled|w_upload_proposals_enabled|w_fact_card_edit_enabled" api/scripts` 가 비어야 한다(단 `verify_w_publication_flow.py` §8 의 `raw_spans` 매장 교차 트리거 검사는 표가 남아 있으므로 유지 가능 — 유지하면 이유 주석).
  - `verify_w_fact_only.py` (d): (d-1) 업로드 경로(`seed_fact_card`)·점주 답변 경로(시나리오 b 의 카드)·`create_owner_answer_card` 직접 호출, 세 경로 모두 `draft_version_id` 가 가리키는 판이 있고 `version_no = 1`. (d-2) `insert into knowledge_cards (store_id, title, content) …` 직접 INSERT 는 판을 만들지 않는다(`draft_version_id is null`) — 트리거가 없어졌다는 확인. (d-3) `pg_trigger` 에 `trg_knowledge_cards_version_legacy_write` 가 없다.
- [ ] **Step 7: 실제 DB 전체 확인** — 재구축 검증 전체 실행. Expected: **모든 PASS, FAIL 0**(이 Task 부터 초록). 실패하면 원인과 함께 멈추고 보고한다.
- [ ] **Step 8: 격리 검사**(`api/app/ingest api/app/learn/knowledge_apply.py`)·저장소 스킬 `store-isolation-check` 절차·**변경 파일 목록 기록.**

---

### Task 8: 남은 플래그 흔적 정리 · 확인

**Files:**
- Modify: `api/app/config.py`, `api/app/ingest/schemas.py:135`, `api/app/ingest/repository.py:211`, `api/app/ingest/variant_split.py` 등 플래그를 언급하는 주석
- Test: `api/tests/test_wa_upload_single_path.py` (검사 추가)

**Interfaces:**
- Consumes: Task 1~3.
- Produces: 저장소 코드에 지운 플래그 이름이 남지 않는다(문서는 Task 12).

- [ ] **Step 1: 실패하는 테스트 추가** — `test_wa_upload_single_path.py` 에

```python
ALL_REMOVED = REMOVED_FLAGS + ("w_fact_card_edit_enabled", "w_owner_answer_raw_publish")


def test_no_removed_flag_names_in_code():
    root = Path(pipeline.__file__).resolve().parents[2]  # api/
    hits = []
    for folder in ("app", "scripts", "tests"):
        for path in (root / folder).rglob("*.py"):
            if path.name == "test_wa_upload_single_path.py":
                continue
            text = path.read_text(encoding="utf-8")
            for name in ALL_REMOVED:
                if name in text or name.upper() in text:
                    hits.append(f"{path.relative_to(root)}:{name}")
    assert hits == []
```

- [ ] **Step 2: 실패 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests/test_wa_upload_single_path.py` / Expected: 남은 주석·스크립트 위치 목록과 함께 FAIL(이미 비어 있으면 PASS — 그대로 기록).
- [ ] **Step 3: 주석·문구 정리** — 목록의 위치마다 플래그 이름을 지우고 "Phase A 부터 항상" 같은 현재 동작으로 고친다. `w_owner_answer_worker_enabled`·`assemble_concurrency`·`w_entity_candidate_max`·`card_fact_parse_*` 는 남긴다(설계 A-D1).
- [ ] **Step 4: 통과 확인** — Run: `cd api && .venv/bin/python -m pytest -q tests` / Expected: 실패 0.
- [ ] **Step 5: 변경 파일 목록 기록.**

---

### Task 9: 1회 삭제 migration · 데이터 찬 DB 리허설 (시나리오 a)

**Files:**
- Create: `supabase/migrations/20261010110000_w_wipe_knowledge_once.sql`
- Modify: `api/scripts/verify_w_fact_only.py` (시나리오 (a))

**Interfaces:**
- Consumes: Task 5 의 `owner_answer_sources`, Task 7 이후 초록 재구축 검증.
- Produces: 이 migration 이 적용된 DB 에는 지식·자료·답변 인용 행이 없고, 남길 표(A-U6)의 행 수는 그대로다. `stores.guide_completed_at` 은 null.

- [ ] **Step 1: FK·트리거 목록 뽑기** — 재구축 DB(Task 7 의 docker)에서 아래를 돌려 결과를 계획 보고에 붙인다.

```sql
-- 지울 표를 가리키는 모든 FK 와 삭제 동작
select c.conrelid::regclass as child, c.confrelid::regclass as parent, c.confdeltype
from pg_constraint c
where c.contype = 'f' and c.confrelid::regclass::text = any (array[
  'knowledge_cards','card_versions','sources','source_facts','knowledge_facts','fact_revisions',
  'knowledge_entities','knowledge_snapshots','ingest_jobs','fact_occurrences','raw_spans',
  'r_index_preparations','r_index_publications','source_video','source_fact_occurrences',
  'knowledge_change_proposals','upload_change_proposals','r_answer_receipts'])
order by parent, child;

-- 지울 표에 걸린 삭제 차단 트리거
select tgname, tgrelid::regclass from pg_trigger
where not tgisinternal and tgrelid::regclass::text = any (array[
  'r_answer_citations','r_answer_receipts','knowledge_snapshots','snapshot_card_versions',
  'r_index_documents','r_index_preparations','r_index_publications','fact_revisions',
  'fact_revision_meta','knowledge_entity_events','raw_spans','card_version_blocks',
  'card_block_facts','card_version_fact_provenance','message_citations'])
order by 2, 1;
```

  **멈춤 규칙:** 평가 기록(`extraction_runs`·`extraction_results`·`evaluation_runs`·`evaluation_results`·`evaluation_cases`·`quality_evaluations`) 이나 비용 원장(`ai_usage_attempts`·`cost_assessments`)·`extraction_raw_responses` 가 지울 표를 `RESTRICT`/`NO ACTION` 으로 가리키면 migration 을 쓰지 말고 사용자에게 묻는다(그 행을 지울지·FK 를 둘지는 사람이 정한다).
- [ ] **Step 2: migration 쓰기** — 설계 A-D5 의 순서를 따른다. 뼈대(Step 1 결과로 표·트리거를 보태고, 없는 표는 뺀다):

```sql
-- Phase A — 배포 때 한 번 도는 지식·자료 삭제 (설계 A-D5, 사용자 결정 A-U5·A-U6).
-- 지우는 것: 지식 전부 + 업로드 자료 + 답변 인용 기록(R 표 포함). R 표 구조는 바꾸지 않는다.
-- 남기는 것: 매장·계정·카테고리·근무조·질문·점주 답변·채팅 문장·비용 원장·알림·로드맵 틀·체크리스트 제출.
-- 불변 트리거는 이 트랜잭션 안에서만 끄고 다시 켠다(DDL 도 트랜잭션에 묶여 실패하면 함께 되돌아간다).
-- migration 은 버전당 한 번 적용된다. 빈 DB 에서 돌아도 지울 것이 없어 무해하다.
-- 되돌리기는 배포 워크플로의 migration 직전 DB 백업뿐이다(FACT_ONLY_ROLLOUT.md).
begin;

alter table r_answer_citations disable trigger r_answer_citation_immutable;
alter table r_answer_receipts disable trigger r_answer_receipt_immutable;
alter table knowledge_snapshots disable trigger trg_snapshot_immutable;
alter table r_index_documents disable trigger r_index_documents_immutable;
alter table fact_revisions disable trigger trg_fact_revision_immutable;
alter table fact_revision_meta disable trigger trg_fact_revision_meta_immutable;
alter table knowledge_entity_events disable trigger trg_entity_event_immutable;

-- 1. 답변 인용
delete from r_answer_citations;
delete from r_answer_receipts;
delete from message_citations;
-- 2. 제안·편집
delete from knowledge_change_proposals;
delete from upload_change_proposal_facts;
delete from upload_change_proposals;
delete from card_fact_edits;
-- 3. 판 고정
delete from card_version_fact_provenance;
delete from card_block_facts;
delete from card_version_blocks;
delete from raw_spans;
-- 4. 카드 부속
delete from card_evidence;
delete from card_embeddings;
delete from facts;
delete from card_facts;
delete from card_review_events;
delete from checklist_card_shifts;
delete from checklist_cards;
delete from reclassification_results;
-- 5. 사실 원장
delete from fact_conflicts;
delete from fact_owner_answer_links;
delete from source_fact_revision_links;
delete from fact_occurrences;
delete from fact_revision_requires;
delete from fact_revision_meta;
update knowledge_facts set head_revision_id = null;
delete from fact_revisions;
delete from knowledge_facts;
delete from knowledge_entity_candidates;
delete from knowledge_entity_events;
delete from knowledge_entity_aliases;
update knowledge_cards set entity_id = null;
delete from knowledge_entities;
-- 6. 자료 원장
delete from source_fact_occurrences;
delete from source_facts;
-- 7. 카드
update knowledge_cards set draft_version_id = null, published_version_id = null;
delete from card_versions;
delete from knowledge_cards;
-- 8. 공개판·색인(R)
update knowledge_publications set current_snapshot_id = null;  -- 칼럼·제약은 Step 1 결과로 맞춘다
delete from r_index_publications;
delete from r_index_documents;
delete from r_index_preparations;
delete from snapshot_card_versions;
delete from knowledge_snapshots;
delete from knowledge_publications;
delete from operations where idempotency_key like 'r-initial-empty%' or operation_kind = 'PUBLISH_CARDS';  -- 실제 칼럼명은 Step 1 에서 확인
-- 9. 작업·자료
delete from owner_answer_sources;
delete from ingest_job_sources;
delete from ingest_jobs;
delete from source_frames;
delete from source_video;
delete from source_voice;
delete from source_kakao;
delete from source_scan;
delete from sources;
-- 10. 체크리스트 체크(지워진 판을 가리킨다). 제출 기록은 남긴다
delete from checklist_check_events;
delete from checklist_checks;
-- 리셋
update stores set guide_completed_at = null;

alter table r_answer_citations enable trigger r_answer_citation_immutable;
alter table r_answer_receipts enable trigger r_answer_receipt_immutable;
alter table knowledge_snapshots enable trigger trg_snapshot_immutable;
alter table r_index_documents enable trigger r_index_documents_immutable;
alter table fact_revisions enable trigger trg_fact_revision_immutable;
alter table fact_revision_meta enable trigger trg_fact_revision_meta_immutable;
alter table knowledge_entity_events enable trigger trg_entity_event_immutable;

commit;
```

  주의: `supabase db push` 와 재구축 검증 스크립트가 파일을 트랜잭션으로 감싸는지 확인하고, 감싸면 `begin;`/`commit;` 을 지운다(이중 트랜잭션 경고 방지). 공개 멱등 기록 표(`operations` 등)의 실제 이름·칼럼은 `api/app/publish/approval.py` `_read_operation` 의 SQL 에서 확인해 맞춘다. `knowledge_publications` 를 지울지 포인터만 비울지는 F11(`ensure_initial_publication` 이 공개판 행이 없을 때 만드는지, 있을 때 쓰는지)을 `api/app/publish/empty.py` 로 확인해 정한다 — 첫 질문이 빈 공개판을 만들 수 있는 쪽.
- [ ] **Step 3: 시나리오 (a) — 데이터 찬 DB 리허설** (`verify_w_fact_only.py`)
  - 재구축 검증은 migration 을 전부 적용한 **뒤** 픽스처를 만든다. 그래서 (a) 는 migration 파일을 **한 번 더 실행**해 리허설한다: 시나리오 (b)·(c)·(d) 가 데이터를 채운 뒤(R 답변 인용·공개판·색인·체크리스트 체크 포함), 남길 표 행 수를 센다 → `await db.execute(Path(".../20261010110000_w_wipe_knowledge_once.sql").read_text())` → 다시 센다.
  - 남길 표(행 수 불변): `stores`·`users`·`store_members`·`task_categories`·`store_shifts`·`member_shifts`·`pending_questions`·`pending_question_occurrences`·`owner_answers`·`r_owner_answer_revisions`·`chat_sessions`·`chat_messages`·`ai_usage_attempts`·`extraction_raw_responses`·`notification_events`·`roadmap_stages`·`checklist_submissions`·`outbox_events`.
  - 지울 표(행 0): Step 2 의 `delete from` 대상 전부.
  - `roadmap_items.card_id`·`owner_answers.card_id`·`learning_progress` 의 카드 연결이 null.
  - 불변 트리거가 다시 켜졌다: `pg_trigger.tgenabled = 'O'` (위 7개).
  - 지운 뒤 첫 직원 질문: R `app.publish.empty.ensure_initial_publication(pool, store_id=…, member_id=…, user_id=…)` → 빈 공개판(`knowledge_publications.current_snapshot_id` 있음, 카드 0). 이어서 `hybrid_search`/`decide` 가 근거 없음으로 이관(ESCALATE)하는지 확인한다(R 함수 호출만).
  - 마지막에 같은 파일을 한 번 더 실행해 빈 DB 에서도 무해(오류 없음).
- [ ] **Step 4: 실제 DB 전체 확인** — 재구축 검증 전체. Expected: FAIL 0.
- [ ] **Step 5: 저장소 스킬 `store-isolation-check`**(migration 절차 포함)·**변경 파일 목록 기록.**

---

### Task 10: Storage 정리 스크립트

**Files:**
- Create: `api/scripts/wipe_storage_sources.py`
- Test: `api/tests/test_wa_wipe_storage.py`

**Interfaces:**
- Consumes: `app.usage.storage_inventory.list_store_objects(store_id) -> list[dict]`, 설정 `supabase_url`·`supabase_service_key`·`storage_bucket`.
- Produces: CLI `python scripts/wipe_storage_sources.py [--store-id N | --all-stores] [--apply]`. 기본은 dry-run(목록·개수·총 바이트만). `--apply` 일 때만 `DELETE {supabase_url}/storage/v1/object/{bucket}` 에 `{"prefixes": [...]}` 를 100개씩 보낸다. 매장 목록은 DB `stores` 에서 읽는다.
- 순수 함수 `plan_deletions(objects: list[dict], *, store_id: int) -> list[str]` — 이름이 `f"{store_id}/"` 로 시작하는 객체 경로만(다른 매장 접두사·이상한 이름은 버린다), 정렬.

- [ ] **Step 1: 실패하는 테스트**

```python
from scripts.wipe_storage_sources import plan_deletions


def test_plan_only_own_store_prefix():
    objects = [{"name": "7/voice/a.m4a"}, {"name": "70/voice/b.m4a"}, {"name": "7/scan/c.pdf"},
               {"name": "../7/x"}, {"name": "8/kakao/d.txt"}]
    assert plan_deletions(objects, store_id=7) == ["7/scan/c.pdf", "7/voice/a.m4a"]
```

  (`api/tests` 에서 `scripts` 를 import 하는 기존 방식이 있으면 따른다. 없으면 `sys.path` 에 `api/scripts` 를 넣는 conftest 없이 `importlib.util.spec_from_file_location` 으로 읽는다.)
- [ ] **Step 2: 실패 확인 → Step 3: 구현** — `list_store_objects` 가 돌려주는 객체의 경로 키를 그 함수 코드에서 확인해 `plan_deletions` 에 맞춘다. 기본 dry-run 출력: 매장별 `store=<id> 객체 <n>개 <bytes>B`. `--apply` 전에 "되돌릴 수 없다" 경고 한 줄. 네트워크 오류는 매장 단위로 보고하고 0 아닌 종료 코드.
- [ ] **Step 4: 통과 확인** — `cd api && .venv/bin/python -m pytest -q tests/test_wa_wipe_storage.py`. 실제 Storage 에는 실행하지 않는다(사용자 실행).
- [ ] **Step 5: 변경 파일 목록 기록.**

---

### Task 11: 데모 시드 — 카드 없이

**Files:**
- Modify: `db/002_seed_demo.sql` (`knowledge_cards`·그 카드를 가리키는 `roadmap_items`·`learning_progress`·인용 INSERT 삭제, 마지막 확인 주석 `-- 3` → `-- 0`)
- Modify: `api/scripts/demo_seed.py` (자료·카드·카드 연결 로드맵 항목·카드 인용 채팅·`bootstrap_store_index` 삭제. 남김: 매장·계정·초대코드·카테고리·근무조·로드맵 틀(`roadmap_stages`)·카드 없는 대기 질문)
- Modify: 시연 절차 문서(`docs/dev/` 에서 `demo_seed` 를 안내하는 문서를 `grep -rln demo_seed docs/dev` 로 찾아 "데모 카드는 자료 업로드로 만든다" 한 줄 추가)

**Interfaces:**
- Consumes: 없음
- Produces: 데모 매장에 카드 0장. 첫 직원 질문은 이관(근거 없음)된다.

- [ ] **Step 1:** 두 시드에서 카드 관련 INSERT 를 지운다. `demo_seed.py` 에서 지운 함수·import 가 남지 않게.
- [ ] **Step 2: 확인** — 재구축용 docker DB 에 `psql … -f db/001_init_schema.sql`(필요하면) 대신 재구축 검증 DB 에서 `db/002_seed_demo.sql` 을 실행해 오류 없음·`select count(*) from knowledge_cards` = 0 을 확인한다(실행 방법은 파일 머리 주석을 따른다). `demo_seed.py` 는 `--help` 또는 dry-run 이 있으면 그것만 돌린다. 운영·배포 DB 에는 실행하지 않는다.
- [ ] **Step 3: 변경 파일 목록 기록.**

---

### Task 12: 절차서 · 인계 · 현황 문서

**Files:**
- Create: `docs/dev/plan/FACT_ONLY_ROLLOUT.md`
- Modify: `docs/dev/plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md` (§13 에 "Phase A 구현" 하위 절, R 이 할 일 12 에 답·새 항목)
- Modify: `docs/dev/DEV_TODO_CURRENT.md` (플래그 언급을 현재 상태로, Phase A 항목)
- Modify: `docs/dev/plan/W_FACT_ONLY_ROADMAP_20261010.md` §1 표의 Phase A 상태 → "구현 완료(브랜치 `w/phase-a-fact-only`), 배포 대기"

**Interfaces:** 없음(문서).

- [ ] **Step 1: 절차서** `FACT_ONLY_ROLLOUT.md` — 독자: 배포하는 사용자. 순서:
  1. 머지 전: R 인계 12-(a)(W3-4 필수 검토) 완료 확인. **Phase B 를 같이 배포하지 않으면 체크리스트는 다시 연결하지 않는다**(설계 §7).
  2. 배포 워크플로(`.github/workflows/deploy-api.yml`) 실행 → **DB 백업 단계 성공을 먼저 확인**(유일한 되돌리기). 실패면 멈춘다.
  3. migration 3개 적용 확인: `select version from supabase_migrations.schema_migrations where version like '20261010%'`.
  4. 서버 배포 확인. env: `W_OWNER_ANSWER_WORKER_ENABLED=true` 확인. 지운 플래그 줄(`W_ENTITY_REVISION_ENABLED`·`W_UPLOAD_PROPOSALS_ENABLED`·`W_FACT_ASSEMBLY_ENABLED`·`W_FACT_CARD_EDIT_ENABLED`·`W_OWNER_ANSWER_RAW_PUBLISH`)은 지워도 되고 남아도 무시된다.
  5. 확인 SQL: 카드 0·자료 0·`r_answer_citations` 0, 질문·점주 답변 수 그대로.
  6. Storage 정리: `cd api && python scripts/wipe_storage_sources.py --all-stores`(dry-run) → 목록 확인 → `--apply`.
  7. 자료 재업로드 → 카드 검수·공개 → 직원 질문 1건으로 답변·인용 확인 → 점주 답변 1건으로 사실 카드 자동 공개 확인(지연 기록).
  8. 체크리스트 재연결은 Phase B 머지 뒤.
  9. 되돌리기: 백업 복원 절차(배포 워크플로 문서 위치) — 코드만 되돌리면 지워진 데이터는 돌아오지 않는다.
- [ ] **Step 2: R 인계** — §13 에 "Phase A 구현(2026-10-10, 브랜치 `w/phase-a-fact-only`)" 하위 절:
  - 12-(d) 답(코드 확인): R `learn/router.py` 는 옛 함수 3개를 import 하지 않는다 → W 가 Task 13 에서 지웠다. **R 확인 대기.**
  - v1 `/learn/pending/{id}/answer`·`/learn/knowledge-proposals/{id}/approve` 는 이제 사실 초안이 없으면 `approve_owner_proposal` 이 `ValueError` → 409. v1 NEW 는 `FAILED`(점주 원문 전달은 그대로). 웹 `/owner/questions` 목록·`/owner/cards/proposals` 가 아직 v1 을 쓴다 → **R 이 할 일 14 (새 항목): v1 점주 답변·제안 화면을 v2 로 옮기거나 닫는다.**
  - 점주 답변 제안의 `relation_type` 의미 변화(12-(e) 에 답): NEW = 새 카드, SUPPLEMENT = 공개 카드 새 초안, IDENTICAL = 이미 공개된 같은 사실. CONFLICT 는 더 만들지 않는다. reason 에 `NO_FACTS`·`FACTS_PENDING` 이 생겼다. 승인 = 그 답변이 만든 초안 카드 전부 공개.
  - 점주 답변 근거 = `OWNER_TEXT` 자료 occurrence, 자료 ↔ 답변은 `owner_answer_sources`(12-(f) 표시 요청 유지).
  - R 소유 검증 3개를 W 가 고쳤다(P-3): 바꾼 줄 요약.
  - 작업 완료 알림 문구(`notifications/service.py` "새 카드가 준비됐어요 / 검토할 업무 카드 N개")를 "카드 N장에 반영됐어요" 쪽으로 바꿔 달라(R 이 할 일 15, 새 항목). W 는 `card_count` 의미를 "이 자료가 이어진 카드 수" 로 바꿨다.
  - 12-(h): 레거시 카드가 1회 삭제로 없어져 이름공간 충돌 가드를 지웠다(블록 없는 판 공개 거절로 대체).
- [ ] **Step 3: TODO·로드맵** — 현재 사실만 고친다(완료 표시는 확인한 것만).
- [ ] **Step 4: 변경 파일 목록 기록.**

---

### Task 13 (맨 뒤): 옛 함수 3개와 `create_owner_answer_card` 삭제

**Files:**
- Modify: `api/app/learn/knowledge_apply.py` (삭제: `prepare_proposal`·`publish_new_proposal`·`publish_existing_proposal`·`create_owner_answer_card`; `resolve_owner_answer_category` 는 worker 가 쓰므로 남긴다)
- Modify: `api/scripts/verify_w_publication_flow.py:25,666-690` (import 와 레거시 R 경로 검사 구간 삭제)
- Modify: `api/scripts/verify_w_fact_only.py` (d-1 의 `create_owner_answer_card` 경로 삭제)
- Test: `api/tests/test_wa_owner_outcome.py` (검사 추가)

**Interfaces:**
- Consumes: Task 6·7.
- Produces: `knowledge_apply` 에 남는 공개 이름 = `approve_owner_proposal`·`resolve_owner_answer_category`·`APPROVABLE_PROPOSAL_STATUSES`·`OwnerReviewNotifier`·`LEGACY_PROPOSAL_MESSAGE`·`NO_DRAFT_MESSAGE`.

- [ ] **Step 1: 삭제 전 재확인** — `grep -rn -E "prepare_proposal|publish_new_proposal|publish_existing_proposal|create_owner_answer_card" api/app api/scripts api/tests` 결과에 `api/app/learn/router.py` 등 R 소유 파일이 **없어야** 한다. 있으면 멈추고 사용자에게 보고한다(P-1 전제가 깨짐).
- [ ] **Step 2: 실패하는 테스트 추가**

```python
def test_legacy_owner_answer_functions_are_gone():
    from app.learn import knowledge_apply as ka
    for name in ("prepare_proposal", "publish_new_proposal", "publish_existing_proposal",
                 "create_owner_answer_card"):
        assert not hasattr(ka, name), name
```

- [ ] **Step 3: 실패 확인 → Step 4: 삭제** — 위 네 함수와 그것만 쓰던 `_attach_owner_answer_citations` 호출부 확인(`_finish_proposal` 이 계속 쓰면 남긴다), 스크립트 구간 삭제.
- [ ] **Step 5: 전체 확인** — `cd api && .venv/bin/python -m pytest -q tests`(실패 0), 재구축 검증 전체(FAIL 0), 격리 검사, `cd web && pnpm check`.
- [ ] **Step 6: 인계 문서** — R 이 할 일 5 에 "W 가 2026-10-10 Phase A 에서 지웠다(코드 확인, R 확인 대기)" 표시.
- [ ] **Step 7: 최종 보고** — 변경 파일 전체 목록, 브랜치 이름, 테스트 수 변화와 이유, 재구축 검증 결과, web 정적 검사·브라우저 확인 구분, 사람이 할 일(배포 절차서). 커밋하지 않는다.

---

## Self-Review (계획 작성자 확인)

1. **설계 대응:** A-D1 → Task 1·2·3·8 / A-D2 업로드 → 1, 공개 → 2, 편집 → 3, 트리거 → 7, 점주 답변 옛 경로 → 6·13, 데모 → 11 / A-D3 → 5·6 / A-D4 → 4 / A-D5 → 9·10 / A-D6 → 12 절차서 / A-D7 → 12 인계 / §5 검증 (a) → 9, (b) → 6, (c) → 4, (d) → 7, web → 3, 격리·R 무수정 → 각 Task + Global Constraints. 로드맵 §5 필수 항목(플래그 제거 범위·트리거·worker 교체·A-D4·삭제 migration 순서와 트리거 끄기·리허설·Storage·데모·절차서·인계) 모두 Task 가 있다.
2. **자리표시 검사:** "Step 1 결과로 맞춘다" 는 실제 DB 카탈로그에 기대는 확인 단계이며 멈춤 규칙을 함께 적었다.
3. **이름 일관성:** `AnswerCard`·`answer_cards`·`answer_fact_count`·`owner_answer_source`·`ensure_owner_answer_source`·`ingest_owner_text`(Task 5) ↔ Task 6 사용처 일치. `REVIEW_NEW_FACTS`/`'NEW_FACTS'`(Task 4) ↔ Task 6 판정(needs_review_reason 이 있으면 changed 판정은 판 포인터로 한다 — 사유 문자열에 기대지 않는다). `seed_fact_card`·`publish_card`(Task 4) ↔ Task 6·7 사용처 일치.
4. **Review Focus:** 다섯 줄 모두 테스트를 소유 Task 에 넣었다.
