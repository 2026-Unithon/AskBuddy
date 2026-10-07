# W3-0 Flag Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기본 꺼져 있는 `w_entity_revision_enabled`·`w_upload_proposals_enabled` 를 배포판에서 켤 수 있게 만든다. HOT/ICE 동시 사실 나누기, legacy 정정 순서, 병합 뒤 후보·제안 정리, 두 플래그를 켠 합성 종단 검증, 처리량 기록, 켜기 절차 문서까지.

**Architecture:** HOT/ICE 나누기는 원장 저장 직전(`pipeline._persist_ledger`)의 순수 함수(`app/ingest/variant_split.py`)로 하고, 조립이 쓰는 원래 ref 는 `_persist` 에서 갈라진 두 원장 열쇠로 이어 준다. legacy 정정은 head 판 메타의 `change_kind` 가 `EXTRACTION` 일 때만 얹는다. 병합 정리는 `entity_admin.merge_entities`(후보)와 `impact.record_upload_proposals`(제안·`matched_cards`)에서 하고, 새 상태·이력 어휘는 가산 migration 하나로 허용 값만 넓힌다. 종단 검증은 새 실제 DB 스크립트를 W 소유 `verify_w_entity_revision.verify()` 끝에서 부른다. 모든 새 쓰기는 기존 플래그 뒤에 있고, 플래그가 꺼져 있으면 원장·수집 DB 쓰기는 이전과 바이트 단위로 같다.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, pydantic v2(2.13), pytest(asyncio), PostgreSQL 17 + pgvector(일회용 Docker), Supabase migration.

**Spec:** `docs/dev/plan/W3_0_FLAG_READINESS_DESIGN.md` (승인됨, 이 계획의 구속 기준)

---

## Global Constraints

- 모든 DB 함수는 `store_id` 를 필수 인자로 받고, 모든 조회·쓰기에 `WHERE store_id = ...` 가 있다(D1, 기본값·`Optional` 금지).
- migration 은 가산형만. 이미 적용된 migration 파일을 고치지 않는다. 새 파일 이름은 `supabase/migrations/YYYYMMDDHHMMSS_w_<주제>.sql`, 기존 최신(`20261005110000`)보다 뒤.
- 플래그가 꺼져 있으면 원장·수집 DB 쓰기가 이전과 바이트 단위로 같다(평가 기준선 D16 보호 — 평가 실행은 플래그를 켜지 않는다).
- 새 동작은 기존 플래그 `w_entity_revision_enabled`·`w_upload_proposals_enabled` 뒤에 둔다. 코드 기본값은 계속 `False`.
- R 소유 파일을 고치지 않는다: `api/app/reg/*`, `api/app/learn/router.py`, `answering.py`, `answer_storage.py`, `owner_handoff.py`, `owner_publication.py`, `approved_renderer.py`, `v2_router.py`, `knowledge_loop.py`, auth·notifications, R migration·`owner_answers` 트리거.
- 공통 파일(`api/app/config.py`, `api/app/main.py`, `api/app/contracts/*`, `api/scripts/verify_r_schema_rebuild.py`)은 이 계획에서 고치지 않는다.
- 주석·docstring 은 한국어. 모델명·임계값은 `config.py` 단일 출처(이 계획은 새 설정을 만들지 않는다).
- 실제 브랜드·상호·메뉴 고유명을 코드·테스트·문서·커밋 메시지 어디에도 쓰지 않는다. 합성 이름(`음료Z`, `합성음료A`, `측정메뉴01`)만 쓴다.
- 유료 모델을 부르지 않는다(`INGEST_MODE=real` 실측 금지). 모든 검증은 합성 모델 대역, 비용 0.
- 배포 환경 값은 바꾸지 않는다. 켜기는 사용자가 `W3_0_FLAG_ROLLOUT.md` 를 보고 한다.
- **git 쓰기 금지: `git add`·`git commit`·`git stash`·`git push` 를 하지 않고 커밋할지 묻지도 않는다.** 사용자가 커밋·PR·머지한다. 각 Task 끝은 "변경 확인(`git status`/`git diff`), 커밋하지 않는다" 이다.
- 이 worktree(`/Users/chabee/new/New_Source/2026unithon-w3`)에는 `api/.venv` 가 없다. 파이썬은 메인 저장소 venv 를 쓴다: `PY=/Users/chabee/new/New_Source/2026unithon/api/.venv/bin/python`, 작업 폴더 `/Users/chabee/new/New_Source/2026unithon-w3/api`. 저장소 파일에 바이트코드·캐시를 남기지 않게 `-B` 와 `-p no:cacheprovider` 를 붙인다.
- 단위 테스트 기준선: `1735 passed, 4 xfailed, 131 subtests passed` (2026-10-07, 이 브랜치 HEAD `5995bac`).

공통 명령(아래 Task 에서 그대로 쓴다):

```bash
cd /Users/chabee/new/New_Source/2026unithon-w3/api
PY=/Users/chabee/new/New_Source/2026unithon/api/.venv/bin/python
# 단위 테스트 전체
$PY -B -m pytest -q -p no:cacheprovider tests
# 매장 격리 정적 검사 (기존 위반 15건은 repository.py 의 기존분 — 16건 이상이면 새 위반)
cd /Users/chabee/new/New_Source/2026unithon-w3 && python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest api/app/cards api/app/publish
# 실제 DB 전체 재구축 검증 (W/R verify 전부)
docker run -d --rm --name askbuddy-w-verify -p 127.0.0.1:55439:5432 \
  -e POSTGRES_PASSWORD=synthetic-local-test -e POSTGRES_DB=usage_verify pgvector/pgvector:pg17
cd /Users/chabee/new/New_Source/2026unithon-w3/api && PYTHONPATH=. PYTHONUTF8=1 $PY -B scripts/verify_r_schema_rebuild.py
docker stop askbuddy-w-verify
```

포트 `55439` 를 다른 프로세스가 쓰고 있으면 그 컨테이너를 지우지 말고 원인을 기록하고 멈춘다. 이번에 띄운 `askbuddy-w-verify` 만 멈춘다.

---

## Review Focus

명세가 함의하지만 테스트가 놓치기 쉬운 입력·실패 양상. 가능성이 높은 순서.

1. **조립 ref 가 갈라진 원장 열쇠를 못 찾는다.** 조립 모델은 나누기 전 사실 목록을 보므로 카드는 `f1` 을 인용하는데 원장 열쇠는 `f1~HOT`·`f1~ICE` 다. 그대로 두면 두 사실이 `DROPPED` 로 표시되고 `card_facts` 연결이 빠진다(복구 재개 경로의 `ledger_ids` 도 같다). → Task 1 `test_persist_links_card_ref_to_both_split_facts`, Task 4 T2 "조립 ref f1 → 카드가 두 사실을 모두 잇고 LINKED".
2. **플래그 켜짐 + 나눌 사실 없음이 원장을 바꾼다.** 나누기 함수가 객체를 복사하거나 `requires` 를 정리하면 `content_hash`·행 내용이 꺼짐과 달라질 수 있다. → Task 1 `test_non_multi_temperature_passes_through_as_the_same_objects`, `test_persist_ledger_flag_on_without_multi_is_identical_to_off`, Task 4 T8.
3. **`requires` 재작성과 40자 이름표.** 다른 사실이 갈라진 사실을 가리키면 둘 다를 가리켜야 하고, 가리키는 쪽도 갈라졌으면 같은 온도만 가리켜야 한다(HOT 절차가 ICE 선행에 매이지 않게). 원래 ref 가 37자 이상이면 `~HOT`·`~ICE` 가 원장 `local_ref`(40자) 에서 잘려 두 행이 같은 이름표가 된다. → Task 1 `test_requires_pointing_to_split_fact_points_to_both`, `test_split_dependent_requires_only_the_same_temperature`, `test_long_local_ref_stays_within_40_chars_and_distinct`.
4. **입력 객체 변경.** 나누기가 원래 assertion 을 고치면 같은 객체를 쓰는 조립 입력과 복구 캐시(`recovery` EXTRACTED 단계)가 오염된다. 비공개 속성(`_raw_response_id`·`_layout_locator`·`_check_flags`)은 사본마다 따로 가져야 한다. → Task 1 `test_private_attributes_are_copied_and_marker_added_only_to_copies`.
5. **제안 옮기기가 유일 제약에 걸린다.** `upload_change_proposals` 는 `unique (store_id, source_id, entity_id)` 다. 병합된 대상 아래 PENDING 제안을 살아 있는 대상으로 옮길 때 그 자료의 살아 있는 대상 제안이 이미 있으면 UPDATE 가 실패한다. 그때는 옛 제안을 `SUPERSEDED` 로 닫아야 하고, 결정된 제안은 건드리지 않는다. → Task 3 `test_pending_proposal_of_merged_entity_is_superseded_when_live_one_exists`, Task 4 T5 "병합 뒤 A 재처리 → … 옛 B 제안 SUPERSEDED".

---

## File Structure

| 경로 | 구분 | 책임 |
|---|---|---|
| `api/app/ingest/entity_names.py` | 수정 | `strip_temperature()` 추가 — 규격 문자열에서 온도 낱말만 뺀 나머지 |
| `api/app/ingest/variant_split.py` | 생성 | HOT/ICE 동시 사실을 규격별 두 사실로 나누는 순수 함수, 갈라진 이름표 규칙 |
| `api/app/ingest/pipeline.py` | 수정 | `_persist_ledger` 에서 플래그 켜짐일 때 나누기, `_persist` 에서 원래 ref → 갈라진 원장 열쇠 연결 |
| `api/app/ingest/fact_revisions.py` | 수정 | `import_legacy_correction` 이 head 가 `EXTRACTION` 이 아니면 건너뜀 |
| `supabase/migrations/20261007090000_w_merge_cleanup_states.sql` | 생성 | 후보 상태 `MERGED`, 대상 이력 `CANDIDATE_MOVED`·`PROPOSAL_MOVED` 허용(CHECK 넓히기) |
| `api/app/ingest/entity_admin.py` | 수정 | `merge_entities` 가 (병합된 대상, 제3 대상) PENDING 후보를 keep 쪽으로 옮기거나 닫음 |
| `api/app/ingest/impact.py` | 수정 | 병합 사슬 끝으로 묶기, 병합된 대상의 PENDING 제안 옮기기, 같은 순위 `matched_cards` 갱신 |
| `api/tests/test_w3_variant_split.py` | 생성 | Task 1 단위 테스트 |
| `api/tests/test_w2_fact_revisions.py` | 수정 | Task 2 단위 테스트(기존 legacy 이관 테스트 응답 보강 포함) |
| `api/tests/test_w2_entity_admin.py` | 수정 | Task 3 병합 후보 정리 테스트 |
| `api/tests/test_w2_impact.py` | 수정 | Task 3 제안 옮기기·같은 순위 갱신 테스트(가짜 연결 보강) |
| `api/scripts/verify_w3_flag_readiness.py` | 생성 | 두 플래그를 켠 실제 DB 합성 종단 검증 T1~T8 |
| `api/scripts/verify_w_entity_revision.py` | 수정 | `verify()` 끝에서 W3-0 종단 검증을 부름, docstring 한 줄 |
| `api/scripts/probe_w3_flag_throughput.py` | 생성 | 처리량 측정(합성 300 사실·60 대상·10 구간, 모델 호출 없음) |
| `api/tests/test_w3_throughput_probe.py` | 생성 | 측정 스크립트의 순수 함수 테스트 |
| `docs/dev/review/W3_0_THROUGHPUT_<측정일 YYYYMMDD>.md` | 생성 | 처리량 측정 기록 |
| `docs/dev/plan/W3_0_FLAG_ROLLOUT.md` | 생성 | 배포판 켜기 절차(사용자 실행) |
| `docs/dev/plan/W_NEXT_PLAN_20260928.md` | 수정 | W2 에서 넘어온 것·플래그 켜기 전 점검 항목 닫기 |
| `docs/dev/plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md` | 수정 | "R 이 할 일" 8번 닫기(§3-4) |
| `docs/dev/DEV_TODO_CURRENT.md` | 수정 | W3 절에 W3-0 완료 줄 |

---

### Task 1: HOT/ICE 동시 사실을 원장에서 규격별 두 사실로 나누기 (설계 §3-1)

**Files:**
- Modify: `api/app/ingest/entity_names.py` (파일 끝 `candidate_reason` 앞, `parse_variant` 다음 — 현재 105행 뒤에 함수 추가)
- Create: `api/app/ingest/variant_split.py`
- Modify: `api/app/ingest/pipeline.py:19-24` (import), `:917-981` (`_persist_ledger`), `:1033-1155` (`_persist` — `:1082-1083`, `:1113-1114` 와 새 헬퍼)
- Test: `api/tests/test_w3_variant_split.py`

**Interfaces:**
- Consumes: `app.ingest.entity_names.parse_variant(raw: str | None) -> VariantParts`(`multi_temperature: bool`), `ExtractedAssertion`(pydantic v2, 필드 `local_ref, variant, requires, …`, 비공개 `_raw_response_id, _check_flags, _layout_locator`, 속성 `check_flags -> list[dict]`, `as_variant() -> str | None`), `pipeline._persist_ledger(conn, store_id: int, source_id: int, source_type: str, assertions: list) -> dict[str, int]`, `repo.insert_source_facts(conn, store_id, source_id, rows, *, locator_type, locator, extract_version) -> list[int]`, `occurrences.insert_occurrences(conn, store_id: int, rows: list[dict]) -> None`, `repo.link_card_facts(conn, store_id, card_id, fact_ids)`, `repo.set_assembly_state(conn, store_id, fact_ids, state)`.
- Produces:
  - `entity_names.strip_temperature(raw: str | None) -> str`
  - `variant_split.split_ref(ref: str, temperature: str) -> str`
  - `variant_split.split_refs(ref: str) -> tuple[str, str]`
  - `variant_split.needs_split(variant: str | None) -> bool`
  - `variant_split.split_hot_ice(assertions: list) -> list`
  - `variant_split.VERDICT_SPLIT = "VARIANT_SPLIT"`
  - `pipeline._ledger_keys(ledger: dict[str, int], ref: str) -> list[str]`

check_flags 표시 모양(설계 §3-1 의 예시 `{"variant_split": "HOT_ICE"}` 를 기존 판정 모양 `{field, verdict, value}` 에 합친다):
`{"field": "variant", "verdict": "VARIANT_SPLIT", "value": "<원래 variant>", "variant_split": "HOT_ICE", "from_ref": "<원래 local_ref>"}`

- [ ] **Step 1: 실패하는 테스트 작성** — `api/tests/test_w3_variant_split.py`

```python
"""W3-0 §3-1 — HOT/ICE 가 함께 적힌 사실을 원장에서 규격별 두 사실로 나눈다.

순수 함수와 파이프라인 연결(_persist_ledger·_persist)을 본다. 설정은 필드가 몇 개뿐인
NS 로 patch 한다(F18). 모델·DB 는 부르지 않는다. 실제 DB 동작은
scripts/verify_w3_flag_readiness.py 의 T2·T8 이 본다.
"""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import fact_ledger, pipeline, variant_split
from app.ingest.entity_names import strip_temperature
from app.ingest.schemas import (ExtractedCard, ExtractedFact, ExtractionResult,
                                LocatedAssertion, LocatedEvidence)


def _a(ref, *, variant="HOT/ICE", requires=(), value="2"):
    return LocatedAssertion(local_ref=ref, original_assertion=f"음료Z 에스프레소 {value}샷",
                            subject="음료Z", attribute="에스프레소", value=value, unit="샷",
                            variant=variant, requires=list(requires),
                            conditions=["바쁠 때"], exceptions=["디카페인"], order=0,
                            confidence=.9, evidence=LocatedEvidence(timestamp_sec=12))


# ── 순수 함수 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, rest", [
    ("HOT/ICE L", "L"),
    ("핫/아이스", ""),
    ("따뜻한/차가운 R", "R"),
    ("HOT/ICE L/R", "L R"),
    (None, ""),
])
def test_strip_temperature_keeps_other_spec_words(raw, rest):
    assert strip_temperature(raw) == rest


def test_split_hot_ice_makes_two_facts_with_same_values():
    out = variant_split.split_hot_ice([_a("f1")])
    assert [a.local_ref for a in out] == ["f1~HOT", "f1~ICE"]
    assert [a.variant for a in out] == ["HOT", "ICE"]
    for a in out:
        assert (a.subject, a.attribute, a.value, a.unit, a.polarity, a.conditions,
                a.exceptions, a.order, a.original_assertion, a.evidence.timestamp_sec) == (
            "음료Z", "에스프레소", "2", "샷", "AFFIRM", ["바쁠 때"], ["디카페인"], 0,
            "음료Z 에스프레소 2샷", 12)


def test_split_keeps_size_words():
    out = variant_split.split_hot_ice([_a("f1", variant="HOT/ICE L")])
    assert [a.as_variant() for a in out] == ["HOT L", "ICE L"]


@pytest.mark.parametrize("variant", ["", "HOT", "ICE", "L/R", "ice/iced"])
def test_non_multi_temperature_passes_through_as_the_same_objects(variant):
    items = [_a("f1", variant=variant), _a("f2", variant=variant, value="3", requires=["f1"])]
    out = variant_split.split_hot_ice(items)
    assert len(out) == 2 and all(x is y for x, y in zip(out, items))


def test_requires_pointing_to_split_fact_points_to_both():
    out = variant_split.split_hot_ice([_a("f1"), _a("f2", variant="", requires=["f1"])])
    assert [a.local_ref for a in out] == ["f1~HOT", "f1~ICE", "f2"]
    assert out[2].requires == ["f1~HOT", "f1~ICE"]


def test_split_dependent_requires_only_the_same_temperature():
    out = variant_split.split_hot_ice([
        _a("f1"), _a("f2", requires=["f1", "f0"]), _a("f0", variant="", value="1")])
    by_ref = {a.local_ref: a for a in out}
    assert by_ref["f2~HOT"].requires == ["f1~HOT", "f0"]
    assert by_ref["f2~ICE"].requires == ["f1~ICE", "f0"]
    assert by_ref["f0"].requires == []


def test_private_attributes_are_copied_and_marker_added_only_to_copies():
    original = _a("f1")
    original._raw_response_id = 55
    original._layout_locator = {"page": 2, "region": "r1"}
    original._check_flags.append({"field": "variant", "verdict": "UNGROUNDED_TEXT",
                                  "value": "HOT/ICE"})
    out = variant_split.split_hot_ice([original])
    marker = {"field": "variant", "verdict": "VARIANT_SPLIT", "value": "HOT/ICE",
              "variant_split": "HOT_ICE", "from_ref": "f1"}
    for a in out:
        assert a.raw_response_id == 55
        assert a._layout_locator == {"page": 2, "region": "r1"}
        assert a.check_flags == [original.check_flags[0], marker]
    assert out[0].check_flags is not out[1].check_flags
    assert out[0]._layout_locator is not original._layout_locator
    # 입력은 그대로 — 조립 입력과 복구 캐시가 같은 객체를 쓴다
    assert (original.local_ref, original.variant, len(original.check_flags)) == (
        "f1", "HOT/ICE", 1)


def test_long_local_ref_stays_within_40_chars_and_distinct():
    ref = "seg10.2.1:" + "r" * 35   # 45자
    out = variant_split.split_hot_ice([_a(ref)])
    refs = [a.local_ref for a in out]
    assert all(len(r) <= 40 for r in refs) and refs[0][:40] != refs[1][:40]
    assert tuple(refs) == variant_split.split_refs(ref)


# ── 파이프라인 연결 ───────────────────────────────────────────────────────────

def _settings(**extra):
    return NS(gemini_model="gemini-synthetic", extract_temperature=0.0, ingest_mode="mock",
              extract_locator_hints=False, **extra)


async def _ledger(settings, assertions, ids):
    insert = AsyncMock(return_value=ids)
    occ = AsyncMock()
    with patch.object(pipeline.repo, "insert_source_facts", insert), \
         patch.object(pipeline.occurrences, "insert_occurrences", occ), \
         patch.object(fact_ledger, "link_source_facts", AsyncMock()), \
         patch("app.config.get_settings", return_value=settings):
        out = await pipeline._persist_ledger(object(), 3, 5, "VIDEO", assertions)
    return insert.await_args.args[3], occ.await_args.args[2], out


@pytest.mark.asyncio
async def test_persist_ledger_flag_off_keeps_multi_variant_row():
    rows, occ, out = await _ledger(_settings(w_entity_revision_enabled=False), [_a("f1")], [70])
    assert [(r["local_ref"], r["variant"]) for r in rows] == [("f1", "HOT/ICE")]
    assert out == {"f1": 70} and len(occ) == 1


@pytest.mark.asyncio
async def test_persist_ledger_flag_on_splits_rows_and_occurrences():
    rows, occ, out = await _ledger(_settings(w_entity_revision_enabled=True), [_a("f1")],
                                   [70, 71])
    assert [(r["local_ref"], r["variant"]) for r in rows] == [("f1~HOT", "HOT"),
                                                              ("f1~ICE", "ICE")]
    assert out == {"f1~HOT": 70, "f1~ICE": 71}
    # 근거 위치는 두 사실 모두 원래 자리 그대로
    assert [(o["fact_id"], o["locator_type"], o["locator"]) for o in occ] == [
        (70, "TIMESTAMP", {"timestamp_sec": 12}), (71, "TIMESTAMP", {"timestamp_sec": 12})]
    assert all(o["check_flags"][-1]["verdict"] == "VARIANT_SPLIT" for o in occ)


@pytest.mark.asyncio
async def test_persist_ledger_flag_on_without_multi_is_identical_to_off():
    def items():
        return [_a("f1", variant="HOT"), _a("f2", variant="", requires=["f1"])]
    off = await _ledger(_settings(w_entity_revision_enabled=False), items(), [70, 71])
    on = await _ledger(_settings(w_entity_revision_enabled=True), items(), [70, 71])
    assert on == off


@pytest.mark.asyncio
async def test_persist_links_card_ref_to_both_split_facts():
    conn = NS(fetchval=AsyncMock(return_value="SCAN"))
    link = AsyncMock()
    state = AsyncMock()
    card = ExtractedCard(category_name="기타", title="음료Z", content="에스프레소 2샷",
                         confidence=.9, facts=[ExtractedFact(
                             object_name="음료Z", attribute="에스프레소", value="2",
                             confidence=.9, ref="f1")])
    with patch.object(pipeline.repo, "insert_card", AsyncMock(return_value=9)), \
         patch.object(pipeline.repo, "insert_facts", AsyncMock()), \
         patch.object(pipeline.repo, "link_card_facts", link), \
         patch.object(pipeline.repo, "insert_card_evidence", AsyncMock()), \
         patch.object(pipeline.repo, "set_assembly_state", state), \
         patch("app.config.get_settings", return_value=_settings()):
        await pipeline._persist(conn, 3, 5, {"기타": 1}, ExtractionResult(cards=[card]),
                                job_id=None, category_version=1,
                                ledger_ids={"f1~HOT": 70, "f1~ICE": 71, "f2": 72})
    assert link.await_args.args == (conn, 3, 9, [70, 71])
    assert [c.args for c in state.await_args_list] == [
        (conn, 3, [70, 71], "LINKED"), (conn, 3, [72], "DROPPED")]
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/chabee/new/New_Source/2026unithon-w3/api && $PY -B -m pytest -q -p no:cacheprovider tests/test_w3_variant_split.py`
Expected: 수집 단계 실패 — `ImportError: cannot import name 'variant_split' from 'app.ingest'` (그리고 `strip_temperature` 없음).

- [ ] **Step 3: `strip_temperature` 추가** — `api/app/ingest/entity_names.py` 의 `parse_variant` 바로 뒤(현재 105행 뒤)에 넣는다

```python
def strip_temperature(raw: str | None) -> str:
    """규격 문자열에서 온도 낱말(HOT/ICE 와 규격 칸 서술어)만 뺀 나머지. 원래 표기, 공백 1칸.

    W3-0 HOT/ICE 나누기가 쓴다 — 'HOT/ICE L' 을 'HOT L'·'ICE L' 로 나눌 때 사이즈 등
    나머지 규격 낱말을 그대로 남긴다.
    """
    tokens = _tokens(unicodedata.normalize("NFKC", raw or ""))
    kept = [t for t in tokens
            if t.casefold() not in TEMPERATURE_TOKENS
            and t.casefold() not in _VARIANT_ONLY_TEMPERATURE]
    return " ".join(kept)
```

- [ ] **Step 4: `variant_split.py` 생성** — `api/app/ingest/variant_split.py`

```python
"""W3-0 §3-1 — HOT/ICE 가 함께 적힌 사실을 규격별 두 사실로 나눈다 (원장 단계). 순수 함수, DB 없음.

D19 — 사실(source_facts)은 variant 로 갈라 저장한다. 추출 모델이 'HOT/ICE' 처럼 두 온도를 한
사실로 낸 경우, 값이 공통이라는 판단은 모델이 한 사실로 냈다는 점에 기댄다(설계 §6 위험).
  - 대상: entity_names.parse_variant 가 온도를 둘 다 읽은 사실(multi_temperature)
  - 결과: HOT 사실 + ICE 사실. 값·단위·부정·조건·예외·순서·근거·원문은 같고, 사이즈 등 나머지
    규격 낱말은 남긴다
  - local_ref: '<원래 ref>~HOT', '<원래 ref>~ICE'. 원장 local_ref 는 40자로 잘리므로 원래 ref 의
    앞 36자만 쓴다 — 잘려도 두 이름표가 갈린다
  - requires: 다른 사실이 원래 ref 를 가리키면 둘 다를 가리킨다. 가리키는 쪽도 갈라진 사실이면
    같은 온도 쪽만 가리킨다(HOT 절차가 ICE 선행에 매이지 않게)
  - 나눈 표시를 check_flags 에 남긴다(근거 위치 행으로 영속) — 원래 한 문장이었음을 검수에서 안다
  - 입력 객체는 바꾸지 않는다. 조립 입력과 복구 캐시가 같은 객체를 쓴다
  - 온도 외 규격(사이즈 둘 이상 등)은 나누지 않는다
pipeline._persist_ledger 가 w_entity_revision_enabled 일 때만 부른다. 나눌 사실이 없으면 같은
객체를 그대로 돌려주므로 원장 쓰기가 꺼짐과 같다.
"""
from __future__ import annotations

from app.ingest.entity_names import parse_variant, strip_temperature

SPLIT_SEPARATOR = "~"
TEMPERATURES = ("HOT", "ICE")
VERDICT_SPLIT = "VARIANT_SPLIT"
_LOCAL_REF_MAX = 40                                    # source_facts.local_ref 저장 길이
_BASE_MAX = _LOCAL_REF_MAX - len(SPLIT_SEPARATOR) - 3  # 36 — '~HOT'·'~ICE' 자리를 남긴다


def split_ref(ref: str, temperature: str) -> str:
    """갈라진 사실의 이름표. 원장 local_ref(40자) 안에서 HOT·ICE 가 갈린다."""
    return f"{ref[:_BASE_MAX]}{SPLIT_SEPARATOR}{temperature}"


def split_refs(ref: str) -> tuple[str, str]:
    """원래 ref 하나의 갈라진 이름표 둘 (HOT, ICE 순)."""
    return split_ref(ref, "HOT"), split_ref(ref, "ICE")


def needs_split(variant: str | None) -> bool:
    """규격 칸에 HOT 과 ICE 가 함께 적혔는가."""
    return parse_variant(variant).multi_temperature


def _rewrite(requires, split: set[str], temperature: str | None) -> list[str]:
    """선행 참조를 갈라진 이름표로 바꾼다. temperature 가 있으면 그 온도 쪽만 가리킨다."""
    out: list[str] = []
    for ref in requires:
        if ref not in split:
            out.append(ref)
        elif temperature is None:
            out.extend(split_refs(ref))
        else:
            out.append(split_ref(ref, temperature))
    return out


def split_hot_ice(assertions: list) -> list:
    """HOT/ICE 동시 사실을 둘로 나눈 새 목록. 나눌 사실이 없으면 같은 객체들을 그대로 담는다."""
    split = {a.local_ref for a in assertions if needs_split(a.variant)}
    if not split:
        return list(assertions)
    out = []
    for a in assertions:
        if a.local_ref not in split:
            requires = _rewrite(a.requires, split, None)
            if requires == list(a.requires):
                out.append(a)
            else:
                out.append(a.model_copy(deep=True, update={"requires": requires}))
            continue
        rest = strip_temperature(a.variant)
        for temperature in TEMPERATURES:
            copy = a.model_copy(deep=True, update={
                "local_ref": split_ref(a.local_ref, temperature),
                "variant": " ".join(part for part in (temperature, rest) if part),
                "requires": _rewrite(a.requires, split, temperature),
            })
            # deep copy 라 _check_flags 는 사본마다 따로다. 표시는 사본에만 붙는다
            copy.check_flags.append({
                "field": "variant", "verdict": VERDICT_SPLIT, "value": a.variant,
                "variant_split": "HOT_ICE", "from_ref": a.local_ref})
            out.append(copy)
    return out
```

- [ ] **Step 5: 파이프라인 연결** — `api/app/ingest/pipeline.py`

(a) import 블록(`:19-24`)의 `from app.ingest.schemas import ExtractionResult, ExtractedAssertion` 바로 위에 한 줄 추가:

```python
from app.ingest.variant_split import split_hot_ice, split_refs
```

(b) `_persist_ledger` 안, `s = get_settings()` 바로 다음(현재 `:936` 다음)에 추가:

```python
    if getattr(s, "w_entity_revision_enabled", False):
        # W3-0 §3-1 — HOT/ICE 가 함께 적힌 사실을 규격별 두 사실로 나눈다(D19).
        # 끄면 이 줄을 건너뛰어 원장 쓰기가 이전과 같다(D16). 반환 열쇠도 갈라진 이름표다
        assertions = split_hot_ice(assertions)
```

(c) `_persist` 바로 위(현재 `:1033` 앞)에 헬퍼 추가:

```python
def _ledger_keys(ledger: dict[str, int], ref: str) -> list[str]:
    """조립이 고른 ref 의 원장 열쇠. HOT/ICE 나누기(W3-0 §3-1)로 갈라진 사실이면 두 열쇠다.

    조립 모델은 나누기 전 사실 목록을 보므로 원래 ref 를 쓴다. 플래그가 꺼져 있으면
    갈라진 열쇠가 원장에 없으므로 이전과 같다(ref 가 있으면 그것 하나, 없으면 빈 목록).
    """
    if ref in ledger:
        return [ref]
    return [key for key in split_refs(ref) if key in ledger]
```

(d) `_persist` 안 `:1082-1083` 을 바꾼다:

```python
        refs = [f.ref for f in card.facts if getattr(f, "ref", "")]
        keys = [key for r in refs for key in _ledger_keys(ledger, r)]
        fact_ids = [ledger[key] for key in keys]
```

(e) `_persist` 안 `:1113-1114` 을 바꾼다:

```python
        linked_refs.update(keys)
        unmatched.extend(r for r in refs if r and not _ledger_keys(ledger, r))
```

(아래 `dropped` 계산은 `ledger.items()` 의 열쇠와 `linked_refs` 를 비교하므로 그대로 둔다 — 갈라진 열쇠가 `linked_refs` 에 들어가 버림으로 세지 않는다.)

- [ ] **Step 6: 통과 확인**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests/test_w3_variant_split.py tests/test_w2_ledger_wiring.py tests/test_w2_impact.py tests/test_fact_occurrences.py`
Expected: 모두 PASS (`test_w3_variant_split.py` 20건 포함).

- [ ] **Step 7: 전체 단위 테스트·매장 격리**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests`
Expected: `1755 passed, 4 xfailed` (기준 1735 + 20).
Run: `cd /Users/chabee/new/New_Source/2026unithon-w3 && python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest api/app/cards api/app/publish`
Expected: `위반 15건` (기존 repository.py 분만, 새 위반 0).

- [ ] **Step 8: 변경 확인, 커밋하지 않는다**

Run: `git -C /Users/chabee/new/New_Source/2026unithon-w3 status --short && git -C /Users/chabee/new/New_Source/2026unithon-w3 diff --stat`
Expected: `entity_names.py`·`pipeline.py` 수정, `variant_split.py`·`test_w3_variant_split.py` 새 파일. `git add`/`commit` 하지 않는다.

---

### Task 2: `import_legacy_correction` 적용 순서 (설계 §3-2)

**Files:**
- Modify: `api/app/ingest/fact_revisions.py:300-337`
- Test: `api/tests/test_w2_fact_revisions.py` (기존 `test_legacy_import_appends_revision_with_legacy_fields` 의 FakeConn 응답 보강 + 새 테스트를 그 뒤, `# ── 충돌 기각` 앞에 추가)

**Interfaces:**
- Consumes: `fact_revisions._lock_fact(conn, store_id, fact_id, expected_head_revision_id: int | None) -> asyncpg.Record`(`fact_id, entity_id, head_revision_id`), `fact_revision_meta(store_id, fact_revision_id, change_kind)`.
- Produces: `import_legacy_correction(conn, store_id: int, *, source_fact_id: int) -> int | None` — 서명 불변. 새 규칙: 이미 옮긴 판이 있으면 그 id(멱등, 기존 그대로). 그 밖에 잠근 사실의 head 판 메타 `change_kind` 가 `EXTRACTION` 이 아니면(메타가 없어 모르는 경우 포함) 아무것도 쓰지 않고 `None`, INFO 로그 `legacy 정정 건너뜀 …`.

- [ ] **Step 1: 실패하는 테스트 작성** — `api/tests/test_w2_fact_revisions.py`

(a) 기존 `test_legacy_import_appends_revision_with_legacy_fields` 의 `FakeConn(extra={...})` 에 head 종류 응답 한 줄을 더한다(지금 head 가 추출 판이어야 이관한다):

```python
    conn = FakeConn(extra={
        "from source_facts": dict(fact_id=5, corrected_value="25", corrected_at=at,
                                  corrected_by=ACTOR),
        "from source_fact_revision_links": FACT,
        "legacy_source_fact_id = $2": None,
        "select change_kind from fact_revision_meta": "EXTRACTION"})
```

(b) 그 테스트 바로 뒤에 추가:

```python
@pytest.mark.parametrize("head_kind", ["OWNER_CORRECTION", "OWNER_ANSWER", "RELINK",
                                       "LEGACY_CORRECTION", None])
@pytest.mark.asyncio
async def test_legacy_import_skips_when_head_is_not_extraction(head_kind, caplog):
    # W3-0 §3-2 — 점주 정정(등) 위에 더 오래된 corrected_value 를 새 head 로 얹지 않는다.
    # 메타가 없어 종류를 모르는 head(None)도 덮지 않는다
    conn = FakeConn(extra={
        "from source_facts": dict(fact_id=5, corrected_value="25", corrected_at=None,
                                  corrected_by=ACTOR),
        "from source_fact_revision_links": FACT,
        "legacy_source_fact_id = $2": None,
        "select change_kind from fact_revision_meta": head_kind})
    with caplog.at_level("INFO", logger="app.ingest.fact_revisions"):
        assert await fr.import_legacy_correction(conn, STORE, source_fact_id=5) is None
    assert not conn.sql("insert into")
    assert not conn.sql("update knowledge_facts")
    kind_query = conn.sql("select change_kind from fact_revision_meta")
    assert len(kind_query) == 1 and kind_query[0][2] == (STORE, HEAD)
    # head 확인은 사실 행을 잠근 뒤에 한다
    assert order_of(conn, "for update") < order_of(conn, "select change_kind")
    assert "legacy 정정 건너뜀" in caplog.text
```

- [ ] **Step 2: 실패 확인**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests/test_w2_fact_revisions.py -k legacy`
Expected: 새 파라미터 5건 FAIL — `assert 701 is None`(판을 얹음) 또는 `IndexError`/`len(kind_query) == 1` 실패. 기존 legacy 테스트 4건은 PASS.

- [ ] **Step 3: 최소 구현** — `api/app/ingest/fact_revisions.py` 의 `import_legacy_correction` 을 아래로 바꾼다(`:300-337`)

```python
async def import_legacy_correction(conn: asyncpg.Connection, store_id: int, *,
                                   source_fact_id: int) -> int | None:
    """source_facts.corrected_value 를 LEGACY_CORRECTION 판으로 옮긴다. 새(또는 이미 옮긴) 판 id.

    corrected_value 가 없거나 비었으면 None. 원장 사실이 아직 판에 이어지지 않았으면 None
    (판이 없는 사실은 옮기지 않는다). 이미 옮겼으면 그 판 id(멱등). 원장은 읽기만 한다.
    W3-0 §3-2 — 지금 head 가 추출 판(EXTRACTION)이 아니면(점주 정정·점주 답변·재연결·이관,
    또는 메타가 없어 모름) 더 오래된 corrected_value 를 그 위에 얹지 않고 None. 사유를 로그에 남긴다.
    """
    async with conn.transaction():
        await lock_store_knowledge(conn, store_id)
        ledger = await conn.fetchrow(
            "select fact_id, corrected_value, corrected_at, corrected_by "
            "from source_facts where store_id = $1 and fact_id = $2",
            store_id, source_fact_id)
        if ledger is None or not (ledger["corrected_value"] or "").strip():
            return None
        fact_id = await conn.fetchval(
            "select fact_id from source_fact_revision_links "
            "where store_id = $1 and source_fact_id = $2",
            store_id, source_fact_id)
        if fact_id is None:
            return None
        done = await conn.fetchval(
            "select fact_revision_id from fact_revision_meta "
            "where store_id = $1 and legacy_source_fact_id = $2",
            store_id, source_fact_id)
        if done is not None:
            return done
        # CAS 기대값은 지금의 head 다(잠근 행에서 읽는다)
        row = await _lock_fact(conn, store_id, fact_id, None)
        head_kind = await conn.fetchval(
            "select change_kind from fact_revision_meta "
            "where store_id = $1 and fact_revision_id = $2",
            store_id, row["head_revision_id"])
        if head_kind != "EXTRACTION":
            log.info("legacy 정정 건너뜀 store=%s source_fact=%s fact=%s head=%s(%s) — "
                     "추출 판이 아닌 head 위에 옛 corrected_value 를 얹지 않는다",
                     store_id, source_fact_id, fact_id, row["head_revision_id"], head_kind)
            return None
        head, variant_other = await _head_of(conn, store_id, row["head_revision_id"])
        corrected = ledger["corrected_value"]
        shape = _apply_change(head, variant_other,
                              FactChange(value=corrected, original_assertion=corrected))
        return await _append_revision(
            conn, store_id, knowledge_fact_row=row, shape=shape, entity_id=row["entity_id"],
            change_kind="LEGACY_CORRECTION", actor_id=ledger["corrected_by"],
            reason=_LEGACY_REASON, legacy_source_fact_id=source_fact_id,
            applied_at=ledger["corrected_at"])
```

- [ ] **Step 4: 통과 확인**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests/test_w2_fact_revisions.py`
Expected: 전부 PASS.

- [ ] **Step 5: 전체 단위 테스트·매장 격리**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests`
Expected: `1760 passed, 4 xfailed` (1755 + 5).
Run: 매장 격리 검사(Global 명령). Expected: `위반 15건`.

(실제 DB V3 시나리오 — 추출 판 위의 이관은 그대로 1판·멱등 — 는 Task 3 Step 9 의 재구축 실행에서 함께 확인된다. `_scenario_revisions` V3 는 `revise_fact` 로 정정하지 않은 `f30` 사실에 이관하므로 head 가 EXTRACTION 이다.)

- [ ] **Step 6: 변경 확인, 커밋하지 않는다**

Run: `git -C /Users/chabee/new/New_Source/2026unithon-w3 status --short && git -C /Users/chabee/new/New_Source/2026unithon-w3 diff --stat`
Expected: `fact_revisions.py`, `test_w2_fact_revisions.py` 추가 변경. 커밋하지 않는다.

---

### Task 3: 병합 정리 — 후보 옮기기·닫기, 제안 옮기기, 같은 순위 `matched_cards` 갱신 (설계 §3-3)

**Files:**
- Create: `supabase/migrations/20261007090000_w_merge_cleanup_states.sql`
- Modify: `api/app/ingest/entity_admin.py` (헬퍼 `_as_object`·`_rehome_candidates` 를 `merge_entities` 앞 `:216` 에 추가, `merge_entities` `:218-287` 의 MERGE 이력 `:281-284` 뒤에서 호출, docstring)
- Modify: `api/app/ingest/impact.py:22` (import), `:186-299` (`record_upload_proposals`), 새 헬퍼 `_adopt_merged_proposals` 를 `record_upload_proposals` 앞(`:184` 의 `_RANK` 다음)에
- Test: `api/tests/test_w2_entity_admin.py` (merge 절 끝 `:405` 뒤), `api/tests/test_w2_impact.py` (`_ProposalConn` `:189-211` 보강, 파일 끝에 새 테스트)

**Interfaces:**
- Consumes: `entities._follow_merged(conn, store_id: int, entity_id: int) -> int`, `entities.lock_store_knowledge(conn, store_id)`, `entity_admin._event(conn, store_id, action, *, entity_id, other_entity_id=None, fact_id=None, fact_revision_id=None, actor_id, payload: dict)`, `entity_admin._json(value) -> str`.
- Produces:
  - `entity_admin._as_object(value) -> dict`
  - `entity_admin._rehome_candidates(conn, store_id: int, *, keep_entity_id: int, merged_entity_id: int, actor_id: int) -> None`
  - `impact._adopt_merged_proposals(conn, store_id: int, source_id: int) -> int` (살펴본 병합된 대상 PENDING 제안 수)
  - `merge_entities(...)`·`record_upload_proposals(...)` 서명 불변.
- 새 DB 값: `knowledge_entity_candidates.status = 'MERGED'`(병합으로 닫힘, `decided_by`=병합한 사람, `evidence` 에 `merged_into_entity_id`·`replaced_by_candidate_id` 덧붙임), `knowledge_entity_events.action ∈ {'CANDIDATE_MOVED', 'PROPOSAL_MOVED'}`. 이력 payload:
  - `CANDIDATE_MOVED`: `entity_id`=keep, `other_entity_id`=제3 대상, payload `{"from_candidate_id", "to_candidate_id" (없으면 null), "merged_entity_id", "outcome": "MOVED"|"CLOSED"}`
  - `PROPOSAL_MOVED`: `entity_id`=살아 있는 대상, `other_entity_id`=병합된 대상, payload `{"proposal_id", "source_id", "outcome": "MOVED"|"SUPERSEDED", "into_proposal_id" (없으면 null)}`

결정(명세 보완): 살아 있는 대상에 같은 자료의 제안이 이미 있으면 `unique (store_id, source_id, entity_id)` 때문에 옮길 수 없으므로 옛 PENDING 제안을 `SUPERSEDED` 로 닫는다. 결정된 제안(ACCEPTED·DISMISSED·SUPERSEDED)은 건드리지 않는다(결정 J). 같은 순위 갱신은 `matched_cards` 가 실제로 달라졌을 때만 한다 — 같은 값 재처리는 `updated_at` 도 그대로(기존 실제 DB P4 "updated_at 포함 불변" 유지).

- [ ] **Step 1: migration 작성** — `supabase/migrations/20261007090000_w_merge_cleanup_states.sql`

```sql
-- W3-0 §3-3 — 대상 병합 뒤 정리 상태·이력 어휘를 더한다.
--
-- 규칙:
--   1. 가산 migration 이다. 기존 CHECK 의 허용 값을 넓히기만 한다. 기존 행·값·다른 제약은 그대로다.
--      제약 이름은 20260930090000_w_knowledge_entities.sql 의 열 CHECK 가 받은 기본 이름이다.
--   2. knowledge_entity_candidates.status 'MERGED' — 병합된 대상이 낀 PENDING 후보를 merge_entities 가
--      닫을 때 쓴다(점주의 '기각'·'다른 대상' 결정과 구별한다). decided_at·decided_by 가 함께 찬다.
--   3. knowledge_entity_events.action 'CANDIDATE_MOVED'(후보를 남은 대상 쪽으로 옮기거나 닫음),
--      'PROPOSAL_MOVED'(병합된 대상의 PENDING 업로드 제안을 살아 있는 대상으로 옮기거나 SUPERSEDED).
--      이력은 그대로 append-only 다.

begin;

alter table knowledge_entity_candidates
  drop constraint if exists knowledge_entity_candidates_status_check;
alter table knowledge_entity_candidates
  add constraint knowledge_entity_candidates_status_check
  check (status in ('PENDING', 'CONFIRMED_SAME', 'CONFIRMED_DIFFERENT', 'DISMISSED', 'MERGED'));

alter table knowledge_entity_events
  drop constraint if exists knowledge_entity_events_action_check;
alter table knowledge_entity_events
  add constraint knowledge_entity_events_action_check
  check (action in ('CREATE', 'ALIAS_ADD', 'ALIAS_RETIRE', 'MERGE', 'SPLIT', 'RELINK_FACT',
                    'CANDIDATE_DECIDED', 'CANDIDATE_MOVED', 'PROPOSAL_MOVED'));

comment on column knowledge_entity_candidates.status is
  'PENDING · CONFIRMED_SAME · CONFIRMED_DIFFERENT · DISMISSED · MERGED(병합된 대상이 끼어 merge_entities 가 닫음, W3-0)';

commit;
```

- [ ] **Step 2: 실패하는 테스트 작성 — 병합 후보 정리** — `api/tests/test_w2_entity_admin.py`, `test_merge_relinks_moves_aliases_marks_merged_and_confirms_candidate` 뒤(`:405` 뒤)에 추가

```python
@pytest.mark.asyncio
async def test_merge_moves_or_closes_pending_candidates_of_the_merged_entity():
    # W3-0 §3-3-1 — (병합된 대상, 제3 대상) PENDING 후보를 남기지 않는다
    third_new, third_dup = 30, 31
    pending = [
        dict(candidate_id=81, entity_id_low=GONE, entity_id_high=third_new, reason="EDIT1",
             evidence='{"reason": "EDIT1"}'),
        dict(candidate_id=82, entity_id_low=GONE, entity_id_high=third_dup, reason="CONTAINS",
             evidence={"reason": "CONTAINS"}),
    ]
    conn = _merge_conn(**{
        "and status = 'PENDING' and $2 in (entity_id_low, entity_id_high)": pending,
        # keep 과 third_dup 사이에는 이미 후보가 있다 → 새로 만들지 못한다(None)
        "insert into knowledge_entity_candidates":
            lambda args: 90 if args[2] == third_new else None,
    })
    await _merge(conn)
    query = conn.sql("$2 in (entity_id_low, entity_id_high)")[0]
    assert query[2] == (STORE, GONE, KEEP) and "for update" in query[1]
    inserts = [c[2] for c in conn.sql("insert into knowledge_entity_candidates")]
    assert [a[:4] for a in inserts] == [(STORE, KEEP, third_new, "EDIT1"),
                                        (STORE, KEEP, third_dup, "CONTAINS")]
    assert json.loads(inserts[0][4]) == {"reason": "EDIT1", "moved_from_candidate_id": 81,
                                         "merged_entity_id": GONE}
    closes = conn.sql("update knowledge_entity_candidates set status = 'MERGED'")
    assert [c[2][:3] for c in closes] == [(STORE, 81, ACTOR), (STORE, 82, ACTOR)]
    assert all("status = 'PENDING'" in c[1] for c in closes)
    assert [json.loads(c[2][3]) for c in closes] == [
        {"merged_into_entity_id": KEEP, "replaced_by_candidate_id": 90},
        {"merged_into_entity_id": KEEP, "replaced_by_candidate_id": None}]
    actions = [e[1] for e in _events(conn)]
    assert actions[-3:] == ["MERGE", "CANDIDATE_MOVED", "CANDIDATE_MOVED"]
    moved = [e for e in _events(conn) if e[1] == "CANDIDATE_MOVED"]
    assert [e[2:4] for e in moved] == [(KEEP, third_new), (KEEP, third_dup)]
    assert [json.loads(e[-1]) for e in moved] == [
        {"from_candidate_id": 81, "to_candidate_id": 90, "merged_entity_id": GONE,
         "outcome": "MOVED"},
        {"from_candidate_id": 82, "to_candidate_id": None, "merged_entity_id": GONE,
         "outcome": "CLOSED"}]
```

- [ ] **Step 3: 실패하는 테스트 작성 — 제안 옮기기·같은 순위** — `api/tests/test_w2_impact.py`

(a) `_ProposalConn`(`:189-211`)을 아래로 바꾼다(병합 사슬 조회와 병합된 대상 제안 조회에 답한다):

```python
class _ProposalConn:
    """record_upload_proposals 가 부르는 조회를 문장 조각으로 흉내 낸다."""

    def __init__(self, status, merged_into=None):
        self.status = status
        self.merged_into = merged_into or {}   # 병합된 대상 → 살아남은 대상
        self.writes: list[tuple[str, tuple]] = []

    async def fetch(self, query, *args):
        if "e.status = 'MERGED'" in query:
            return []   # 병합된 대상 아래 PENDING 제안 없음
        if "from source_fact_revision_links l" in query and "sf.source_id" in query:
            return [{"fact_id": 70, "fact_revision_id": 700, "link_kind": "CREATED",
                     "entity_id": 5}]
        if "from knowledge_cards" in query:
            return [{"card_id": 9, "review_status": "APPROVED", "published_version_id": 90}]
        if "from fact_conflicts" in query:
            return [{"fact_id_low": 70, "fact_id_high": 71}]
        if "join card_facts" in query:
            return [{"fact_id": 71, "card_id": 9}]
        raise AssertionError(query)

    async def fetchrow(self, query, *args):
        if "from knowledge_entities" in query:
            # _follow_merged — (store_id, entity_id)
            target = self.merged_into.get(args[1])
            if target is not None:
                return {"status": "MERGED", "merged_into_entity_id": target}
            return {"status": "ACTIVE", "merged_into_entity_id": None}
        assert "from upload_change_proposals" in query and "store_id = $1" in query
        return {"proposal_id": 40, "status": self.status}

    async def execute(self, query, *args):
        self.writes.append((query, args))
        return "INSERT 0 1"
```

(b) 파일 끝에 추가:

```python
# ── W3-0 §3-3 — 병합 뒤 제안 정리·같은 순위 갱신 ─────────────────────────────

async def _record_with(conn):
    affected = impact.AffectedCards(card_ids=(9,), by_fact_revision={700: (9,)})
    with patch.object(impact, "lock_store_knowledge", AsyncMock()), \
         patch.object(impact, "affected_cards", AsyncMock(return_value=affected)):
        await impact.record_upload_proposals(conn, 3, 8, job_id=None)


@pytest.mark.asyncio
async def test_proposals_group_by_the_live_entity_after_merge():
    conn = _ProposalConn("PENDING_REVIEW", merged_into={5: 12})
    await _record_with(conn)
    heads = [a for q, a in conn.writes if "insert into upload_change_proposals as p" in q]
    assert len(heads) == 1 and heads[0][3] == 12


@pytest.mark.asyncio
async def test_upsert_refreshes_matched_cards_on_same_rank_only_when_changed():
    conn = _ProposalConn("PENDING_REVIEW")
    await _record_with(conn)
    sql = next(q for q, _ in conn.writes if "insert into upload_change_proposals as p" in q)
    assert "where p.status = 'PENDING_REVIEW'" in sql
    assert (f"array_position({impact._RANK}, excluded.relation_type) "
            f"> array_position({impact._RANK}, p.relation_type)") in sql
    assert (f"array_position({impact._RANK}, excluded.relation_type) "
            f"= array_position({impact._RANK}, p.relation_type)") in sql
    assert "p.matched_cards is distinct from excluded.matched_cards" in sql


class _AdoptConn:
    """병합된 대상(9 → 12) 아래 PENDING 제안 41 하나. taken 은 살아 있는 대상의 같은 자료 제안."""

    def __init__(self, taken):
        self.taken = taken
        self.writes: list[tuple[str, tuple]] = []

    async def fetch(self, query, *args):
        assert ("p.status = 'PENDING_REVIEW'" in query and "e.status = 'MERGED'" in query
                and "p.store_id = $1" in query and args == (3, 8))
        return [{"proposal_id": 41, "entity_id": 9}]

    async def fetchrow(self, query, *args):
        assert "from knowledge_entities" in query and args[0] == 3
        if args[1] == 9:
            return {"status": "MERGED", "merged_into_entity_id": 12}
        return {"status": "ACTIVE", "merged_into_entity_id": None}

    async def fetchval(self, query, *args):
        assert "from upload_change_proposals" in query and args == (3, 8, 12)
        return self.taken

    async def execute(self, query, *args):
        self.writes.append((query, args))
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_pending_proposal_of_merged_entity_moves_to_live_entity():
    conn = _AdoptConn(taken=None)
    assert await impact._adopt_merged_proposals(conn, 3, 8) == 1
    updates = [(q, a) for q, a in conn.writes if q.startswith("update upload_change_proposals")]
    assert len(updates) == 1 and "set entity_id = $3" in updates[0][0]
    assert "status = 'PENDING_REVIEW'" in updates[0][0] and updates[0][1] == (3, 41, 12)
    events = [a for q, a in conn.writes if "insert into knowledge_entity_events" in q]
    assert len(events) == 1 and events[0][:3] == (3, 12, 9)
    assert json.loads(events[0][3]) == {"proposal_id": 41, "source_id": 8, "outcome": "MOVED",
                                        "into_proposal_id": None}


@pytest.mark.asyncio
async def test_pending_proposal_of_merged_entity_is_superseded_when_live_one_exists():
    conn = _AdoptConn(taken=40)
    await impact._adopt_merged_proposals(conn, 3, 8)
    updates = [(q, a) for q, a in conn.writes if q.startswith("update upload_change_proposals")]
    assert len(updates) == 1 and "status = 'SUPERSEDED'" in updates[0][0]
    assert "status = 'PENDING_REVIEW'" in updates[0][0] and updates[0][1] == (3, 41)
    assert not any("set entity_id" in q for q, _ in conn.writes)
    events = [a for q, a in conn.writes if "insert into knowledge_entity_events" in q]
    assert json.loads(events[0][3]) == {"proposal_id": 41, "source_id": 8,
                                        "outcome": "SUPERSEDED", "into_proposal_id": 40}
```

그리고 파일 맨 위 import 에 `import json` 을 더한다(`import inspect` 앞).

- [ ] **Step 4: 실패 확인**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests/test_w2_entity_admin.py tests/test_w2_impact.py`
Expected: 새 테스트 5건 FAIL — `test_merge_moves_or_closes…`(후보 조회 없음 → `IndexError`), `test_proposals_group_by_the_live_entity_after_merge`(`heads[0][3] == 5`), `test_upsert_refreshes…`(`= array_position` 없음), `_adopt_merged_proposals` 두 건(`AttributeError: module 'app.ingest.impact' has no attribute '_adopt_merged_proposals'`). 기존 테스트는 PASS(가짜 연결 보강 후에도).

- [ ] **Step 5: 최소 구현 — `entity_admin.py`**

(a) `merge_entities` 정의 앞(`:216`)에 추가:

```python
def _as_object(value) -> dict:
    """jsonb 객체(문자열로 올 수 있다)를 dict 로."""
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value) if value.strip() else {}
    return dict(value)


async def _rehome_candidates(conn: asyncpg.Connection, store_id: int, *, keep_entity_id: int,
                             merged_entity_id: int, actor_id: int) -> None:
    """병합된 대상이 낀 (병합된 대상, 제3 대상) PENDING 후보를 정리한다 (W3-0 §3-3-1).

    keep 과 제3 대상 사이에 후보가 없으면 같은 이유·근거로 keep 쪽 PENDING 후보를 새로 만들고,
    이미 있으면(상태 무관 — 결정된 쌍은 다시 열지 않는다) 만들지 않는다. 어느 쪽이든 옛 후보는
    MERGED 로 닫고 이력 CANDIDATE_MOVED 를 남긴다.
    호출 전 조건: 같은 트랜잭션에서 매장 잠금을 잡았고 merged 는 이미 MERGED 다.
    """
    rows = await conn.fetch(
        "select candidate_id, entity_id_low, entity_id_high, reason, evidence "
        "from knowledge_entity_candidates "
        "where store_id = $1 and status = 'PENDING' and $2 in (entity_id_low, entity_id_high) "
        "and $3 not in (entity_id_low, entity_id_high) "
        "order by candidate_id for update",
        store_id, merged_entity_id, keep_entity_id)
    for row in rows:
        third = (row["entity_id_high"] if row["entity_id_low"] == merged_entity_id
                 else row["entity_id_low"])
        low, high = sorted((keep_entity_id, third))
        evidence = _as_object(row["evidence"]) | {
            "moved_from_candidate_id": row["candidate_id"], "merged_entity_id": merged_entity_id}
        new_id = await conn.fetchval(
            "insert into knowledge_entity_candidates "
            "(store_id, entity_id_low, entity_id_high, reason, evidence) "
            "values ($1, $2, $3, $4, $5::jsonb) "
            "on conflict (store_id, entity_id_low, entity_id_high) do nothing "
            "returning candidate_id",
            store_id, low, high, row["reason"], _json(evidence))
        await conn.execute(
            "update knowledge_entity_candidates set status = 'MERGED', decided_by = $3, "
            "decided_at = now(), evidence = evidence || $4::jsonb "
            "where store_id = $1 and candidate_id = $2 and status = 'PENDING'",
            store_id, row["candidate_id"], actor_id,
            _json({"merged_into_entity_id": keep_entity_id, "replaced_by_candidate_id": new_id}))
        await _event(conn, store_id, "CANDIDATE_MOVED", entity_id=keep_entity_id,
                     other_entity_id=third, actor_id=actor_id,
                     payload={"from_candidate_id": row["candidate_id"], "to_candidate_id": new_id,
                              "merged_entity_id": merged_entity_id,
                              "outcome": "MOVED" if new_id is not None else "CLOSED"})
```

(b) `merge_entities` 안, `await _event(conn, store_id, "MERGE", …)` 호출(`:281-284`) 바로 뒤, `async with` 블록 안에 추가:

```python
        # W3-0 §3-3-1 — 병합된 대상이 낀 다른 PENDING 후보를 keep 쪽으로 옮기거나 닫는다
        await _rehome_candidates(conn, store_id, keep_entity_id=keep_entity_id,
                                 merged_entity_id=merged_entity_id, actor_id=actor_id)
```

(c) `merge_entities` docstring 끝에 한 문장 추가: `병합된 대상이 낀 다른 PENDING 후보는 keep 쪽으로 옮기거나(같은 쌍이 이미 있으면) MERGED 로 닫는다(W3-0).`

- [ ] **Step 6: 최소 구현 — `impact.py`**

(a) `:22` import 를 바꾼다:

```python
from app.ingest.entities import _follow_merged, lock_store_knowledge
```

(b) `_RANK` 정의(`:183`) 다음, `record_upload_proposals` 앞에 추가:

```python
async def _adopt_merged_proposals(conn: asyncpg.Connection, store_id: int,
                                  source_id: int) -> int:
    """병합된 대상 아래 이 자료의 PENDING_REVIEW 제안을 살아 있는 대상으로 옮긴다 (W3-0 §3-3-2).

    살아 있는 대상(병합 사슬 끝)에 이 자료의 제안이 아직 없으면 그 제안의 entity_id 를 바꾼다
    (proposal_id·항목 그대로). 이미 있으면 unique(store, source, entity) 때문에 옮길 수 없으므로
    옛 제안을 SUPERSEDED 로 닫는다. 결정된 제안은 건드리지 않는다(결정 J).
    어느 쪽이든 대상 이력 PROPOSAL_MOVED 를 남긴다. 살펴본 제안 수를 돌려준다.
    호출 전 조건: 같은 트랜잭션에서 매장 잠금을 잡았다.
    """
    rows = await conn.fetch(
        "select p.proposal_id, p.entity_id from upload_change_proposals p "
        "join knowledge_entities e on e.store_id = p.store_id and e.entity_id = p.entity_id "
        "where p.store_id = $1 and p.source_id = $2 and p.status = 'PENDING_REVIEW' "
        "and e.status = 'MERGED' "
        "order by p.proposal_id",
        store_id, source_id)
    for row in rows:
        live = await _follow_merged(conn, store_id, row["entity_id"])
        taken = await conn.fetchval(
            "select proposal_id from upload_change_proposals "
            "where store_id = $1 and source_id = $2 and entity_id = $3",
            store_id, source_id, live)
        if taken is None:
            await conn.execute(
                "update upload_change_proposals set entity_id = $3, updated_at = now() "
                "where store_id = $1 and proposal_id = $2 and status = 'PENDING_REVIEW'",
                store_id, row["proposal_id"], live)
            outcome = "MOVED"
        else:
            await conn.execute(
                "update upload_change_proposals set status = 'SUPERSEDED', decided_at = now(), "
                "updated_at = now() "
                "where store_id = $1 and proposal_id = $2 and status = 'PENDING_REVIEW'",
                store_id, row["proposal_id"])
            outcome = "SUPERSEDED"
        await conn.execute(
            "insert into knowledge_entity_events "
            "(store_id, action, entity_id, other_entity_id, payload) "
            "values ($1, 'PROPOSAL_MOVED', $2, $3, $4::jsonb)",
            store_id, live, row["entity_id"],
            json.dumps({"proposal_id": row["proposal_id"], "source_id": source_id,
                        "outcome": outcome, "into_proposal_id": taken}, ensure_ascii=False))
        log.info("W3-0 제안 정리 store=%s source=%s proposal=%s 대상 %s → %s (%s)",
                 store_id, source_id, row["proposal_id"], row["entity_id"], live, outcome)
    return len(rows)
```

(c) `record_upload_proposals` 안:

- `await lock_store_knowledge(conn, store_id)`(`:194`) 바로 다음에 추가:

```python
    # W3-0 §3-3-2 — 병합된 대상 아래 PENDING 제안을 먼저 살아 있는 대상으로 옮긴다
    await _adopt_merged_proposals(conn, store_id, source_id)
```

- `if not links: return 0` 다음, `fact_of: dict[int, int] = {}` 앞에 추가:

```python
    # W3-0 §3-3-2 — 대상은 병합 사슬 끝(살아 있는 대상)으로 묶는다
    live_of: dict[int, int] = {}
    for entity_id in sorted({link["entity_id"] for link in links}):
        live_of[entity_id] = await _follow_merged(conn, store_id, entity_id)
```

- 루프 안 `entity_of[link["fact_revision_id"]] = link["entity_id"]`(`:211`)를 바꾼다:

```python
        entity_of[link["fact_revision_id"]] = live_of[link["entity_id"]]
```

- 머리 upsert 의 조건(`:270-273`, `"where p.status = 'PENDING_REVIEW' "` 부터 `> array_position(...)"` 까지)을 바꾼다:

```python
            "where p.status = 'PENDING_REVIEW' and ("
            f"array_position({_RANK}, excluded.relation_type) "
            f"> array_position({_RANK}, p.relation_type) "
            f"or (array_position({_RANK}, excluded.relation_type) "
            f"= array_position({_RANK}, p.relation_type) "
            "and p.matched_cards is distinct from excluded.matched_cards))",
```

- docstring 첫 문단의 "머리는 PENDING_REVIEW 이고 더 강한 관계일 때만 관계·영향 카드를 올린다." 를 다음으로 바꾼다: `머리는 PENDING_REVIEW 이고 더 강한 관계일 때 관계·영향 카드를 올리며, 같은 관계면 영향 카드(matched_cards)가 달라졌을 때만 새 계산으로 바꾼다(W3-0 §3-3-3). 병합된 대상 아래 PENDING 제안은 먼저 살아 있는 대상으로 옮기고, 대상은 병합 사슬 끝으로 묶는다(W3-0 §3-3-2).`

- [ ] **Step 7: 통과 확인**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests/test_w2_entity_admin.py tests/test_w2_impact.py`
Expected: 전부 PASS.

- [ ] **Step 8: 전체 단위 테스트·매장 격리**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests`
Expected: `1765 passed, 4 xfailed` (1760 + 5).
Run: 매장 격리 검사. Expected: `위반 15건`.
그리고 저장소 스킬 `store-isolation-check` 를 실행한다(`api/app/`·`supabase/migrations/` 를 건드렸다). 스킬이 요구하는 migration 절차 확인 결과를 보고에 적는다.

- [ ] **Step 9: 실제 DB 재구축 — 새 migration 과 기존 W2 검증이 그대로 통과**

Run: Global 의 docker run → `verify_r_schema_rebuild.py` → docker stop.
Expected: `PASS migration 20261007090000_w_merge_cleanup_states.sql` 이 보이고, 마지막까지 예외 없이 끝난다(`PASS W entity revision all scenarios` 포함 — V3 legacy 이관, P4 "updated_at 포함 불변", P7, S2 병합 이력 payload 그대로).

- [ ] **Step 10: 변경 확인, 커밋하지 않는다**

Run: `git -C /Users/chabee/new/New_Source/2026unithon-w3 status --short && git -C /Users/chabee/new/New_Source/2026unithon-w3 diff --stat`
Expected: migration 새 파일, `entity_admin.py`·`impact.py`·두 테스트 파일 변경. 커밋하지 않는다.

---

### Task 4: 두 플래그를 켠 합성 종단 검증 (설계 §3-6) + 점주 답변 삭제 경로 확인 기록 (설계 §3-4)

**Files:**
- Create: `api/scripts/verify_w3_flag_readiness.py`
- Modify: `api/scripts/verify_w_entity_revision.py:1-80` (docstring 끝에 한 단락), `:1700-1709` (`verify()` 끝에서 호출)
- Modify: `docs/dev/plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md` ("R 이 할 일" 8번, 현재 `:262`)
- Modify: `docs/dev/plan/W_NEXT_PLAN_20260928.md` ("플래그 켜기 전 점검" 의 `owner_answer_id` 줄, 현재 `:265`)

**Interfaces:**
- Consumes: `verify_w_entity_revision._MODEL_SETTINGS, _VECTOR, _card_rows(db, store, card_ids) -> dict, _checker(prefix) -> check, _fact(ref, subject, attribute, value, unit="", *, variant="", order=0, ts=0, requires=()) -> dict, _proposal_rows(db, store) -> dict, _published_fingerprint(db, store) -> dict, _rows_text(db, table, key, store) -> dict, _w2_counts(db, store) -> dict`, `verify_w_partial_extraction._seed(db) -> (user, store, job)`, `_new_source(db, store, user, source_type) -> int`, `pipeline.process_source(store, source, *, job_id, run_tag)`, `entities.find_entity_by_alias(conn, store_id, alias_norm) -> int | None`, `entities.list_candidates(conn, store_id, *, status="PENDING")`, `entity_names.normalize_alias(raw) -> str`, `entity_admin.merge_entities(conn, store_id, *, keep_entity_id, merged_entity_id, actor_id, candidate_id)`, `entity_admin.split_entity(conn, store_id, *, entity_id, fact_ids, new_canonical_name, move_alias_norms, actor_id) -> int`, `fact_ledger.list_open_conflicts(conn, store_id, *, entity_id) -> list[dict]`, `fact_revisions.revise_fact(...)`, `fact_revisions.import_legacy_correction(...)`, `publish.approval.publish_cards(pool, *, store_id, member_id, actor_user_id, changes, idempotency_key, usage_context)`, `CardChange(card_id, expected_draft, publish_version)`.
- Produces: `verify_w3_flag_readiness.verify(db: asyncpg.Connection, dsn: str) -> None` — 실패하면 `AssertionError(<검사 이름>)`, 통과하면 `PASS W entity W3-0 T<n> …` 줄과 끝에 `PASS W3-0 flag readiness all scenarios`.

시나리오 실행 순서는 의존 때문에 T1 → T4 → T2 → T3 → T5 → T6 → T7 → T8 이다(A 재처리 중복 확인은 다른 자료가 A 대상의 영향 카드를 바꾸기 전에 해야 항목 행 비교가 의미 있다). 번호는 설계 §3-6 의 번호를 그대로 쓴다.

- [ ] **Step 1: 종단 검증 스크립트 작성** — `api/scripts/verify_w3_flag_readiness.py`

```python
"""실제 DB: W3-0 — 두 W2 플래그를 켠 합성 종단 검증 (설계 §3-6). 모델은 합성 대역, 비용 0.

verify_w_entity_revision.verify() 끝에서 부른다(verify_r_schema_rebuild 가 부르는 W 검증).
한 합성 매장에서 차례로(번호는 설계 §3-6):
  T1 자료 A(영상 구간 2개, 동시 2) → 대상·판·occurrence·제안·같은 대상 후보
  T4 A 재처리 → W2 표 행 수·제안 머리·항목 그대로(중복 없음)
  T2 자료 B 의 HOT/ICE 동시 사실 → 원장·판 규격별 두 사실, 같은 자리 occurrence 둘, 나눔 표시,
     선행 관계는 갈라진 둘 다, 조립 ref 로 카드가 둘 다 잇고 LINKED
  T3 자료 C 의 다른 값 → 충돌 양쪽 보존·기본 선택 없음. A 카드 승인 뒤 재처리 → CONFLICT,
     matched_cards 를 지운 뒤 같은 순위 재처리 → 새 계산으로 갱신(§3-3-3)
  T5 대상 병합 → 후보 옮김·닫음(§3-3-1), 병합 뒤 재처리 → 제안 옮김·SUPERSEDED·중복 없음,
     결정된 제안 그대로(§3-3-2)
  T6 대상 분리 → 이력 SPLIT, 공개본·카드 행·제안 그대로
  T7 점주 정정 → 새 head, 옛 이관 정정은 그 위에 얹히지 않음(§3-2)
  T8 플래그를 끈 뒤 처리 → 새 W2 행·제안·후보·이력 없음, HOT/ICE 는 나누지 않음
"""
import json
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import asyncpg

import app.config
from app.config import Settings
from app.ingest import extract, pipeline
from app.ingest import repository as repo
from app.ingest.extract import gemini
from app.ingest.schemas import (ExtractedCard, ExtractedFact, ExtractionResult,
                                FactExtractionResult)
from verify_w_entity_revision import (_MODEL_SETTINGS, _VECTOR, _card_rows, _checker, _fact,
                                      _proposal_rows, _published_fingerprint, _rows_text,
                                      _w2_counts)
from verify_w_partial_extraction import _new_source, _seed

# 합성 대상 이름. A·B·C 는 서로 한 글자 차이(EDIT1), B1 은 B 와만 한 글자 차이다
A, B, C, D = "합성음료A", "합성음료B", "합성음료C", "합성음료B1"


async def _process(db, pool, store, user, source, parts, *, run_tag, flags=True):
    """process_source 를 합성 모델 대역으로 돌린다. parts = [(구간 글, 사실 목록)].

    parts 가 둘 이상이면 구간으로 나눠 동시에 2개씩 뽑는다. 하나면 구간 없는 자료다.
    조립 대역은 주어(subject)마다 카드 하나를 만들고, 나누기 전 이름표(seg1:f1·f1)를 인용한다.
    """
    job_id = await db.fetchval(
        "insert into ingest_jobs (store_id, created_by, title, status, category_version, "
        "prompt_version) values ($1,$2,'W3-0 종단 검증','EXTRACTING',1,'v1') returning job_id",
        store, user)
    await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                     store, source)
    await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                     "values($1,$2,$3,'QUEUED')", store, job_id, source)
    category = next(iter(await repo.enabled_categories(db, store)))
    segmented = len(parts) > 1
    cited = [(f"seg{index}:{f['local_ref']}" if segmented else f["local_ref"], f)
             for index, (_, facts) in enumerate(parts, start=1) for f in facts]

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        if schema is not None and issubclass(schema, FactExtractionResult):
            facts = next(f for text, f in parts if text in prompt)
            body = FactExtractionResult.model_validate({"assertions": facts})
            return gemini.CallResult(body.model_dump_json(), {}, "STOP")
        by_subject: dict[str, list[ExtractedFact]] = {}
        for ref, f in cited:
            by_subject.setdefault(f["subject"], []).append(ExtractedFact(
                object_name=f["subject"], attribute=f["attribute"], value=f["value"],
                confidence=.9, ref=ref))
        cards = [ExtractedCard(category_name=category, title=subject, content="합성 카드",
                               confidence=.9, facts=facts)
                 for subject, facts in by_subject.items()]
        return gemini.CallResult(ExtractionResult(cards=cards).model_dump_json(), {}, "STOP")

    if segmented:
        preprocessed = ("합성 자료 본문", [], [(text, []) for text, _ in parts])
    else:
        preprocessed = (parts[0][0], [], [])
    settings = Settings(_env_file=None, w_entity_revision_enabled=flags,
                        w_upload_proposals_enabled=flags, extract_segment_concurrency=2)
    with ExitStack() as stack:
        for obj, name, replacement in [
            (pipeline, "get_pool", lambda: pool),
            (pipeline, "_preprocess", AsyncMock(return_value=preprocessed)),
            (pipeline.shutil, "rmtree", lambda *a, **kw: None),
            (app.config, "get_settings", lambda: settings),
            (extract, "get_settings", lambda: NS(ingest_mode="real")),
            (gemini, "get_settings", lambda: _MODEL_SETTINGS),
            (gemini, "_call", fake_call),
        ]:
            stack.enter_context(patch.object(obj, name, replacement))
        await pipeline.process_source(store, source, job_id=job_id, run_tag=run_tag)
    state = await db.fetchrow("select status, error_message from sources "
                              "where store_id=$1 and source_id=$2", store, source)
    assert state["status"] == "DONE", f"처리 실패: {state['status']} {state['error_message']}"


async def verify(db, dsn) -> None:
    from app.contracts.usage import UsageContext
    from app.ingest.entities import find_entity_by_alias, list_candidates
    from app.ingest.entity_admin import merge_entities, split_entity
    from app.ingest.entity_names import normalize_alias
    from app.ingest.fact_ledger import list_open_conflicts
    from app.ingest.fact_revisions import FactChange, import_legacy_correction, revise_fact
    from app.publish.approval import CardChange, publish_cards

    async def fake_embedder(texts, *, context, sink=None):
        return [list(_VECTOR) for _ in texts]

    user, s, _ = await _seed(db)
    member = await db.fetchval(
        "insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') "
        "returning member_id", s, user)

    async def entity(name):
        return await find_entity_by_alias(db, s, normalize_alias(name))

    async def fact_of(source, attribute, value):
        """원장 사실 → 이어진 사실(knowledge_facts) 행."""
        return await db.fetchrow(
            "select f.fact_id as source_fact_id, k.fact_id, k.entity_id, k.head_revision_id "
            "from source_facts f "
            "join source_fact_revision_links l on l.store_id = f.store_id "
            "  and l.source_fact_id = f.fact_id "
            "join knowledge_facts k on k.store_id = l.store_id and k.fact_id = l.fact_id "
            "where f.store_id=$1 and f.source_id=$2 and f.attribute=$3 and f.value=$4 "
            "order by f.fact_id limit 1", s, source, attribute, value)

    async def proposals(source):
        return await db.fetch(
            "select proposal_id, entity_id, relation_type, status, matched_cards "
            "from upload_change_proposals where store_id=$1 and source_id=$2 "
            "order by proposal_id", s, source)

    async def events(action):
        return await db.fetch(
            "select entity_id, other_entity_id, payload from knowledge_entity_events "
            "where store_id=$1 and action=$2 order by event_id", s, action)

    def pair(rows, x, y):
        return [r for r in rows if {r["entity_id_low"], r["entity_id_high"]} == {x, y}]

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        # T1 — 자료 A: 영상 구간 2개를 동시에
        check = _checker("W3-0 T1")
        src_a = await _new_source(db, s, user, "VIDEO")
        parts_a = [
            ("구간1 합성 본문", [_fact("f1", A, "물", "200", "ml", ts=5),
                                _fact("f2", A, "시럽", "20", "ml", ts=8)]),
            ("구간2 합성 본문", [_fact("f1", A, "얼음", "100", "g", ts=65),
                                _fact("f2", B, "시럽", "15", "ml", ts=70)]),
        ]
        await _process(db, pool, s, user, src_a, parts_a, run_tag=601)
        counts_a = await _w2_counts(db, s)
        a_id, b_id = await entity(A), await entity(B)
        check("대상 2·사실 4·판 4·occurrence 4",
              a_id is not None and b_id is not None and a_id != b_id
              and (counts_a["knowledge_entities"], counts_a["knowledge_facts"],
                   counts_a["fact_revisions"], counts_a["fact_occurrences"]) == (2, 4, 4, 4))
        segments = sorted(r["segment_id"] for r in await db.fetch(
            "select distinct segment_id from source_facts where store_id=$1 and source_id=$2",
            s, src_a))
        check("두 구간이 모두 원장에 — seg1·seg2", segments == ["seg1", "seg2"])
        check("occurrence 는 모두 영상 시각(TIMESTAMP)", await db.fetchval(
            "select count(*) from fact_occurrences where store_id=$1 and source_id=$2 "
            "and locator_type='TIMESTAMP'", s, src_a) == 4)
        heads_a = await proposals(src_a)
        check("제안 2행(대상 A·B) 모두 NEW·PENDING_REVIEW",
              sorted(r["entity_id"] for r in heads_a) == sorted([a_id, b_id])
              and all((r["relation_type"], r["status"]) == ("NEW", "PENDING_REVIEW")
                      for r in heads_a))
        ab = pair(await list_candidates(db, s), a_id, b_id)
        check("A·B 같은 대상 후보 PENDING 1(EDIT1)", len(ab) == 1 and ab[0]["reason"] == "EDIT1")

        # T4 — A 재처리 → 중복 없음
        check = _checker("W3-0 T4")
        props_before = await _proposal_rows(db, s)
        await _process(db, pool, s, user, src_a, parts_a, run_tag=602)
        check("A 재처리 → W2 표 행 수 그대로", await _w2_counts(db, s) == counts_a)
        check("A 재처리 → 제안 머리·항목 그대로(updated_at 포함)",
              await _proposal_rows(db, s) == props_before)

        # T2 — 자료 B: HOT/ICE 동시 사실
        check = _checker("W3-0 T2")
        src_b = await _new_source(db, s, user, "SCAN")
        await _process(db, pool, s, user, src_b, [("합성 자료 본문 B", [
            _fact("f1", A, "에스프레소", "2", "샷", variant="HOT/ICE"),
            _fact("f2", A, "제조 순서", "잔에 붓는다", order=2, requires=["f1"]),
            _fact("f3", C, "시럽", "10", "ml"),
            _fact("f4", D, "시럽", "12", "ml")])], run_tag=603)
        ledger_b = await db.fetch(
            "select fact_id, local_ref, variant, assembly_state from source_facts "
            "where store_id=$1 and source_id=$2 and attribute='에스프레소' order by local_ref",
            s, src_b)
        check("원장 — f1~HOT(HOT)·f1~ICE(ICE) 두 행, HOT/ICE 한 행은 없다",
              [(r["local_ref"], r["variant"]) for r in ledger_b]
              == [("f1~HOT", "HOT"), ("f1~ICE", "ICE")])
        revs = await db.fetch(
            "select fact_revision_id, variant_temperature, quantity_value, original_assertion "
            "from fact_revisions where store_id=$1 and predicate='에스프레소' "
            "order by variant_temperature", s)
        check("판 둘 — HOT·ICE, 값 2·원문 같음",
              [r["variant_temperature"] for r in revs] == ["HOT", "ICE"]
              and {str(r["quantity_value"]) for r in revs} == {"2"}
              and len({r["original_assertion"] for r in revs}) == 1)
        marker = {"field": "variant", "verdict": "VARIANT_SPLIT", "value": "HOT/ICE",
                  "variant_split": "HOT_ICE", "from_ref": "f1"}
        located = await db.fetch(
            "select locator_type, locator::text loc, check_flags from source_fact_occurrences "
            "where store_id=$1 and fact_id = any($2::bigint[]) order by fact_id",
            s, [r["fact_id"] for r in ledger_b])
        check("원장 위치 둘 — 같은 자리, 둘 다 나눔 표시",
              len(located) == 2 and len({(o["locator_type"], o["loc"]) for o in located}) == 1
              and all(marker in json.loads(o["check_flags"]) for o in located))
        reasons = await db.fetch(
            "select reason from fact_occurrences where store_id=$1 "
            "and fact_revision_id = any($2::bigint[])", s, [r["fact_revision_id"] for r in revs])
        check("판 occurrence 둘 — W2_UNASSEMBLED, 매장에 VARIANT_MULTI 0",
              len(reasons) == 2 and all(r["reason"] == "W2_UNASSEMBLED" for r in reasons)
              and await db.fetchval("select count(*) from fact_occurrences where store_id=$1 "
                                    "and reason='VARIANT_MULTI'", s) == 0)
        step = await fact_of(src_b, "제조 순서", "잔에 붓는다")
        required = sorted(r["requires_revision_id"] for r in await db.fetch(
            "select requires_revision_id from fact_revision_requires "
            "where store_id=$1 and fact_revision_id=$2", s, step["head_revision_id"]))
        check("선행 관계 — 갈라진 두 판을 모두 가리킨다",
              required == sorted(r["fact_revision_id"] for r in revs))
        card_b = await db.fetchval("select card_id from knowledge_cards where store_id=$1 "
                                   "and source_id=$2 and title=$3", s, src_b, A)
        linked = {r["fact_id"] for r in await db.fetch(
            "select fact_id from card_facts where store_id=$1 and card_id=$2", s, card_b)}
        check("조립 ref f1 → 카드가 두 사실을 모두 잇고 LINKED",
              {r["fact_id"] for r in ledger_b} <= linked
              and all(r["assembly_state"] == "LINKED" for r in ledger_b))
        c_id, d_id = await entity(C), await entity(D)
        candidates = await list_candidates(db, s)
        check("후보 — (A,C)·(B,C)·(B,D) PENDING",
              all(len(pair(candidates, x, y)) == 1
                  for x, y in ((a_id, c_id), (b_id, c_id), (b_id, d_id))))

        # T3 — 자료 C: 다른 값 → 충돌 양쪽 보존, 승인 뒤 재처리
        check = _checker("W3-0 T3")
        src_c = await _new_source(db, s, user, "KAKAO")
        parts_c = [("합성 자료 본문 C", [_fact("f1", A, "물", "250", "ml")])]
        await _process(db, pool, s, user, src_c, parts_c, run_tag=604)
        groups = [g for g in await list_open_conflicts(db, s, entity_id=a_id)
                  if {str(f["quantity_value"]) for f in g["facts"]} == {"200", "250"}]
        check("200 ml·250 ml 두 사실 모두 남고 OPEN 충돌 1",
              len(groups) == 1 and len(groups[0]["facts"]) == 2
              and len(groups[0]["conflict_ids"]) == 1)
        forbidden = {"selected", "winner", "default", "chosen", "preferred"}
        check("기본 선택·승자 칸 없음", not (forbidden & set(groups[0]))
              and all(not (forbidden & set(f)) for f in groups[0]["facts"]))
        card_x = await db.fetchval(
            "select card_id from knowledge_cards where store_id=$1 and source_id=$2 "
            "and title=$3 order by card_id limit 1", s, src_a, A)
        draft_x = await db.fetchval("select draft_version_id from knowledge_cards "
                                    "where store_id=$1 and card_id=$2", s, card_x)
        with patch("app.reg.index_preparation.recorded_embeddings", fake_embedder):
            published = await publish_cards(
                pool, store_id=s, member_id=member, actor_user_id=user,
                changes=[CardChange(card_x, draft_x, draft_x)],
                idempotency_key="w3-0-t3-publish",
                usage_context=UsageContext(
                    store_id=str(s), cost_phase="OPERATING", cost_purpose="PRODUCT",
                    stage="EMBED", operation_id="w3-0-t3", logical_call_id="w3-0-t3:embed"))
        check("A 카드 발행", published.status == "PUBLISHED")
        await _process(db, pool, s, user, src_c, parts_c, run_tag=605)
        head_c = next(r for r in await proposals(src_c) if r["entity_id"] == a_id)
        check("승인 뒤 재처리 → 머리 CONFLICT·matched_cards = [A 카드]",
              (head_c["relation_type"], head_c["status"]) == ("CONFLICT", "PENDING_REVIEW")
              and [m["card_id"] for m in json.loads(head_c["matched_cards"])] == [card_x])
        await db.execute("update upload_change_proposals set matched_cards='[]'::jsonb "
                         "where store_id=$1 and proposal_id=$2", s, head_c["proposal_id"])
        await _process(db, pool, s, user, src_c, parts_c, run_tag=606)
        again = next(r for r in await proposals(src_c) if r["entity_id"] == a_id)
        check("같은 순위(CONFLICT) 재처리 → matched_cards 새 계산으로 갱신(§3-3-3)",
              again["relation_type"] == "CONFLICT"
              and [m["card_id"] for m in json.loads(again["matched_cards"])] == [card_x])

        # T5 — 대상 병합 → 후보·제안 정리
        check = _checker("W3-0 T5")
        src_e = await _new_source(db, s, user, "VOICE")
        src_f = await _new_source(db, s, user, "VOICE")
        parts_e = [("합성 자료 본문 E", [_fact("f1", B, "우유", "150", "ml")])]
        parts_f = [("합성 자료 본문 F", [_fact("f1", B, "얼음", "90", "g")])]
        await _process(db, pool, s, user, src_e, parts_e, run_tag=607)
        await _process(db, pool, s, user, src_f, parts_f, run_tag=608)
        await db.execute("update upload_change_proposals set status='DISMISSED', decided_by=$3, "
                         "decided_at=now() where store_id=$1 and source_id=$2", s, src_f, user)
        e_before = await proposals(src_e)
        f_dismissed = (await proposals(src_f))[0]["proposal_id"]
        f_text = (await _rows_text(db, "upload_change_proposals", "proposal_id", s))[f_dismissed]
        bc = pair(candidates, b_id, c_id)[0]["candidate_id"]
        bd = pair(candidates, b_id, d_id)[0]["candidate_id"]
        await merge_entities(db, s, keep_entity_id=a_id, merged_entity_id=b_id, actor_id=user,
                             candidate_id=ab[0]["candidate_id"])
        rows = await db.fetch(
            "select candidate_id, entity_id_low, entity_id_high, status, decided_by, evidence "
            "from knowledge_entity_candidates where store_id=$1", s)
        by_id = {r["candidate_id"]: r for r in rows}
        check("병합된 대상이 낀 PENDING 후보 0", not [
            r for r in rows
            if r["status"] == "PENDING" and b_id in (r["entity_id_low"], r["entity_id_high"])])
        ac = pair(rows, a_id, c_id)
        check("(B,C) → MERGED 로 닫힘, (A,C) 는 PENDING 한 행 그대로",
              (by_id[bc]["status"], by_id[bc]["decided_by"]) == ("MERGED", user)
              and len(ac) == 1 and ac[0]["status"] == "PENDING")
        ad = pair(rows, a_id, d_id)
        check("(B,D) → MERGED, keep 쪽 (A,D) 새 PENDING 후보(옮긴 출처 기록)",
              by_id[bd]["status"] == "MERGED" and len(ad) == 1 and ad[0]["status"] == "PENDING"
              and json.loads(ad[0]["evidence"])["moved_from_candidate_id"] == bd)
        check("이력 CANDIDATE_MOVED 2 — MOVED·CLOSED", sorted(
            json.loads(e["payload"])["outcome"] for e in await events("CANDIDATE_MOVED"))
            == ["CLOSED", "MOVED"])
        await _process(db, pool, s, user, src_e, parts_e, run_tag=609)
        e_after = await proposals(src_e)
        check("병합 뒤 E 재처리 → 제안 1행, 같은 proposal_id 가 살아 있는 대상 A 로",
              len(e_after) == 1 and e_after[0]["proposal_id"] == e_before[0]["proposal_id"]
              and (e_after[0]["entity_id"], e_after[0]["status"]) == (a_id, "PENDING_REVIEW"))
        await _process(db, pool, s, user, src_a, parts_a, run_tag=610)
        a_after = await proposals(src_a)
        check("병합 뒤 A 재처리 → PENDING 제안은 대상 A 하나, 옛 B 제안은 SUPERSEDED",
              [r["entity_id"] for r in a_after if r["status"] == "PENDING_REVIEW"] == [a_id]
              and [r["status"] for r in a_after if r["entity_id"] == b_id] == ["SUPERSEDED"])
        await _process(db, pool, s, user, src_f, parts_f, run_tag=611)
        check("결정된 제안(F, DISMISSED) 행 그대로",
              (await _rows_text(db, "upload_change_proposals", "proposal_id", s))[f_dismissed]
              == f_text)
        check("MERGED 대상 아래 PENDING 제안 0", await db.fetchval(
            "select count(*) from upload_change_proposals p join knowledge_entities e "
            "on e.store_id = p.store_id and e.entity_id = p.entity_id "
            "where p.store_id=$1 and p.status='PENDING_REVIEW' and e.status='MERGED'", s) == 0)
        check("이력 PROPOSAL_MOVED — MOVED(E)·SUPERSEDED(A)", sorted(
            json.loads(e["payload"])["outcome"] for e in await events("PROPOSAL_MOVED"))
            == ["MOVED", "SUPERSEDED"])

        # T6 — 대상 분리 → 이력, 공개본·카드 행 불변
        check = _checker("W3-0 T6")
        all_cards = [r["card_id"] for r in await db.fetch(
            "select card_id from knowledge_cards where store_id=$1", s)]
        published_before = await _published_fingerprint(db, s)
        cards_before = await _card_rows(db, s, all_cards)
        props_before = await _proposal_rows(db, s)
        ice = await fact_of(src_a, "얼음", "100")
        new_entity = await split_entity(db, s, entity_id=a_id, fact_ids=[ice["fact_id"]],
                                        new_canonical_name="합성 얼음 대상",
                                        move_alias_norms=[], actor_id=user)
        moved = await db.fetchval("select entity_id from knowledge_facts where store_id=$1 "
                                  "and fact_id=$2", s, ice["fact_id"])
        check("분리 → 새 대상·사실 이동·이력 SPLIT 1",
              new_entity != a_id and moved == new_entity and len(await events("SPLIT")) == 1)
        check("공개본·카드 행·제안 그대로",
              await _published_fingerprint(db, s) == published_before
              and await _card_rows(db, s, all_cards) == cards_before
              and await _proposal_rows(db, s) == props_before)

        # T7 — 점주 정정 → 새 판, 옛 이관 정정은 그 위에 얹히지 않는다
        check = _checker("W3-0 T7")
        water = await fact_of(src_a, "물", "200")
        owner_rev = await revise_fact(
            db, s, fact_id=water["fact_id"], expected_head_revision_id=water["head_revision_id"],
            change=FactChange(value="210", original_assertion="물은 210ml 로 바꿨어요"),
            change_kind="OWNER_CORRECTION", actor_id=user)
        await db.execute("update source_facts set corrected_value='205', corrected_by=$3 "
                         "where store_id=$1 and fact_id=$2", s, water["source_fact_id"], user)
        first = await import_legacy_correction(db, s, source_fact_id=water["source_fact_id"])
        second = await import_legacy_correction(db, s, source_fact_id=water["source_fact_id"])
        head = await db.fetchval("select head_revision_id from knowledge_facts "
                                 "where store_id=$1 and fact_id=$2", s, water["fact_id"])
        check("점주 정정 → 새 head", owner_rev != water["head_revision_id"] and head == owner_rev)
        check("옛 corrected_value 이관 → None 두 번, head 그대로, LEGACY 판 0",
              first is None and second is None and head == owner_rev
              and await db.fetchval("select count(*) from fact_revision_meta where store_id=$1 "
                                    "and change_kind='LEGACY_CORRECTION'", s) == 0)

        # T8 — 플래그를 다시 끈 뒤 처리
        check = _checker("W3-0 T8")
        counts = await _w2_counts(db, s)
        props = await _proposal_rows(db, s)
        candidate_n = await db.fetchval(
            "select count(*) from knowledge_entity_candidates where store_id=$1", s)
        event_n = await db.fetchval(
            "select count(*) from knowledge_entity_events where store_id=$1", s)
        src_g = await _new_source(db, s, user, "SCAN")
        await _process(db, pool, s, user, src_g, [("합성 자료 본문 G", [
            _fact("f1", A, "에스프레소", "3", "샷", variant="HOT/ICE")])],
            run_tag=612, flags=False)
        check("꺼짐 → W2 표·제안·후보·이력 행 그대로",
              await _w2_counts(db, s) == counts and await _proposal_rows(db, s) == props
              and await db.fetchval("select count(*) from knowledge_entity_candidates "
                                    "where store_id=$1", s) == candidate_n
              and await db.fetchval("select count(*) from knowledge_entity_events "
                                    "where store_id=$1", s) == event_n)
        g_rows = await db.fetch("select local_ref, variant from source_facts "
                                "where store_id=$1 and source_id=$2", s, src_g)
        check("꺼짐 → HOT/ICE 는 나누지 않고 원장 한 행(이전과 같다)",
              [(r["local_ref"], r["variant"]) for r in g_rows] == [("f1", "HOT/ICE")])
        check("꺼짐 → 새 카드 entity_id null", await db.fetchval(
            "select count(*) from knowledge_cards where store_id=$1 and source_id=$2 "
            "and entity_id is not null", s, src_g) == 0)
    finally:
        await pool.close()
    print("PASS W3-0 flag readiness all scenarios")
```

- [ ] **Step 2: W 검증에 연결** — `api/scripts/verify_w_entity_revision.py`

(a) `verify()`(`:1700-1709`) 를 바꾼다:

```python
async def verify(db, dsn):
    # 설정은 함수 안에서 읽으므로 patch 가 먹는다 (F21). 후보 상한은 기본값 5
    settings = Settings(_env_file=None)
    with patch.object(app.config, "get_settings", lambda: settings):
        await _scenario_entities(db)
        await _scenario_ledger(db, dsn)
        await _scenario_revisions(db, dsn)
        await _scenario_proposals(db, dsn)
        await _scenario_entity_admin(db, dsn)
        # W3-0 §3-6 — 두 플래그를 켠 합성 종단 검증. 순환 import 를 피해 여기서 부른다
        from verify_w3_flag_readiness import verify as verify_w3_0
        await verify_w3_0(db, dsn)
    print("PASS W entity revision all scenarios")
```

(b) 모듈 docstring 의 Task 5 단락(S4 줄) 뒤, 닫는 `"""` 앞에 추가:

```text

W3-0 (설계 W3_0_FLAG_READINESS_DESIGN §3-6): verify() 끝에서 scripts/verify_w3_flag_readiness.py 를
부른다 — 두 플래그를 켠 합성 종단 검증 T1~T8.
```

- [ ] **Step 3: 실제 DB 재구축 실행**

Run: Global 의 docker run → `verify_r_schema_rebuild.py` → docker stop.
Expected: `PASS W entity W3-0 T1 …` 부터 `PASS W entity W3-0 T8 …` 까지 모두 나오고 `PASS W3-0 flag readiness all scenarios`, 이어 `PASS W entity revision all scenarios` 와 뒤의 W 공개·R 검증이 예외 없이 끝난다.
실패하면 실패한 검사 이름을 보고 원인을 고친다(시나리오 기대를 바꿔 통과시키지 않는다 — 기대가 설계와 어긋났다고 판단되면 멈추고 보고한다).

- [ ] **Step 4: §3-4 기록 — 인계 문서 8번 닫기** — `docs/dev/plan/W_TO_R_PUBLICATION_HANDOFF_20260927.md`

현재 "R 이 할 일" 8번 줄 전체(`8. **\`FactProvenance.source_id\`(\`contracts/snapshot.py\`)가 필수라 …` 로 시작해 `… 확인한다.` 로 끝나는 한 줄)를 다음으로 바꾼다:

```markdown
8. ~~`FactProvenance.source_id` 필수 · `owner_answer_id` FK `on delete restrict` 점검~~ — **닫힘, R 이 할 일 없음.**
   (a) R 이 `4bb145c`(2026-10-05)에서 `FactProvenance` 를 `source_id XOR owner_answer_id`(파일 출처면 `occurrence_id` 필수)로 바꿨다(`api/app/contracts/snapshot.py:35-55`).
   (b) W3-0 §3-4 확인(2026-10-07, 코드 변경 없음): R 트리거 `askbuddy_owner_original_immutable`(`supabase/migrations/20260917130000_m3_owner_answer_delivery.sql:43-56`)가 R revision 이 있는 점주 답변의 삭제·원문 수정을 막고, 앱 코드(`api/app`)에는 `owner_answers`·`pending_questions`(답변으로 cascade)를 지우는 경로가 없다. 따라서 W 링크(`fact_revision_meta.owner_answer_id`·`fact_owner_answer_links`)의 `on delete restrict` 가 새로 막는 앱 삭제 경로는 없다. 매장 삭제는 기존처럼 불변 원장 때문에 막히고, 데모 매장은 보관 방식으로 처리한다(현행 유지).
```

- [ ] **Step 5: §3-4 기록 — W_NEXT_PLAN 플래그 점검 줄** — `docs/dev/plan/W_NEXT_PLAN_20260928.md`

```markdown
- [ ] `owner_answer_id` FK 는 R 소유 `owner_answers` 에 대해 `on delete restrict` 다. 점주 답변 삭제 경로와 맞춘다(인계 문서 R 이 할 일).
```

를 다음으로 바꾼다:

```markdown
- [x] `owner_answer_id` FK 는 R 소유 `owner_answers` 에 대해 `on delete restrict` 다. — W3-0 §3-4 확인: R 트리거가 R revision 있는 답변의 삭제를 막고 앱에 답변 삭제 경로가 없어 새로 막히는 경로 없음. 코드 변경 없음(인계 문서 R 이 할 일 8, 닫힘).
```

- [ ] **Step 6: 단위 테스트 회귀 확인**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests`
Expected: `1765 passed, 4 xfailed` (스크립트만 더했으므로 Task 3 과 같다).

- [ ] **Step 7: 변경 확인, 커밋하지 않는다**

Run: `git -C /Users/chabee/new/New_Source/2026unithon-w3 status --short && git -C /Users/chabee/new/New_Source/2026unithon-w3 diff --stat`
Expected: `verify_w3_flag_readiness.py` 새 파일, `verify_w_entity_revision.py`·인계 문서·W_NEXT_PLAN 변경. 커밋하지 않는다.

---

### Task 5: 처리량 측정 스크립트와 기록 (설계 §3-5)

**Files:**
- Create: `api/scripts/probe_w3_flag_throughput.py`
- Create: `api/tests/test_w3_throughput_probe.py`
- Create: `docs/dev/review/W3_0_THROUGHPUT_<측정일 YYYYMMDD>.md` (측정한 날짜를 `date +%Y%m%d` 로 쓴다. 2026-10-07 에 재면 `W3_0_THROUGHPUT_20261007.md`)

**Interfaces:**
- Consumes: `pipeline.process_source`, `pipeline._persist_ledger`, `pipeline._persist`, `fact_ledger.link_source_facts`, `fact_ledger.lock_store_knowledge`/`entities.lock_store_knowledge`/`impact.lock_store_knowledge`(모듈 속성으로 patch), `entities._propose_candidates`, `verify_r_answer_usage.DSN`, `verify_w_partial_extraction._fresh_db(admin) -> (name, db)`, `_seed`, `_new_source`.
- Produces:
  - `synthetic_segments(facts_total: int = 300, entities_total: int = 60, segments_total: int = 10) -> list[list[dict]]`
  - `summary(values: list[float]) -> dict` — `{"n", "sum_ms", "p50_ms", "p95_ms", "max_ms"}` 또는 `{"n": 0}`
  - `class Probe` — `link`, `lock_wait`, `lock_hold`, `candidates` 목록(초)
  - `run_once(db, dsn: str, *, concurrency: int, delay_s: float, segments: list[list[dict]]) -> dict`
  - `main(argv: list[str] | None = None) -> int` (CLI `--model-delay-ms`, `--out`)

측정 정의(기록 문서에 그대로 옮긴다):
- `total_ms`: `process_source` 벽시계(전처리·추출 대역·원장·연결·조립 대역·카드 저장 전부).
- `link`: 구간 checkpoint 마다 `link_source_facts` 시간(안에서 잡는 매장 잠금 대기 포함).
- `lock_wait`: 트랜잭션에서 처음 매장 advisory lock 문을 실행해 돌아오기까지(같은 트랜잭션 재진입 제외).
- `lock_hold`: 처음 잠근 시각 → 그 트랜잭션 함수(`_persist_ledger` 또는 `_persist`)가 끝난 시각. commit 시간은 빠진다.
- `candidates_per_new_entity`: 새 대상 하나의 `_propose_candidates` 시간.
- `lock_hold_share`: `sum(lock_hold) / total`.

- [ ] **Step 1: 실패하는 테스트 작성** — `api/tests/test_w3_throughput_probe.py`

```python
"""W3-0 §3-5 처리량 측정 스크립트의 순수 함수. DB·모델은 부르지 않는다."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import probe_w3_flag_throughput as probe  # noqa: E402


def test_synthetic_segments_shape():
    segments = probe.synthetic_segments(facts_total=300, entities_total=60, segments_total=10)
    flat = [f for seg in segments for f in seg]
    assert len(segments) == 10 and all(len(seg) == 30 for seg in segments)
    assert len(flat) == 300 and len({f["subject"] for f in flat}) == 60
    assert all(seg[i]["local_ref"] == f"f{i + 1}" for seg in segments for i in range(30))
    # 사실은 서로 다르다(원장 content_hash 로 합쳐지지 않는다)
    assert len({(f["subject"], f["attribute"], f["value"]) for f in flat}) == 300
    assert all(f["evidence"]["timestamp_sec"] > 0 for f in flat)
    assert all(f["subject"].startswith("측정메뉴") for f in flat)


def test_summary_reports_ms_percentiles():
    assert probe.summary([0.001, 0.002, 0.003, 0.004]) == {
        "n": 4, "sum_ms": 10.0, "p50_ms": 2.5, "p95_ms": 4.0, "max_ms": 4.0}
    assert probe.summary([]) == {"n": 0}
```

- [ ] **Step 2: 실패 확인**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests/test_w3_throughput_probe.py`
Expected: `ModuleNotFoundError: No module named 'probe_w3_flag_throughput'`.

- [ ] **Step 3: 측정 스크립트 작성** — `api/scripts/probe_w3_flag_throughput.py`

```python
"""W3-0 §3-5 — 두 W2 플래그를 켠 수집의 처리량을 잰다. 합성 데이터만, 모델 호출 없음, 비용 0.

일회용 DB 서버(verify_r_answer_usage.DSN, 127.0.0.1:55439)에 새 UUID DB 를 만들고 migration 을
모두 올린 뒤 process_source 를 합성 모델 대역으로 돌린다. 끝나면 그 DB 를 지운다.

재는 것 (합격선 없음 — D21 카드 생성 지연 상한 보류):
  - total: 자료 처리 전체 시간(process_source 벽시계)
  - link: 구간 checkpoint 마다 원장→판 연결 시간(link_source_facts, 안의 잠금 대기 포함)
  - lock_wait: 매장 advisory lock 대기(트랜잭션에서 처음 잡을 때만)
  - lock_hold: 매장 lock 을 쥔 시간(처음 잡은 때 → 그 트랜잭션 함수가 끝날 때, commit 제외)
  - candidates_per_new_entity: 새 대상 하나의 같은 대상 후보 계산 시간
조건: 사실 300건·대상 60개·구간 10개, 구간 동시성 1 과 2, 모델 지연 0ms 와 --model-delay-ms.

사용 (api/ 에서):
  PYTHONPATH=. PYTHONUTF8=1 <venv python> -B scripts/probe_w3_flag_throughput.py \
      --model-delay-ms 1500 --out <저장할 JSON 경로>
"""
import argparse
import asyncio
import json
import statistics
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import asyncpg

import app.config
from app.config import Settings
from app.ingest import entities, extract, fact_ledger, impact, pipeline
from app.ingest import repository as repo
from app.ingest.extract import gemini
from app.ingest.schemas import (ExtractedCard, ExtractedFact, ExtractionResult,
                                FactExtractionResult)

_MODEL_SETTINGS = NS(gemini_api_key="synthetic", gemini_model="gemini-synthetic",
                     ingest_mode="real", extract_temperature=0.0, extract_locator_hints=False)
_COUNTED = ("source_facts", "knowledge_entities", "knowledge_entity_candidates",
            "fact_revisions", "fact_occurrences", "upload_change_proposals")


def synthetic_segments(facts_total: int = 300, entities_total: int = 60,
                       segments_total: int = 10) -> list[list[dict]]:
    """구간마다 사실 목록. 대상 이름은 합성 '측정메뉴NN', 사실마다 속성·값이 다르다."""
    per_segment = facts_total // segments_total
    segments = []
    for seg in range(segments_total):
        facts = []
        for i in range(per_segment):
            n = seg * per_segment + i
            subject = f"측정메뉴{n % entities_total:02d}"
            facts.append(dict(
                local_ref=f"f{i + 1}", original_assertion=f"{subject} 속성{n} {n}ml",
                subject=subject, attribute=f"속성{n}", value=str(n), unit="ml",
                confidence=.9, evidence=dict(timestamp_sec=seg * 60 + i + 1)))
        segments.append(facts)
    return segments


def summary(values: list[float]) -> dict:
    """초 단위 측정값 → ms 요약."""
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"n": len(values), "sum_ms": round(sum(values) * 1000, 1),
            "p50_ms": round(statistics.median(values) * 1000, 1),
            "p95_ms": round(p95 * 1000, 1), "max_ms": round(max(values) * 1000, 1)}


class Probe:
    """잠금·연결·후보 계산 시간을 모은다. 태스크마다 처음 잡은 매장 잠금 시각을 기억한다."""

    def __init__(self) -> None:
        self.link: list[float] = []
        self.lock_wait: list[float] = []
        self.lock_hold: list[float] = []
        self.candidates: list[float] = []
        self._acquired: dict[int, float] = {}

    @staticmethod
    def _task() -> int:
        return id(asyncio.current_task())

    def lock(self, original):
        async def timed(conn, store_id):
            started = time.perf_counter()
            await original(conn, store_id)
            got = time.perf_counter()
            # 같은 트랜잭션 안의 재진입은 새 대기·보유로 세지 않는다
            if self._task() not in self._acquired:
                self._acquired[self._task()] = got
                self.lock_wait.append(got - started)
        return timed

    def transaction_end(self, original):
        async def timed(*args, **kwargs):
            try:
                return await original(*args, **kwargs)
            finally:
                got = self._acquired.pop(self._task(), None)
                if got is not None:
                    self.lock_hold.append(time.perf_counter() - got)
        return timed

    def timed(self, bucket: list[float], original):
        async def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return await original(*args, **kwargs)
            finally:
                bucket.append(time.perf_counter() - started)
        return wrapper


async def run_once(db, dsn: str, *, concurrency: int, delay_s: float,
                   segments: list[list[dict]]) -> dict:
    """새 합성 매장 하나에서 영상 자료 하나를 처리하며 잰다."""
    from verify_w_partial_extraction import _new_source, _seed

    user, store, _ = await _seed(db)
    source = await _new_source(db, store, user, "VIDEO")
    job_id = await db.fetchval(
        "insert into ingest_jobs (store_id, created_by, title, status, category_version, "
        "prompt_version) values ($1,$2,'W3-0 처리량','EXTRACTING',1,'v1') returning job_id",
        store, user)
    await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                     store, source)
    await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                     "values($1,$2,$3,'QUEUED')", store, job_id, source)
    category = next(iter(await repo.enabled_categories(db, store)))
    texts = [f"측정 구간 {i + 1:02d}" for i in range(len(segments))]
    by_text = dict(zip(texts, segments))

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        if delay_s:
            await asyncio.sleep(delay_s)
        if schema is not None and issubclass(schema, FactExtractionResult):
            facts = next(v for k, v in by_text.items() if k in prompt)
            body = FactExtractionResult.model_validate({"assertions": facts})
            return gemini.CallResult(body.model_dump_json(), {}, "STOP")
        cards = [ExtractedCard(
            category_name=category, title=f"측정 카드 {i:02d}", content="합성 카드",
            confidence=.9, facts=[ExtractedFact(
                object_name=f["subject"], attribute=f["attribute"], value=f["value"],
                confidence=.9, ref=f"seg{i}:{f['local_ref']}") for f in facts])
            for i, facts in enumerate(segments, start=1)]
        return gemini.CallResult(ExtractionResult(cards=cards).model_dump_json(), {}, "STOP")

    probe = Probe()
    settings = Settings(_env_file=None, w_entity_revision_enabled=True,
                        w_upload_proposals_enabled=True,
                        extract_segment_concurrency=concurrency)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        with ExitStack() as stack:
            for obj, name, replacement in [
                (pipeline, "get_pool", lambda: pool),
                (pipeline, "_preprocess", AsyncMock(return_value=(
                    "측정 본문", [], [(t, []) for t in texts]))),
                (pipeline.shutil, "rmtree", lambda *a, **kw: None),
                (app.config, "get_settings", lambda: settings),
                (extract, "get_settings", lambda: NS(ingest_mode="real")),
                (gemini, "get_settings", lambda: _MODEL_SETTINGS),
                (gemini, "_call", fake_call),
                (fact_ledger, "lock_store_knowledge",
                 probe.lock(fact_ledger.lock_store_knowledge)),
                (entities, "lock_store_knowledge", probe.lock(entities.lock_store_knowledge)),
                (impact, "lock_store_knowledge", probe.lock(impact.lock_store_knowledge)),
                (pipeline, "_persist_ledger", probe.transaction_end(pipeline._persist_ledger)),
                (pipeline, "_persist", probe.transaction_end(pipeline._persist)),
                (fact_ledger, "link_source_facts",
                 probe.timed(probe.link, fact_ledger.link_source_facts)),
                (entities, "_propose_candidates",
                 probe.timed(probe.candidates, entities._propose_candidates)),
            ]:
                stack.enter_context(patch.object(obj, name, replacement))
            started = time.perf_counter()
            await pipeline.process_source(store, source, job_id=job_id, run_tag=900 + concurrency)
            total = time.perf_counter() - started
    finally:
        await pool.close()
    state = await db.fetchval("select status from sources where store_id=$1 and source_id=$2",
                              store, source)
    assert state == "DONE", f"처리 실패: {state}"
    rows = {t: await db.fetchval(f"select count(*) from {t} where store_id=$1", store)
            for t in _COUNTED}
    return {
        "conditions": {"facts": sum(len(seg) for seg in segments),
                       "entities": len({f["subject"] for seg in segments for f in seg}),
                       "segments": len(segments), "segment_concurrency": concurrency,
                       "model_delay_ms": round(delay_s * 1000)},
        "total_ms": round(total * 1000, 1),
        "link": summary(probe.link),
        "lock_wait": summary(probe.lock_wait),
        "lock_hold": summary(probe.lock_hold),
        "candidates_per_new_entity": summary(probe.candidates),
        "lock_hold_share": round(sum(probe.lock_hold) / total, 3),
        "rows": rows,
    }


async def main(argv: list[str] | None = None) -> int:
    from verify_r_answer_usage import DSN
    from verify_w_partial_extraction import _fresh_db

    parser = argparse.ArgumentParser(description="W3-0 처리량 측정(합성, 비용 0)")
    parser.add_argument("--model-delay-ms", type=int, default=0,
                        help="합성 모델 호출마다 기다릴 ms (0 이면 지연 없음만 잰다)")
    parser.add_argument("--out", type=Path, default=None, help="결과 JSON 을 저장할 경로")
    args = parser.parse_args(argv)
    admin = await asyncpg.connect(DSN, timeout=5)
    name = db = None
    try:
        name, db = await _fresh_db(admin)
        dsn = DSN.rsplit("/", 1)[0] + "/" + name
        segments = synthetic_segments()
        results = []
        for delay_ms in sorted({0, args.model_delay_ms}):
            for concurrency in (1, 2):
                results.append(await run_once(db, dsn, concurrency=concurrency,
                                              delay_s=delay_ms / 1000, segments=segments))
        text = json.dumps(results, ensure_ascii=False, indent=2)
        print(text)
        if args.out is not None:
            args.out.write_text(text + "\n", encoding="utf-8")
    finally:
        if db is not None:
            await db.close()
        if name is not None:
            await admin.execute(f'drop database "{name}"')
        await admin.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 4: 통과 확인**

Run: `$PY -B -m pytest -q -p no:cacheprovider tests/test_w3_throughput_probe.py`
Expected: 2 passed.
Run: `$PY -B -m pytest -q -p no:cacheprovider tests`
Expected: `1767 passed, 4 xfailed` (1765 + 2).

- [ ] **Step 5: 측정 실행 (합성, 비용 0)**

```bash
docker run -d --rm --name askbuddy-w-verify -p 127.0.0.1:55439:5432 \
  -e POSTGRES_PASSWORD=synthetic-local-test -e POSTGRES_DB=usage_verify pgvector/pgvector:pg17
cd /Users/chabee/new/New_Source/2026unithon-w3/api && PYTHONPATH=. PYTHONUTF8=1 $PY -B scripts/probe_w3_flag_throughput.py \
  --model-delay-ms 1500 \
  --out /private/tmp/claude-501/-Users-chabee-new-New-Source-2026unithon/814e8d8d-803c-4c3b-9faa-ca0baa03240b/scratchpad/w3_0_throughput.json
docker stop askbuddy-w-verify
```

Expected: JSON 배열 4개(지연 0ms·1500ms × 동시성 1·2). 각 항목 `rows.source_facts == 300`, `rows.knowledge_entities == 60`, `rows.fact_occurrences == 300`. 프로세스 종료 코드 0. 모델 지연 1500ms 는 실제 공급자 지연이 아니라 합성 조건이다.

- [ ] **Step 6: 기록 문서 작성** — `docs/dev/review/W3_0_THROUGHPUT_<측정일>.md`

아래 구조로 쓰고, 표의 숫자는 Step 5 JSON 에서 그대로 옮긴다(반올림·추정 금지). 원자료 JSON 전체를 문서 끝 코드 블록에 붙인다.

````markdown
# W3-0 처리량 측정 — 두 W2 플래그 켜짐 (<측정일 YYYY-MM-DD>)

> 설계: `docs/dev/plan/W3_0_FLAG_READINESS_DESIGN.md` §3-5. 합격선 없음(D21 카드 생성 지연 상한 보류).
> 합성 데이터·합성 모델 대역, 유료 호출 0, 비용 0. 숫자는 이 조건의 관찰 기록이며 운영 지연 보장이 아니다.

## 조건

- 스크립트: `api/scripts/probe_w3_flag_throughput.py` (브랜치 `w/w3-fact-assembly`, 측정 시 HEAD `<git rev-parse --short HEAD>`)
- DB: 로컬 Docker `pgvector/pgvector:pg17`(127.0.0.1:55439), migration 전체 적용한 새 UUID DB. 기기: <측정 기기, 예: 개발용 macOS 노트북>
- 자료: 영상 자료 1건, 구간 10개, 사실 300건(구간당 30), 대상 60개(`측정메뉴00`~`59`, 서로 한 글자 차이라 대상마다 후보 계산이 돈다, 상한 5)
- 플래그: `w_entity_revision_enabled=true`, `w_upload_proposals_enabled=true`
- 변수: 구간 동시성 1·2 × 합성 모델 지연 0ms·1500ms (호출마다 `asyncio.sleep`)
- 정의: total = `process_source` 벽시계 / link = 구간마다 `link_source_facts`(안의 잠금 대기 포함) / lock_wait = 트랜잭션에서 처음 매장 잠금을 잡기까지 / lock_hold = 처음 잡은 때 → `_persist_ledger`·`_persist` 가 끝날 때(commit 제외) / 후보 = 새 대상 하나의 `_propose_candidates`

## 결과

| 지연 | 동시성 | total ms | link p50/p95 ms (합) | lock_wait p50/p95/max ms | lock_hold 합 ms | lock_hold 몫 | 후보 p50/p95 ms (n) |
|---|---|---|---|---|---|---|---|
| 0 | 1 | … | … | … | … | … | … |
| 0 | 2 | … | … | … | … | … | … |
| 1500 | 1 | … | … | … | … | … | … |
| 1500 | 2 | … | … | … | … | … | … |

## 관찰

- 매장 lock 보유 몫(lock_hold 합 / total): 지연 1500ms 조건에서 <값>.
  **0.5 이상이면** 이 줄에 "매장 lock 을 쥔 시간이 자료 처리 전체 시간의 큰 몫이다" 라고 쓰고, `W3_0_FLAG_ROLLOUT.md` §0 에 사용자 확인 항목으로 옮긴다.
- 동시성 2 의 lock_wait: 구간 두 개가 매장 lock 을 두고 기다린 시간(p95·max).
- 대상 하나당 후보 계산: p50/p95, 새 대상 수 n.

## 한계

- 로컬·합성 조건이다. 운영 DB(Supabase) 왕복 지연·동시 매장 부하는 들어가지 않았다.
- lock_hold 는 commit 시간을 빼고, link 는 안의 잠금 대기를 포함한다.
- 실제 모델 지연은 재지 않았다(1500ms 는 합성 값).

## 원자료

```json
<Step 5 JSON 전체>
```
````

(문서 안의 `<…>`·`…` 는 이 Step 에서 Step 5 출력값으로 모두 채운다. 채우지 못한 칸이 남으면 Task 를 끝내지 않는다.)

- [ ] **Step 7: 변경 확인, 커밋하지 않는다**

Run: `git -C /Users/chabee/new/New_Source/2026unithon-w3 status --short`
Expected: `probe_w3_flag_throughput.py`·`test_w3_throughput_probe.py`·`W3_0_THROUGHPUT_<측정일>.md` 새 파일. 커밋하지 않는다.

---

### Task 6: 배포판 켜기 절차 문서 + 계획·TODO 갱신 + 마감 검증 (설계 §3-7)

**Files:**
- Create: `docs/dev/plan/W3_0_FLAG_ROLLOUT.md`
- Modify: `docs/dev/plan/W_NEXT_PLAN_20260928.md` ("W2 에서 넘어온 것" `:254-260`, "플래그 켜기 전 점검" `:262-267`)
- Modify: `docs/dev/DEV_TODO_CURRENT.md` ("## W3." 절 머리, 현재 `:313`)

**Interfaces:**
- Consumes: 배포 사실(저장소에서 확인함) — `.github/workflows/deploy-api.yml` 순서: 운영 DB 백업 → `supabase db push --db-url "$PROD_DB_URL"` → `.github/scripts/ssm_deploy.sh` → health. `ssm_deploy.sh` 는 SSM 으로 `runuser -l ubuntu -c 'cd ~/askbuddy && git checkout --force <sha> && bash deploy/remote_deploy.sh'` 를 보낸다. `deploy/remote_deploy.sh` 는 `deploy/` 에서 `docker compose up -d --build --remove-orphans`. `deploy/compose.yml` 의 api 서비스는 `env_file: ${ASKBUDDY_ENV_FILE:-/home/ubuntu/askbuddy.env}`. 설정은 `pydantic-settings`(`api/app/config.py`, 필드 이름 대소문자 무시 → `W_ENTITY_REVISION_ENABLED`), `get_settings()` 는 `lru_cache` 라 컨테이너를 다시 만들어야 읽는다. 수집은 API 프로세스 안에서 돈다.
- Produces: 사용자 실행용 문서. 코드 산출물 없음.

- [ ] **Step 1: 켜기 절차 문서 작성** — `docs/dev/plan/W3_0_FLAG_ROLLOUT.md`

````markdown
# W3-0 배포판 W2 플래그 켜기 절차 (사용자 실행)

> 설계: `docs/dev/plan/W3_0_FLAG_READINESS_DESIGN.md` §3-7. **이 문서의 명령은 사용자가 실행한다.** 개발 세션은 배포 환경 값을 바꾸지 않는다.
> 켜면 그 뒤로 처리되는 자료부터 대상·불변 판·occurrence·충돌·업로드 제안이 쌓인다. 기존 자료·카드는 소급 이관하지 않는다(2026-10-07 결정).

## 0. 켜기 전 확인

- W3-0 PR 이 main 에 머지되고 `Deploy API` 워크플로가 성공했다(GitHub Actions). 배포는 migration(`supabase db push`)을 서버 배포 **전에** 적용하므로 순서는 이미 맞다.
- 처리량 기록 `docs/dev/review/W3_0_THROUGHPUT_<측정일>.md` 의 "관찰" 을 읽는다. 매장 lock 보유 몫이 크다고 적혀 있으면 켜기 전에 그 영향(같은 매장 자료가 차례로 처리됨)을 받아들일지 정한다.
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
select to_regclass('public.knowledge_entities'), to_regclass('public.knowledge_facts'),
       to_regclass('public.fact_revision_meta'), to_regclass('public.fact_occurrences'),
       to_regclass('public.upload_change_proposals');

-- W3-0 이 넓힌 허용 값: 'MERGED' 와 'CANDIDATE_MOVED'·'PROPOSAL_MOVED' 가 보여야 한다
select conname, pg_get_constraintdef(oid) from pg_constraint
where conname in ('knowledge_entity_candidates_status_check', 'knowledge_entity_events_action_check');
```

하나라도 빠졌으면 켜지 않는다. `Deploy API` 의 "migration 적용" 단계 로그를 확인한다.

## 2. 서버 API 환경 값에 두 플래그 켜기

API 컨테이너는 `deploy/compose.yml` 의 `env_file: ${ASKBUDDY_ENV_FILE:-/home/ubuntu/askbuddy.env}` 를 읽는다.
기본은 `/home/ubuntu/askbuddy.env` 이고, ubuntu 로그인 셸 환경이나 `~/askbuddy/deploy/.env` 에 `ASKBUDDY_ENV_FILE` 가 있으면 그 경로다(배포 SSM 명령이 `runuser -l ubuntu` 로그인 셸에서 `docker compose` 를 돌린다).
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
select source_id, store_id, source_type, status, updated_at
from sources where status = 'DONE' and updated_at >= now() - interval '1 hour'
order by source_id desc limit 5;

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

- 기대: `linked_facts` = `ledger_facts`(대상 이름을 정규화할 수 없는 사실만 빠지고 로그 `대상 결정 불가` 가 남는다), `occurrences` ≥ `linked_facts`, `proposals` ≥ 1, `store_entities` ≥ 1.
- 오류·처리 시간 로그:

```bash
cd ~/askbuddy/deploy && docker compose logs --since 1h api | grep -E "W2 연결|W2 업로드 제안|W3-0 제안 정리|대상 결정 불가|ingest DONE|ingest FAILED|Traceback"
```

- `ingest DONE source=… cards=… 구간 …/… 실패 N.Ns` 의 마지막 초가 처리 시간이다. 켜기 전 같은 크기 자료와 비교하고 처리량 기록의 숫자와 함께 본다.

## 4. 되돌리기

- env 파일의 두 줄을 `false` 로 바꾸고(또는 지우고) §2 의 `docker compose up -d --force-recreate api` 를 다시 실행한다. 확인 출력은 `False False`.
- 끄면 **새 쓰기만** 멈춘다. 이미 쌓인 대상·판·occurrence·충돌·제안 행은 지우지 않는다(불변 원장, W3-0 종단 검증 T8). 다시 켜면 그 행 위에 이어서 쌓인다.
- 백업한 env 파일(`$ENV_FILE.bak-…`)로 되돌려도 된다.
````

- [ ] **Step 2: W_NEXT_PLAN 갱신** — `docs/dev/plan/W_NEXT_PLAN_20260928.md` 의 "W2 에서 넘어온 것" 다섯 줄과 "플래그 켜기 전 점검" 남은 네 줄(Task 4 Step 5 에서 고친 `owner_answer_id` 줄 제외)을 아래로 바꾼다. 처리량 기록 파일 이름은 Task 5 에서 만든 실제 이름을 쓴다.

```markdown
### W2 에서 넘어온 것
- [x] 병합 뒤 재처리하면 병합된 대상 아래의 옛 PENDING 업로드 제안과 남은 대상 아래의 새 PENDING 제안이 중복된다. — W3-0 §3-3-2: 병합된 대상의 PENDING 제안을 살아 있는 대상으로 옮기고(이미 있으면 SUPERSEDED), 이력 PROPOSAL_MOVED.
- [x] 병합된 대상이 낀 다른 PENDING 같은 대상 후보(병합된 것, 제3 대상)가 그대로 PENDING 으로 남는다. — W3-0 §3-3-1: keep 쪽으로 옮기거나 MERGED 로 닫고 이력 CANDIDATE_MOVED.
- [x] `import_legacy_correction` 이 점주 정정 판 위에 더 오래된 `corrected_value` 를 새 head 로 얹을 수 있다(적용 시각과 head 순서 불일치). — W3-0 §3-2: head 가 EXTRACTION 이 아니면 건너뜀.
- [x] 같은 순위로 다시 처리하면 제안의 `matched_cards` 가 갱신되지 않는다. — W3-0 §3-3-3: 같은 순위면 달라졌을 때 새 계산으로 갱신.
- [x] 기존 카드·사실은 소급 채우지 않았다(`knowledge_cards.entity_id` 비어 있음, 옛 `source_facts` 의 대상·판 없음). — 2026-10-07 사용자 결정: 소급 이관하지 않는다. 플래그를 켠 뒤 올라온 자료만 새 구조로 간다(W3-0 설계 §2).

**플래그 켜기 전 점검** (`w_entity_revision_enabled`·`w_upload_proposals_enabled`)
- [x] 한 자료에 HOT/ICE 가 함께 나오면 규격 없음 slot 으로 들어간다. — W3-0 §3-1: 원장 단계에서 규격별 두 사실로 나눈다(`api/app/ingest/variant_split.py`).
- [x] 연결·같은 대상 후보 처리량이 매장 advisory lock 하나에 묶인다. — W3-0 §3-5 측정: `docs/dev/review/W3_0_THROUGHPUT_<측정일>.md`.
- [x] 호출 경로를 붙이기 전에 `import_legacy_correction` 적용 순서(위 항목)를 먼저 고친다. — W3-0 §3-2.
- [x] 두 플래그를 모두 켜고 구간을 동시에 처리하는 합성 종단 검증을 한 번 돌린다. — W3-0 §3-6: `api/scripts/verify_w3_flag_readiness.py`(재구축 검증이 부른다).
- 배포판 켜기 절차: `docs/dev/plan/W3_0_FLAG_ROLLOUT.md` (사용자 실행).
```

(위 블록의 `<측정일>` 은 Task 5 에서 만든 파일 이름의 날짜로 바꿔 쓴다.)

- [ ] **Step 3: DEV_TODO 갱신** — `docs/dev/DEV_TODO_CURRENT.md` 의 `## W3. 사실 참조로 카드 조립·검수 — 구 13.3-1b~1c·13.4~13.5` 줄 다음 빈 줄 뒤, 첫 `- [ ]` 줄 앞에 추가:

```markdown
- [x] W3-0 플래그 켜기 준비(설계 `docs/dev/plan/W3_0_FLAG_READINESS_DESIGN.md`, 계획 `docs/dev/plan/W3_0_FLAG_READINESS_PLAN.md`): HOT/ICE 동시 사실 원장 나누기, legacy 정정 순서, 병합 뒤 후보·제안 정리·같은 순위 `matched_cards` 갱신, 두 플래그 합성 종단 검증, 처리량 기록, 점주 답변 삭제 경로 확인. **남은 것: 배포판 플래그 켜기는 사용자가 `docs/dev/plan/W3_0_FLAG_ROLLOUT.md` 로 한다. 다음은 W3a(대상 단위 사실 조립).**
```

- [ ] **Step 4: 마감 검증 — 전부 다시 돌린다**

```bash
cd /Users/chabee/new/New_Source/2026unithon-w3/api && $PY -B -m pytest -q -p no:cacheprovider tests
```
Expected: `1767 passed, 4 xfailed`.

```bash
cd /Users/chabee/new/New_Source/2026unithon-w3 && python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest api/app/cards api/app/publish
```
Expected: `위반 15건`(기존분만).

Global 의 docker run → `verify_r_schema_rebuild.py` → docker stop.
Expected: `PASS W3-0 flag readiness all scenarios`, `PASS W entity revision all scenarios`, 이어지는 W 공개·R 검증까지 예외 없이 끝남.

문서 금지어 확인(실제 브랜드·상호·서비스명 혼용이 없는지):

```bash
cd /Users/chabee/new/New_Source/2026unithon-w3 && git status --short | awk '{print $2}' | xargs grep -nE "Relay|유니쉐프" || echo "금지 서비스명 없음"
```
Expected: `금지 서비스명 없음`. 새 파일의 대상 이름은 `음료Z`·`합성음료*`·`측정메뉴*` 같은 합성 이름뿐이다.

- [ ] **Step 5: 변경 확인, 커밋하지 않는다**

Run: `git -C /Users/chabee/new/New_Source/2026unithon-w3 status --short && git -C /Users/chabee/new/New_Source/2026unithon-w3 diff --stat`
Expected: 이 계획의 File Structure 표에 있는 파일만 바뀌거나 새로 생겼다. `git add`·`commit`·`push` 를 하지 않는다. 사용자에게 변경 요약·검증 결과(통과 수, 재구축 PASS, 격리 15건, 처리량 기록 경로)·브랜치 이름 `w/w3-fact-assembly` 만 보고한다.

---

## Self-Review

### Spec coverage

| 설계 절 | 내용 | Task |
|---|---|---|
| §1 완료 조건 1 | §3 구현 + 단위·실제 DB 통과 | Task 1~4, Task 6 Step 4 |
| §1 완료 조건 2 | 두 플래그 합성 종단 검증 실제 DB 통과 | Task 4 |
| §1 완료 조건 3 | 처리량 기록 `docs/dev/review/` | Task 5 |
| §1 완료 조건 4 | 켜기 절차 문서(실행은 사용자) | Task 6 Step 1 |
| §2 소급 이관 안 함 | 결정 기록 | Task 6 Step 2·Step 1 머리 |
| §3-1 HOT/ICE 나누기 | 대상·결과·local_ref·requires 둘 다·같은 occurrence·check_flags 표시·사이즈 미분할·플래그 뒤 | Task 1 (종단 Task 4 T2·T8) |
| §3-2 legacy 정정 순서 | head 가 EXTRACTION 아니면 None·로그, 멱등 유지 | Task 2 (종단 Task 4 T7) |
| §3-3-1 병합 후보 | keep 쪽으로 다시 걸기/이미 있으면 MERGED 로 닫기, 이력 | Task 3 (+migration), 종단 T5 |
| §3-3-2 병합 뒤 제안 | 병합 사슬 끝으로 찾기, PENDING 제안 옮기기·이력, 결정된 제안 불변 | Task 3, 종단 T5 |
| §3-3-3 같은 순위 matched_cards | PENDING 제안 같은 순위 갱신 | Task 3, 종단 T3 |
| §3-4 점주 답변 삭제 경로 | 코드 변경 없이 W_NEXT_PLAN·인계 문서 8번에 기록 | Task 4 Step 4·5 |
| §3-5 처리량 | 연결 시간·lock 보유·후보 계산·동시 2 대기, 합격선 없음, 스크립트 `api/scripts/` | Task 5 |
| §3-6 종단 1~8 | 구간 2 동시·HOT/ICE·충돌·재처리·병합·분리·정정·끄기 | Task 4 T1~T8 |
| §3-7 켜기 절차 | migration 조회문, env 파일 위치·값 이름·의존, 켠 뒤 확인, 되돌리기 | Task 6 Step 1 |
| §4 하지 않는 것 | 소급·W3a·W3b·사이즈 나누기·배포 값 변경·유료 실행·R 파일 | Global Constraints |
| §5 제약 | 격리·가산 migration·플래그 꺼짐 불변·한국어·고유명 금지·커밋은 사용자 | Global Constraints, 각 Task 검증 |

### Placeholder scan

- 코드 블록에 `TBD`·"적절히 처리"·"Task N 과 같이" 없음. 모든 새 함수·테스트는 실제 본문을 담았다.
- 남는 꺾쇠 표기는 두 종류뿐이다: (1) 처리량 기록 문서 틀의 `<측정일>`·`…` — Task 5 Step 6 이 Step 5 측정 출력으로 채우라고 명시(채우지 못하면 Task 미완료), (2) 사용자 실행 문서의 `\set source_id <고른 source_id>` — 운영 DB 에서 사용자가 고르는 입력값.

### Type consistency

- `split_hot_ice(list) -> list`, `split_refs(str) -> tuple[str, str]`, `split_ref(str, str) -> str` — Task 1 구현·테스트·`pipeline._ledger_keys` 가 같은 이름·모양을 쓴다. 갈라진 이름표 `f1~HOT`·`f1~ICE` 는 단위 테스트·종단 T2 가 같다.
- check_flags 표시 dict `{"field": "variant", "verdict": "VARIANT_SPLIT", "value": <원래 variant>, "variant_split": "HOT_ICE", "from_ref": <원래 ref>}` — Task 1 구현·단위 테스트·종단 T2 가 같다.
- `import_legacy_correction` 서명 불변, 새 조회문 `select change_kind from fact_revision_meta where store_id = $1 and fact_revision_id = $2` — 구현과 FakeConn 열쇠가 같은 문자열.
- `_rehome_candidates` 조회문 조각 `and status = 'PENDING' and $2 in (entity_id_low, entity_id_high)`, 닫기 조각 `update knowledge_entity_candidates set status = 'MERGED'` — 구현과 테스트가 같다. 이력 payload 키(`from_candidate_id`, `to_candidate_id`, `merged_entity_id`, `outcome`) 동일.
- `_adopt_merged_proposals(conn, store_id, source_id) -> int`, 이력 payload(`proposal_id`, `source_id`, `outcome`, `into_proposal_id`) — 구현·`_AdoptConn` 테스트·종단 T5 가 같다. `_follow_merged` 의 `fetchrow` 조각 `from knowledge_entities` 를 `_ProposalConn`·`_AdoptConn` 이 처리한다.
- migration 이 허용하는 값(`MERGED`, `CANDIDATE_MOVED`, `PROPOSAL_MOVED`)과 코드가 쓰는 값이 같다. 제약 이름은 로컬 Supabase DB 의 `pg_constraint` 에서 확인한 실제 이름(`knowledge_entity_candidates_status_check`, `knowledge_entity_events_action_check`)이다.
- 기존 테스트 영향 확인: `test_merge_relinks_…`(PENDING 후보 조회가 빈 목록 → 쓰기·이력 순서 불변), `_ProposalConn` 보강 뒤 결정 J 두 테스트, `test_legacy_import_appends_revision_with_legacy_fields`(head 종류 응답 추가), 실제 DB P4(같은 값이면 `updated_at` 불변)·S2(MERGE payload 불변)·S3(병합은 제안을 쓰지 않음)·V3(EXTRACTION head 이관).
- 단위 테스트 수: 1735 → Task 1 +20 → Task 2 +5 → Task 3 +5 → Task 5 +2 = 1767.
