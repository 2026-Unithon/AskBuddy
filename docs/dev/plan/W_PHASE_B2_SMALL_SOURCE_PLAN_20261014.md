# Phase B 추가 — 작은 자료 호출 줄이기 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 작은 자료에서 모델 호출을 줄인다. 한 작업에 올린 여러 자료는 묶어서 한 번만 분류한다. 훑기가 자료 전체를 다 담은 작은 자료는 분류와 추출을 한 호출로 합친다(설정 스위치, 기본 꺼짐). 실제 효과는 원가 원장으로 잰다.

**Architecture:** 훑기 결과(`ProbeResult`)에 "자료 전체를 담았는가"(`complete`) 표시를 더한다. 이 값은 용량이 아니라 코드가 읽은 실제 내용(글자 수·쪽 수)으로 정한다.
- **묶어 분류:** `job_worker` 가 자료를 처리하기 전에, 판정이 없는 자료가 둘 이상이면 점주 답변 묶음과 같은 방식으로 분류 1회에 판정을 저장한다. 그러면 `process_source` 는 저장된 판정을 재사용한다.
- **한 호출:** 자료가 혼자이고 `complete` 이며 스위치가 켜져 있으면, `route_source` 가 분류하지 않고 "한 호출 대기"를 돌려준다. `process_source` 는 추출 프롬프트에 용도 판정 칸을 더한 한 호출로 사실과 판정을 함께 받는다.

**Tech Stack:** FastAPI·asyncpg·pydantic v2, Gemini(`extract/gemini.py`), 기존 Phase B intake 모듈.

**Spec:** 사용자 결정(2026-10-11·10-14 대화) — 아래 "결정" 표가 정본이다. 바탕 설계는 `docs/dev/plan/W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md`(§9 포함)이고, 앞선 계획은 `docs/dev/plan/W_PHASE_B_PLAN_20261011.md` 이다.

## 결정 (2026-10-14 사용자 대화)

| # | 결정 |
|---|---|
| S1 | 한 작업에 올린 여러 자료는 **묶어서 분류 1회**. 묶음 상한(자료 수·글자·그림)을 넘으면 나눈다 |
| S2 | "작은 자료"는 **용량이 아니라 내용으로** 판별한다 — 훑기 표본이 자료 전체를 다 담았는가(글: 전체 글이 표본 상한 안, 사진: 1쪽). 코드가 무료로 정한다 |
| S3 | 자료가 하나뿐이고 작은 자료면 **분류와 추출을 한 호출**로 합친다. 무관 판정·공지 보류는 그대로 유지한다. **설정 스위치(기본 꺼짐)**, 평가 뒤에 켠다 |
| S4 | 음성·영상은 이번 범위가 아니다(훑기 STT 를 본 추출에 재사용하지 않는 계획 P3 를 유지한다) |
| S5 | 측정: 원가 원장에서 단계별(분류·추출·조립·STT) 호출과 비용, 작은 자료 비중, 묶음·한 호출 사용 수를 보는 보고 스크립트 |

## Global Constraints

- 저장소 `CLAUDE.md` 가 우선한다. 주석·프롬프트·문서는 한국어로 쓴다.
- **git commit·git add(실제 인덱스)·push 를 하지 않는다.** 작업 트리에만 둔다.
- 매장 격리: 모든 DB 함수는 `store_id` 를 필수로 받고, 모든 조회는 `store_id` 로 좁힌다. `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/ingest api/app/cards api/app/checklist api/app/publish` 결과 새 위반 0(기존 `repository.py` 15건 제외).
- 모델 호출 중에는 DB 연결을 쥐지 않는다. 분류 실패를 조용히 다른 로직으로 보내지 않는다.
- **스위치가 꺼져 있으면 추출 요청이 지금과 바이트 단위로 같다(D16).** 기존 `extract_facts.ko.txt`·응답 스키마는 바꾸지 않는다. 한 호출은 새 프롬프트 꼬리 파일과 새 스키마로만 만든다.
- 모델명·상한은 `config.py`, 프롬프트는 `api/prompts/` 에 둔다. 원장 단계 이름은 기존 값만 쓴다(`CLASSIFY`·`EXTRACT`).
- 유료 호출(`INGEST_MODE=real` 실행·실모델 평가)은 사용자 승인 없이 하지 않는다. 승인된 실행은 실행별 토큰·USD 를 남긴다.
- R 소유 앱 파일과 `api/app/contracts/*` 는 바꾸지 않는다. migration 은 만들지 않는다(필요하면 멈추고 보고한다).
- 평가용 실제 자료의 브랜드·상호·메뉴 고유명을 어디에도 쓰지 않는다(`음료Z`·`합성매장` 같은 합성 이름만).
- API 테스트: `cd api && .venv/bin/python -m pytest -q <경로>`. 시작 기준은 `2387 passed, 6 skipped, 4 xfailed`(후속 1 반영 뒤)다. 실제 숫자는 Task 1 Step 1 에서 다시 잰다.

## Review Focus

1. **묶음 분류가 실패해도 작업은 멈추지 않는다.** 그 묶음의 자료는 판정 없이 남고, `process_source` 가 자료마다 다시 분류한다(로직을 추정해 보내지 않는다). Task 3 테스트로 고정한다.
2. **한 호출에서 무관(NONE) 판정이 나오면 뽑은 사실을 원장에 적지 않는다.** 작업은 `INTAKE_NONE` 이다. Task 5 테스트로 고정한다.
3. **한 호출 뒤 재시도·복구는 분류도 한 호출도 다시 부르지 않는다.** 저장된 판정으로 보통 추출 경로를 탄다. Task 5 테스트로 고정한다.
4. **스위치가 꺼져 있거나 자료가 크면 지금과 같다.** 한 호출 프롬프트는 쓰이지 않고, `route_source` 는 지금처럼 분류해 저장한다. Task 5 테스트로 고정한다.
5. **묶음 안에서 점주 칩은 자기 자료에만 가산된다.** 다른 자료의 칩이 결정을 바꾸지 않는다. Task 2 테스트로 고정한다.

---

## 파일 구조

| 파일 | 책임 | Task |
|---|---|---|
| `api/app/config.py` (가산) | 묶음·한 호출 설정 | 1 |
| `api/app/ingest/intake/ir.py` | `ProbeResult.complete` | 1 |
| `api/app/ingest/intake/probe_text.py`·`probe_media.py` | `complete` 채우기 | 1 |
| `api/app/ingest/intake/route.py` | `complete`(카톡 캡처), `single_call_eligible`, `_classify_bundle`, `bundle_chunks`, `route_job_bundle`, `SingleCallPending`, `classify_and_save`, `extract_with_intake`, `single_call_route` | 1·2·3·5 |
| `api/app/ingest/intake/classify.py` | 자료별 칩 표시(`candidate_hints`) | 2 |
| `api/app/ingest/job_worker.py` | 처리 전 묶음 분류, 캐시 전달 | 3 |
| `api/app/ingest/pipeline.py` | `intake_cache` 인자, 한 호출 경로, `_extract_facts_all(prefetched=)` | 3·5 |
| `api/app/ingest/schemas.py` | `IntakeRank`·`IntakeFactExtractionResult`·`IntakeLocatedFactExtractionResult` | 4 |
| `api/prompts/extract_facts_intake_suffix.ko.txt` (신규) | 한 호출 꼬리 지시문 | 4 |
| `api/app/ingest/extract/__init__.py`·`gemini.py`·`mock.py` | `extract_facts_with_intake` | 4 |
| `api/scripts/run_intake_classifier_eval.py` | `--single-call` 모드 | 6 |
| `api/scripts/intake_cost_report.py`·`api/app/usage/intake_report.py` (신규) | 측정 보고 | 7 |
| `api/scripts/verify_w_intake.py` | i-15~i-17 | 7 |
| 문서 | 설계 §9-3, 로드맵, 이 계획 실행 기록 | 7 |

---

### Task 1: 설정 · 훑기 "자료 전체를 담았는가"

**Files:**
- Modify: `api/app/config.py` (Phase B `intake_*` 블록 아래 가산)
- Modify: `api/app/ingest/intake/ir.py` (`ProbeResult`)
- Modify: `api/app/ingest/intake/probe_text.py`
- Modify: `api/app/ingest/intake/probe_media.py` (`probe_doc_image`)
- Modify: `api/app/ingest/intake/route.py` (`probe_source` 의 카톡 캡처 분기, `single_call_eligible`)
- Test: `api/tests/test_wb2_probe_complete.py`

**Interfaces:**
- Produces:
  - `ProbeResult(normalizer: str, candidates: tuple[Candidate, ...], complete: bool = False)`. `summary()` 에 `"complete": bool` 이 더해진다. `sample_hash()` 는 바꾸지 않는다.
  - `route.SINGLE_CALL_NORMALIZERS = frozenset({"DOC_TEXT", "CHAT", "DOC_IMAGE"})`
  - `route.single_call_eligible(probe: ProbeResult, settings) -> bool`
  - 설정: `intake_bundle_enabled: bool = True`, `intake_bundle_max_sources: int = Field(default=8, ge=2)`, `intake_bundle_max_chars: int = Field(default=12000, ge=1000)`, `intake_bundle_max_images: int = Field(default=12, ge=1)`, `intake_single_call_small: bool = False`

- [ ] **Step 1: 기준선을 잰다.** `cd api && .venv/bin/python -m pytest -q tests 2>&1 | tail -3` 를 돌리고 결과를 보고서에 적는다.

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# api/tests/test_wb2_probe_complete.py
"""Phase B 추가 S2 — '작은 자료'는 용량이 아니라 훑기가 내용 전체를 담았는지로 정한다."""
import asyncio
from types import SimpleNamespace as NS

from PIL import Image

from app.config import Settings
from app.ingest.intake import grouping, probe_media, probe_text, route
from app.ingest.intake.ir import Candidate, Locator, ProbeResult


def _groups(*texts):
    return grouping.group_pdf_pages([(i, f"[{i}쪽]\n{t}") for i, t in enumerate(texts, 1)],
                                    max_sections=12)


def test_short_text_is_complete():
    probe = probe_text.probe_groups("DOC_TEXT", _groups("음료Z 샷 2", "마감 청소"),
                                    budget_chars=3000)
    assert probe.complete is True
    assert probe.summary()["complete"] is True


def test_text_over_budget_is_not_complete():
    probe = probe_text.probe_groups("DOC_TEXT", _groups("가" * 2000, "나" * 2000),
                                    budget_chars=3000)
    assert probe.complete is False


def test_owner_text_is_complete():
    assert probe_text.probe_owner_text("시럽 어디?", "창고 2번 선반").complete is True


def test_single_image_complete_multi_page_not(tmp_path):
    img = tmp_path / "p.jpg"
    Image.new("RGB", (100, 100)).save(img)
    one = asyncio.run(probe_media.probe_doc_image(img, tmp_path, max_images=6, px=512,
                                                  max_sections=12, page_count=1))
    many = asyncio.run(probe_media.probe_doc_image(
        tmp_path / "s.pdf", tmp_path, max_images=6, px=512, max_sections=12, page_count=3,
        render=lambda path, index, dpi: Image.new("RGB", (100, 100))))
    assert one.complete is True and many.complete is False


def test_default_is_not_complete():
    assert ProbeResult("AUDIO", (Candidate("c1", Locator("TIME", "0", "20"), "말"),)).complete is False


def _settings(**kw):
    return Settings(_env_file=None).model_copy(update=kw)


def test_eligible_needs_switch_complete_and_normalizer():
    small = ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "글"),),
                        complete=True)
    assert route.single_call_eligible(small, _settings(intake_single_call_small=False)) is False
    assert route.single_call_eligible(small, _settings(intake_single_call_small=True)) is True
    big = ProbeResult("DOC_TEXT", small.candidates, complete=False)
    assert route.single_call_eligible(big, _settings(intake_single_call_small=True)) is False
    audio = ProbeResult("AUDIO", small.candidates, complete=True)
    assert route.single_call_eligible(audio, _settings(intake_single_call_small=True)) is False


def test_layout_scan_is_never_single_call():
    img = ProbeResult("DOC_IMAGE", (Candidate("c1", Locator("PAGE", "1", "1"), ""),),
                      complete=True)
    s = _settings(intake_single_call_small=True, scan_extract_mode="LAYOUT")
    assert route.single_call_eligible(img, s) is False


def test_config_defaults():
    s = Settings(_env_file=None)
    assert (s.intake_bundle_enabled, s.intake_bundle_max_sources, s.intake_bundle_max_chars,
            s.intake_bundle_max_images, s.intake_single_call_small) == (True, 8, 12000, 12, False)
```

`Settings.model_copy(update={"scan_extract_mode": "LAYOUT"})` 는 검증기를 다시 돌리지 않으므로 real 모드 금지 검사에 걸리지 않는다. 걸리면 `ingest_mode="mock"` 을 함께 넣는다.

- [ ] **Step 3: 실패를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb2_probe_complete.py` → `complete` 속성 없음.

- [ ] **Step 4: 구현한다.**

`ir.py`:

```python
@dataclass(frozen=True)
class ProbeResult:
    normalizer: str
    candidates: tuple[Candidate, ...]
    # 표본이 자료 내용 전체를 담았는가(Phase B 추가 S2). 용량이 아니라 읽은 내용으로 정한다
    complete: bool = False
```

`summary()` 의 dict 끝에 `"complete": self.complete` 를 더한다.

`probe_text.probe_groups`:

```python
def probe_groups(normalizer: str, groups: Sequence[Group], *, budget_chars: int) -> ProbeResult:
    per = max(1, budget_chars // max(1, len(groups)))
    candidates, complete = [], True
    for g in groups:
        full = "\n".join(g.units)
        if len(full) > per:
            complete = False
        candidates.append(Candidate(g.candidate_id, g.locator, full[:per]))
    return ProbeResult(normalizer, tuple(candidates), complete=complete)
```

`probe_owner_text`: `ProbeResult("OWNER_TEXT", (...), complete=True)`.

`probe_media.probe_doc_image`: 반환 직전 `complete=(page_count == 1)` 을 넘긴다. `probe_audio`·`probe_video` 는 바꾸지 않는다(기본 False, S4).

`route.probe_source` 카톡 캡처 분기: `ProbeResult("CHAT", tuple(...), complete=True)`. mock 분기와 저장 전사문 분기는 기본값(False)을 그대로 둔다. mock 흐름은 바뀌지 않는다.

`route.py`:

```python
# 한 호출(분류+추출) 대상 정규화기 — 음성·영상은 이번 범위가 아니다(S4)
SINGLE_CALL_NORMALIZERS = frozenset({"DOC_TEXT", "CHAT", "DOC_IMAGE"})


def single_call_eligible(probe: ProbeResult, settings) -> bool:
    """작은 자료(훑기가 내용 전체를 담음)를 한 호출로 처리하는가. 스위치가 꺼져 있으면 늘 False."""
    if not getattr(settings, "intake_single_call_small", False):
        return False
    if not probe.complete or probe.normalizer not in SINGLE_CALL_NORMALIZERS:
        return False
    # 구역(LAYOUT) 스캔은 다단계 추출이라 한 호출로 합칠 수 없다
    if probe.normalizer == "DOC_IMAGE" and getattr(settings, "scan_extract_mode", "SINGLE") == "LAYOUT":
        return False
    return True
```

`config.py` 의 Phase B 블록 아래에 넣는다:

```python
    # ── Phase B 추가 — 작은 자료 호출 줄이기(S1·S3) ──
    # 한 작업의 판정 없는 자료가 둘 이상이면 묶어 분류 1회. 상한을 넘으면 묶음을 나눈다
    intake_bundle_enabled: bool = True
    intake_bundle_max_sources: int = Field(default=8, ge=2)
    intake_bundle_max_chars: int = Field(default=12000, ge=1000)
    intake_bundle_max_images: int = Field(default=12, ge=1)
    # 홀로 남은 작은 자료(훑기가 전체를 담음)는 분류+추출 한 호출. 평가 뒤 켠다(기본 꺼짐)
    intake_single_call_small: bool = False
```

- [ ] **Step 5: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb2_probe_complete.py tests/test_wb_intake_probe_text.py tests/test_wb_intake_probe_media.py tests/test_wb_intake_registry.py` → 전부 통과(기존 `summary()` 단언이 dict 전체를 비교하면 `complete` 키 때문에 깨진다. 그 단언에 `"complete": False` 를 더하고 보고서에 적는다).
- [ ] **Step 6: 변경 확인.** `git status --short`

---

### Task 2: 묶음 분류 공용 함수 · 자료별 칩 표시

**Files:**
- Modify: `api/app/ingest/intake/classify.py` (`render_prompt`·`classify` 에 `candidate_hints`)
- Modify: `api/app/ingest/intake/route.py` (`_classify_bundle` 추출, `route_owner_answer` 가 그것을 쓰게)
- Test: `api/tests/test_wb2_bundle_classify.py`

**Interfaces:**
- Consumes: `_prefixed`, `_split_outcome`, `decide_all`, `source_decision`, `records.save_decision`
- Produces:
  - `classify.render_prompt(probes, *, hints, context, candidate_hints: Mapping[str, Sequence[str]] | None = None)`. `candidate_hints` 는 (접두어 포함) 후보 id → 그 자료의 칩이다. 그 후보 머리줄 끝에 ` [점주 선택: RECIPE, NOTICE]` 를 붙인다.
  - `classify.classify(probes, *, hints, context, usage_sink, usage_context, candidate_hints=None)`
  - `async route._classify_bundle(pool, store_id: int, items: Sequence[tuple[int, ProbeResult, tuple[str, ...]]], *, context: str | None, global_hints: Sequence[str], usage_sink, ctx, entry: str, owner_answer_id: int | None) -> dict[int, StoredRoute]`. 분류 1회, 자료별 결정(그 자료 칩만 가산), 한 트랜잭션 저장.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# api/tests/test_wb2_bundle_classify.py
"""Phase B 추가 S1 — 묶음 분류 공용 함수. 칩은 자기 자료에만 가산(Review Focus 5)."""
import asyncio
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.ingest.intake import classify, route
from app.ingest.intake.classify import ClassifyOutcome
from app.ingest.intake.decide import Ranked
from app.ingest.intake.ir import Candidate, Locator, ProbeResult


def _probe(text):
    return ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), text),),
                       complete=True)


def test_prompt_marks_candidate_hints():
    prompt, _ = classify.render_prompt(
        [route._prefixed(5, _probe("음료Z 샷 2")), route._prefixed(6, _probe("마감"))],
        hints=(), context=None, candidate_hints={"s5:c1": ("RECIPE", "NOTICE")})
    assert "### s5:c1 (DOC_TEXT PAGE 1~1) [점주 선택: RECIPE, NOTICE]" in prompt
    assert "### s6:c1 (DOC_TEXT PAGE 1~1)\n" in prompt


class _Lease:
    async def __aenter__(self):
        conn = AsyncMock()
        conn.transaction = lambda: _Tx()
        return conn

    async def __aexit__(self, *exc):
        return False


class _Tx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def acquire(self):
        return _Lease()


def test_bundle_one_call_hints_only_boost_own_source():
    # 두 자료 모두 모델은 RECIPE .45 / PROCEDURE .40 — 5번 자료만 PROCEDURE 칩
    outcome = ClassifyOutcome(
        {"s5:c1": [Ranked("RECIPE", 0.45), Ranked("PROCEDURE", 0.40)],
         "s6:c1": [Ranked("RECIPE", 0.45), Ranked("PROCEDURE", 0.40)]},
        {"sections": []}, "gemini-3.6-flash", "abcd")
    saves = []

    async def save(conn, store_id, **kw):
        saves.append(kw)
        return 100 + len(saves)

    cls = AsyncMock(return_value=outcome)
    with patch.object(route.classify, "classify", cls), \
         patch.object(route.records, "save_decision", side_effect=save), \
         patch.object(route, "get_settings", return_value=Settings(_env_file=None)):
        routes = asyncio.run(route._classify_bundle(
            _Pool(), 7, [(5, _probe("가"), ("PROCEDURE",)), (6, _probe("나"), ())],
            context=None, global_hints=(), usage_sink=None, ctx=None, entry="UPLOAD",
            owner_answer_id=None))
    cls.assert_awaited_once()
    assert cls.await_args.kwargs["candidate_hints"] == {"s5:c1": ("PROCEDURE",)}
    assert routes[5].source.logic == "PROCEDURE" and routes[6].source.logic == "RECIPE"
    assert [s["entry"] for s in saves] == ["UPLOAD", "UPLOAD"]
    assert routes[5].decisions[0].candidate_id == "c1"  # 저장 판정은 접두어 없음
```

- [ ] **Step 2: 실패를 확인한다.** → `candidate_hints` 인자·`_classify_bundle` 없음.

- [ ] **Step 3: 구현한다.**

`classify.render_prompt` 의 후보 머리줄 한 줄을 바꾼다:

```python
            mark = ""
            if candidate_hints and candidate_hints.get(c.candidate_id):
                mark = f" [점주 선택: {', '.join(candidate_hints[c.candidate_id])}]"
            lines.append(f"### {c.candidate_id} ({probe.normalizer} {loc.kind} {loc.start}~{loc.end}){mark}")
```

`classify.classify` 는 `candidate_hints` 를 받아 `render_prompt` 에 넘긴다. mock 결과(`mock_sections`)는 그대로다.

`route._classify_bundle`:

```python
async def _classify_bundle(pool, store_id: int,
                           items: Sequence[tuple[int, ProbeResult, tuple[str, ...]]], *,
                           context: str | None, global_hints: Sequence[str], usage_sink, ctx,
                           entry: str, owner_answer_id: int | None) -> dict[int, StoredRoute]:
    """여러 자료를 분류 1회로 판정한다. 후보 id 는 `s{source_id}:` 로 묶고, 결정은 자료마다
    그 자료의 칩만 가산한다. 모든 자료가 판정된 뒤 한 트랜잭션으로 저장한다(함께 남거나 함께 없다).
    분류 실패는 IntakeClassificationError 로 올라간다."""
    candidate_hints = {f"s{sid}:{c.candidate_id}": hints
                       for sid, probe, hints in items if hints for c in probe.sampled()}
    outcome = await classify.classify(
        [_prefixed(sid, probe) for sid, probe, _ in items], hints=tuple(global_hints),
        context=context, usage_sink=usage_sink, usage_context=ctx,
        candidate_hints=candidate_hints or None)
    th = Thresholds.from_settings(get_settings())
    registered = registry.registered_logics()
    decided = []
    for sid, probe, hints in items:
        own = _split_outcome(outcome, sid)
        decisions = decide_all(probe.candidates, own.model_sections, hints=hints, th=th,
                               registered=registered)
        decided.append((sid, probe, hints, own, decisions,
                        source_decision(decisions, hints=hints, th=th, registered=registered)))
    routes: dict[int, StoredRoute] = {}
    async with pool.acquire() as conn, conn.transaction():
        for sid, probe, hints, own, decisions, source in decided:
            decision_id = await records.save_decision(
                conn, store_id, source_id=sid, entry=entry, owner_answer_id=owner_answer_id,
                probe=probe, owner_hints=hints, outcome=own, decisions=decisions, source=source,
                logical_call_id=ctx.logical_call_id if ctx else None)
            routes[sid] = StoredRoute(decision_id, probe.normalizer, list(decisions), source)
    return routes
```

`route_owner_answer` 의 "분류 호출 → 결정 → 저장" 부분을 `_classify_bundle(pool, store_id, [(sid, probes[sid], hints_of[sid]) for sid in missing], context=f"직원 질문: {question}", global_hints=tuple(attachment_hints), usage_sink=usage_sink, ctx=ctx, entry="OWNER_ANSWER", owner_answer_id=owner_answer_id)` 호출로 바꾸고, 결과를 `routes` 에 합친다. 동작은 같다. 자료별 칩 표시가 프롬프트에 더해지는 것만 다르다.

- [ ] **Step 4: 통과를 확인한다.** `cd api && .venv/bin/python -m pytest -q tests/test_wb2_bundle_classify.py tests/test_wb_intake_classify.py tests/test_wb_owner_answer_intake.py` → 전부 통과. 기존 점주 답변 테스트의 단언은 바꾸지 않는다.
- [ ] **Step 5: 변경 확인.** `git status --short`

---

### Task 3: 작업 묶음 분류 (job_worker)

**Files:**
- Modify: `api/app/ingest/intake/route.py` (`bundle_chunks`, `route_job_bundle`)
- Modify: `api/app/ingest/job_worker.py` (`process_ingest_job`)
- Modify: `api/app/ingest/pipeline.py` (`process_source(..., intake_cache=None)`)
- Test: `api/tests/test_wb2_job_bundle.py`

**Interfaces:**
- Consumes: `_classify_bundle`(Task 2), `probe_source`, `records.latest_decision`·`source_owner_hints`, `repo.get_source`
- Produces:
  - `route.bundle_chunks(items: Sequence[tuple[int, ProbeResult, tuple[str, ...]]], *, max_sources: int, max_chars: int, max_images: int) -> list[list[tuple[...]]]` — 순서를 지키며 탐욕적으로 나눈다.
  - `async route.route_job_bundle(pool, store_id: int, *, job_id: int, source_ids: Sequence[int], usage_sink, usage_base: tuple, caches: dict[int, IntakeCache]) -> dict[int, StoredRoute]`
  - `pipeline.process_source(..., intake_cache: "IntakeCache | None" = None)` — 주면 그 캐시를 쓴다(다운로드·파싱 재사용).

**규칙:**
- `intake_bundle_enabled` 가 꺼져 있으면 아무것도 하지 않는다.
- 판정이 없는 자료가 둘 미만이면 아무것도 하지 않는다(홀로 남은 자료는 `process_source` 가 단독 분류 또는 한 호출을 한다).
- 훑기에 실패한 자료(`UnsupportedDocument` 등)는 묶음에서 빼고 경고만 남긴다. 그 자료는 `process_source` 에서 지금처럼 실패한다.
- 묶음이 1개짜리로 남으면 묶지 않는다.
- 묶음 분류가 실패하면(`IntakeClassificationError` 등 모든 예외) 경고를 남기고 그 묶음은 판정 없이 둔다. 작업은 이어간다(Review Focus 1).
- 원장 문맥은 `pipeline._ctx_for(usage_base, 묶음 첫 source_id, "CLASSIFY", segment_id=f"bundle{n}")` 이다.
- job_worker 는 PARTIAL 재시도 자료(`failed_segment_ids` 있음)를 묶음에서 뺀다(판정이 이미 있다).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# api/tests/test_wb2_job_bundle.py
"""Phase B 추가 S1 — 한 작업의 판정 없는 자료를 묶어 분류 1회. 실패해도 작업은 이어간다."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.ingest.intake import route
from app.ingest.intake.decide import IntakeClassificationError
from app.ingest.intake.ir import Candidate, Locator, ProbeResult


def _probe(chars, images=0):
    imgs = tuple(f"/tmp/i{i}.jpg" for i in range(images))
    return ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "가" * chars,
                                              imgs),), complete=True)


def test_bundle_chunks_respects_limits_in_order():
    items = [(1, _probe(5000), ()), (2, _probe(5000), ()), (3, _probe(5000), ()),
             (4, _probe(10), ())]
    chunks = route.bundle_chunks(items, max_sources=8, max_chars=12000, max_images=12)
    assert [[i[0] for i in c] for c in chunks] == [[1, 2], [3, 4]]
    chunks = route.bundle_chunks(items, max_sources=2, max_chars=10**9, max_images=12)
    assert [[i[0] for i in c] for c in chunks] == [[1, 2], [3, 4]]


class _Lease:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def acquire(self):
        return _Lease()


BASE = (7, 3, "REGISTRATION", "PRODUCT", None, 42)


def _run(source_ids, *, stored=(), probe_fail=(), bundle_error=None, **settings):
    calls = []

    async def latest(conn, store_id, sid):
        return object() if sid in stored else None

    async def get_source(conn, store_id, sid):
        return {"source_id": sid, "store_id": store_id, "source_type": "SCAN",
                "file_url": f"sources/7/scan/{sid}.docx"}

    async def probe(pool, store_id, src, **kw):
        if src["source_id"] in probe_fail:
            raise RuntimeError("훑기 실패")
        return _probe(10)

    async def bundle(pool, store_id, items, **kw):
        calls.append(([i[0] for i in items], kw["ctx"]))
        if bundle_error:
            raise bundle_error
        return {i[0]: f"route{i[0]}" for i in items}

    s = Settings(_env_file=None).model_copy(update=settings)
    caches = {}
    with patch.object(route.records, "latest_decision", side_effect=latest), \
         patch.object(route.records, "source_owner_hints", AsyncMock(return_value=())), \
         patch.object(route.repo, "get_source", side_effect=get_source), \
         patch.object(route, "probe_source", side_effect=probe), \
         patch.object(route, "_classify_bundle", side_effect=bundle), \
         patch.object(route, "get_settings", return_value=s):
        out = asyncio.run(route.route_job_bundle(_Pool(), 7, job_id=3, source_ids=source_ids,
                                                 usage_sink=None, usage_base=BASE,
                                                 caches=caches))
    return out, calls, caches


def test_three_new_sources_one_call():
    out, calls, caches = _run([11, 12, 13])
    assert [c[0] for c in calls] == [[11, 12, 13]]
    assert calls[0][1].stage == "CLASSIFY" and calls[0][1].logical_call_id.endswith(":bundle1")
    assert set(out) == {11, 12, 13} and set(caches) == {11, 12, 13}


def test_single_pending_source_is_left_alone():
    out, calls, _ = _run([11, 12], stored={12})
    assert calls == [] and out == {}


def test_probe_failure_drops_only_that_source():
    out, calls, _ = _run([11, 12, 13], probe_fail={12})
    assert [c[0] for c in calls] == [[11, 13]]


def test_bundle_failure_keeps_job_going():
    # Review Focus 1 — 묶음 실패는 예외로 올라오지 않고 판정 없이 둔다
    out, calls, _ = _run([11, 12], bundle_error=IntakeClassificationError("JSON"))
    assert out == {} and len(calls) == 1


def test_disabled_does_nothing():
    out, calls, _ = _run([11, 12, 13], intake_bundle_enabled=False)
    assert out == {} and calls == []
```

job_worker 연결 테스트도 같은 파일에 더한다. `tests.test_w3a_pipeline_wiring._worker` 대역을 쓰고, `route.route_job_bundle` 을 기록 대역으로 바꾼다.
- QUEUED 자료 3개(그중 1개는 `failed_segment_ids` 있음)이면 `source_ids` 가 나머지 2개다.
- `process_source` 가 `intake_cache=caches.get(source_id)` 로 불린다.
- `route_job_bundle` 이 예외를 올려도 작업은 각 자료를 처리한다.

`_worker` 의 `conn.fetch` 대역이 `failed_segment_ids` 를 돌려주게 바꿔야 하면 그 테스트 안에서만 바꾼다.

- [ ] **Step 2: 실패를 확인한다.**
- [ ] **Step 3: 구현한다.**

```python
def bundle_chunks(items, *, max_sources: int, max_chars: int, max_images: int):
    """순서를 지키며 상한(자료 수·글자·그림) 안에서 묶음을 나눈다."""
    chunks, current, chars, images = [], [], 0, 0
    for item in items:
        summary = item[1].summary()
        c, i = summary["chars"], summary["images"]
        if current and (len(current) >= max_sources or chars + c > max_chars
                        or images + i > max_images):
            chunks.append(current)
            current, chars, images = [], 0, 0
        current.append(item)
        chars += c
        images += i
    if current:
        chunks.append(current)
    return chunks


async def route_job_bundle(pool, store_id: int, *, job_id: int, source_ids: Sequence[int],
                           usage_sink, usage_base: tuple,
                           caches: dict[int, IntakeCache]) -> dict[int, StoredRoute]:
    """한 작업의 판정 없는 자료를 묶어 분류 1회(S1). 둘 미만이면 아무것도 하지 않는다.

    훑기 결과(다운로드·파싱)는 caches 에 둬 process_source 가 다시 쓴다. 묶음 분류가 실패하면
    그 묶음은 판정 없이 두고 경고만 남긴다 — process_source 가 자료마다 다시 분류한다
    (로직을 추정해 보내지 않는다). 작업은 멈추지 않는다.
    """
    from app.ingest import pipeline

    s = get_settings()
    if not s.intake_bundle_enabled:
        return {}
    pending = []
    async with pool.acquire() as conn:
        for sid in source_ids:
            if await records.latest_decision(conn, store_id, sid) is not None:
                continue
            row = await repo.get_source(conn, store_id, sid)
            if row is None:
                continue
            pending.append((sid, row, tuple(await records.source_owner_hints(conn, store_id, sid))))
    if len(pending) < 2:
        return {}
    # 여기부터 연결 없음 — 다운로드·STT·분류 모델 호출 중 DB 연결을 쥐지 않는다
    probed = []
    for sid, row, hints in pending:
        try:
            probe = await probe_source(pool, store_id, row, cache=caches.setdefault(sid, IntakeCache()),
                                       usage_sink=usage_sink, usage_base=usage_base)
        except Exception as exc:
            logger.warning("묶음 훑기 실패 — 그 자료는 따로 처리한다 job=%s source=%s %s: %s",
                           job_id, sid, type(exc).__name__, exc)
            continue
        probed.append((sid, probe, hints))
    routes: dict[int, StoredRoute] = {}
    chunks = bundle_chunks(probed, max_sources=s.intake_bundle_max_sources,
                           max_chars=s.intake_bundle_max_chars,
                           max_images=s.intake_bundle_max_images)
    for n, chunk in enumerate(chunks, start=1):
        if len(chunk) < 2:
            continue
        ctx = pipeline._ctx_for(usage_base, chunk[0][0], "CLASSIFY", segment_id=f"bundle{n}")
        try:
            routes.update(await _classify_bundle(
                pool, store_id, chunk, context=None, global_hints=(), usage_sink=usage_sink,
                ctx=ctx, entry="UPLOAD", owner_answer_id=None))
        except Exception as exc:
            logger.warning("묶음 분류 실패 — 자료마다 다시 분류한다 job=%s sources=%s %s: %s",
                           job_id, [c[0] for c in chunk], type(exc).__name__, exc)
    return routes
```

`job_worker.process_ingest_job`: 원래 `source_ids` 를 읽은 뒤, 루프 앞에 넣는다.

```python
    caches: dict = {}
    fresh = [int(r["source_id"]) for r in source_ids if not r["failed_segment_ids"]]
    if len(fresh) >= 2:
        from app.ingest.intake import route as intake_route
        from app.usage import DbUsageSink
        bundle_tag = int(time.time() * 1000)
        try:
            await intake_route.route_job_bundle(
                pool, store_id, job_id=job_id, source_ids=fresh,
                usage_sink=DbUsageSink(pool, resilient=True),
                usage_base=(store_id, job_id, "REGISTRATION", "PRODUCT", None, bundle_tag),
                caches=caches)
        except Exception:
            # 묶음은 비용 절감 장치다. 실패해도 자료마다 따로 판정하면 된다
            logger.exception("작업 묶음 분류 단계 실패 job=%s — 자료마다 처리한다", job_id)
```

두 `process_source` 호출 모두에 `intake_cache=caches.get(source_id)` 를 더한다. `time` 을 들여온다. `pipeline.process_source` 는 `intake_cache` 인자를 받고, 입구 블록의 `cache = intake_route.IntakeCache()` 를 `cache = intake_cache or intake_route.IntakeCache()` 로 바꾼다.

- [ ] **Step 4: 통과를 확인한다.** 새 파일과 `tests/test_w3a_pipeline_wiring.py tests/test_wb_intake_pipeline.py tests/test_ingest_job_partial.py` → 통과. 기존 `_run_worker` 같은 대역이 `route_job_bundle` 을 몰라 실제로 부르면(자료 1개짜리는 부르지 않는다), 그 테스트에서 명시적으로 patch 한다. 단언은 바꾸지 않는다.
- [ ] **Step 5: 격리 검사·변경 확인.**

---

### Task 4: 한 호출 추출기 (분류+추출)

**Files:**
- Modify: `api/app/ingest/schemas.py` (가산)
- Create: `api/prompts/extract_facts_intake_suffix.ko.txt`
- Modify: `api/app/ingest/extract/gemini.py` (`render_facts_intake_prompt`, `extract_facts_with_intake`. 기존 `extract_facts` 본문은 공용 내부 함수로 빼되 요청은 그대로 둔다)
- Modify: `api/app/ingest/extract/mock.py` (`extract_facts_with_intake`)
- Modify: `api/app/ingest/extract/__init__.py` (분기 함수)
- Test: `api/tests/test_wb2_single_call_extract.py`

**Interfaces:**
- Produces:
  - `schemas.IntakeRank(logic: Literal["RECIPE","PROCEDURE","POLICY","REFERENCE","NOTICE","NONE"], score: float[0,1])`
  - `schemas.IntakeFactExtractionResult(FactExtractionResult)` + `intake_ranking: list[IntakeRank] = []`, `intake_reason: str = ""`
  - `schemas.IntakeLocatedFactExtractionResult(LocatedFactExtractionResult)` + 같은 두 칸
  - `gemini.render_facts_intake_prompt(*, source_type, text, glossary, hints, locator_hints=False) -> str` = `render_facts_prompt(...) + "\n\n" + 꼬리 파일(hints 치환)`
  - `async extract.extract_facts_with_intake(*, source_id, source_type, text, glossary, media, hints, usage_sink=None, usage_context=None, raw_sink=None) -> IntakeFactExtractionResult`(위치 표지가 켜져 있으면 Located 판)

- [ ] **Step 1: 꼬리 파일을 쓴다** (`api/prompts/extract_facts_intake_suffix.ko.txt`):

```text
## 추가 — 자료의 용도 판정
위 사실 추출과 함께, 이 자료 전체의 용도를 아래 6개 중에서 판정한다.
가능성이 있는 것을 점수(0~1)와 함께 높은 순서로 `intake_ranking` 에 낸다. 애매해도 가장 가까운 용도를 1위로 둔다.
`intake_reason` 에는 20자 안의 짧은 근거를 쓴다.
- RECIPE: 메뉴 제조법. 규격별 수량·단위·제조 순서
- PROCEDURE: 오픈·마감·청소·기기 사용·발주 같은 업무 절차
- POLICY: 환불·할인·응대·금지 같은 운영 규칙
- REFERENCE: 보관 위치·비품·연락처·기기 정보 같은 매장 정보
- NOTICE: 이번 주 공지·행사·근무 변경처럼 기간이 있는 알림
- NONE: 업무와 무관(잡담·셀카·영수증 등)
업무와 무관(NONE)이 1위면 `assertions` 는 비워 둔다.
점주가 고른 종류: {hints} — 참고만 한다. 내용이 다르면 내용을 따른다.
```

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# api/tests/test_wb2_single_call_extract.py
"""Phase B 추가 S3 — 한 호출 추출기. 기존 추출 요청은 바뀌지 않는다(D16)."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import patch

from app.ingest.extract import gemini
from app.ingest.schemas import (FactExtractionResult, IntakeFactExtractionResult,
                                IntakeLocatedFactExtractionResult)


def test_base_prompt_unchanged_and_suffix_appended():
    base = gemini.render_facts_prompt(source_type="SCAN", text="음료Z 샷 2", glossary=[])
    merged = gemini.render_facts_intake_prompt(source_type="SCAN", text="음료Z 샷 2",
                                               glossary=[], hints=("RECIPE",))
    assert merged.startswith(base + "\n\n## 추가 — 자료의 용도 판정")
    assert "점주가 고른 종류: RECIPE" in merged
    no_hint = gemini.render_facts_intake_prompt(source_type="SCAN", text="x", glossary=[], hints=())
    assert "점주가 고른 종류: (고르지 않음)" in no_hint


def test_intake_schema_extends_fact_schema():
    props = IntakeFactExtractionResult.model_json_schema()["properties"]
    assert {"assertions", "unresolved", "intake_ranking", "intake_reason"} <= set(props)
    assert "intake_ranking" not in FactExtractionResult.model_json_schema()["properties"]
    assert issubclass(IntakeLocatedFactExtractionResult, IntakeFactExtractionResult) is False
    assert "intake_ranking" in IntakeLocatedFactExtractionResult.model_json_schema()["properties"]


def test_gemini_single_call_uses_merged_prompt_and_schema():
    seen = {}

    async def fake_measured(prompt, media, sink, context, **kw):
        seen.update(prompt=prompt, schema=kw["schema"])
        return NS(text='{"assertions": [], "unresolved": [], "intake_ranking": '
                       '[{"logic": "NOTICE", "score": 0.8}], "intake_reason": "휴무"}',
                  usage={}, finish_reason="STOP", raw_response_id=None, reused=False)

    s = NS(gemini_api_key="x", extract_locator_hints=False, extract_max_output_tokens=None)
    with patch.object(gemini, "get_settings", lambda: s), \
         patch.object(gemini, "_measured_call", fake_measured):
        out = asyncio.run(gemini.extract_facts_with_intake(
            source_id=1, source_type="SCAN", text="토요일 휴무", glossary=[], media=[],
            hints=(), usage_sink=None, usage_context=None, raw_sink=None))
    assert seen["schema"] is IntakeFactExtractionResult
    assert "## 추가 — 자료의 용도 판정" in seen["prompt"]
    assert out.intake_ranking[0].logic == "NOTICE"


def test_mock_single_call_ranks_hint_or_recipe():
    from app.ingest.extract import mock
    out = asyncio.run(mock.extract_facts_with_intake(
        source_id=1, source_type="SCAN", text="(목 모드)", glossary=[], media=[],
        hints=("POLICY",), usage_context=None, raw_sink=None))
    assert out.intake_ranking[0].logic == "POLICY"
    out = asyncio.run(mock.extract_facts_with_intake(
        source_id=1, source_type="SCAN", text="(목 모드)", glossary=[], media=[], hints=(),
        usage_context=None, raw_sink=None))
    assert out.intake_ranking[0].logic == "RECIPE"
```

`raw_responses.parse_checked` 가 `raw_sink=None`·`usage_context=None` 일 때 그냥 파싱만 하는지 먼저 확인한다. 아니면 이 테스트에서 `gemini.raw_responses.parse_checked` 를 `lambda sink, ctx, rid, fr, parse, what: parse()` 의 async 대역으로 바꾼다.

- [ ] **Step 3: 실패를 확인한다.**
- [ ] **Step 4: 구현한다.**

`schemas.py`(가산):

```python
class IntakeRank(BaseModel):
    """한 호출(Phase B 추가 S3) — 자료 전체의 용도 순위 한 줄."""
    logic: Literal["RECIPE", "PROCEDURE", "POLICY", "REFERENCE", "NOTICE", "NONE"]
    score: float = Field(ge=0, le=1)


class IntakeFactExtractionResult(FactExtractionResult):
    intake_ranking: list[IntakeRank] = []
    intake_reason: str = ""


class IntakeLocatedFactExtractionResult(LocatedFactExtractionResult):
    intake_ranking: list[IntakeRank] = []
    intake_reason: str = ""
```

`gemini.py`: 기존 `extract_facts` 본문(프롬프트 만들기 뒤 `_measured_call`·`parse_checked`·`_raw_response_id`)을 `async def _extract_with(prompt, schema, *, source_id, media, usage_sink, usage_context, raw_sink, what)` 으로 빼낸다. `extract_facts` 는 지금과 같은 `prompt`·`schema` 로 그것을 부른다(요청 동일). 새 함수는 다음과 같다.

```python
INTAKE_SUFFIX_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "extract_facts_intake_suffix.ko.txt")


def render_facts_intake_prompt(*, source_type: str, text: str, glossary, hints,
                               locator_hints: bool = False) -> str:
    """한 호출 프롬프트 = 기존 사실 추출 완성본 + 용도 판정 꼬리. 기존 프롬프트는 그대로다(D16)."""
    suffix = INTAKE_SUFFIX_PATH.read_text(encoding="utf-8").replace(
        "{hints}", ", ".join(hints) if hints else "(고르지 않음)")
    return (render_facts_prompt(source_type=source_type, text=text, glossary=glossary,
                                locator_hints=locator_hints).rstrip("\n") + "\n\n" + suffix)


async def extract_facts_with_intake(*, source_id: int, source_type: str, text: str, glossary,
                                    media=(), hints=(), usage_sink=None, usage_context=None,
                                    raw_sink=None):
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY 가 없다")
    from app.ingest.schemas import IntakeFactExtractionResult, IntakeLocatedFactExtractionResult
    schema = (IntakeLocatedFactExtractionResult if locator_hints(s)
              else IntakeFactExtractionResult)
    prompt = render_facts_intake_prompt(source_type=source_type, text=text, glossary=glossary,
                                        hints=tuple(hints), locator_hints=locator_hints(s))
    return await _extract_with(prompt, schema, source_id=source_id, media=list(media),
                               usage_sink=usage_sink, usage_context=usage_context,
                               raw_sink=raw_sink, what="사실 추출+용도 판정")
```

`mock.py`:

```python
async def extract_facts_with_intake(*, source_id, source_type, text, glossary, media=(), hints=(),
                                    usage_context=None, raw_sink=None):
    """mock 한 호출 — 기존 mock 추출 결과에 칩 첫째(없으면 RECIPE) 순위를 붙인다."""
    from app.ingest.schemas import IntakeFactExtractionResult, IntakeRank
    base = await extract_facts(source_id=source_id, source_type=source_type, text=text,
                               glossary=glossary, media=media, usage_context=usage_context,
                               raw_sink=raw_sink)
    out = IntakeFactExtractionResult(
        assertions=base.assertions, unresolved=base.unresolved,
        intake_ranking=[IntakeRank(logic=hints[0] if hints else "RECIPE", score=0.9)],
        intake_reason="mock")
    out._raw_response_id = base.raw_response_id
    return out
```

`extract/__init__.py`: `extract_facts` 와 같은 모양으로 `ingest_mode` 에 따라 gemini/mock 의 `extract_facts_with_intake` 를 부른다(mock 에는 `usage_sink` 를 넘기지 않는다).

- [ ] **Step 5: 통과를 확인한다.** 새 파일과 `tests -k "extract"` → 통과. 기존 추출 테스트(요청 바이트·재사용 키)가 그대로 통과하는지 확인한다(D16).
- [ ] **Step 6: 변경 확인.**

---

### Task 5: 한 호출 경로 연결 (route · pipeline)

**Files:**
- Modify: `api/app/ingest/intake/route.py` (`SingleCallPending`, `classify_and_save`, `route_source` 분기, `single_call_route`, `SingleCallResult`, `extract_with_intake`)
- Modify: `api/app/ingest/pipeline.py` (입구 블록, `_extract_facts_all(prefetched=)`)
- Test: `api/tests/test_wb2_single_call_pipeline.py`

**Interfaces:**
- Consumes: Task 1(`single_call_eligible`), Task 4(`extract_facts_with_intake`)
- Produces:
  - `@dataclass(frozen=True) route.SingleCallPending(probe: ProbeResult, hints: tuple[str, ...])`
  - `async route.classify_and_save(pool, store_id, src, probe, *, hints, usage_sink, usage_base) -> StoredRoute` — 지금 `route_source` 의 "분류→결정→저장" 부분을 그대로 옮긴 것.
  - `route.route_source(...)`: 시그니처는 그대로다. 저장 판정이 없고 `single_call_eligible(probe, get_settings())` 이면 `SingleCallPending` 을 돌려준다(분류 0회). 아니면 지금처럼 `StoredRoute` 를 돌려준다.
  - `route.single_call_route(probe, result, *, hints, model: str) -> tuple[list[SectionDecision], SectionDecision, ClassifyOutcome]`(순수). 순위가 비면 `IntakeClassificationError`. 모든 후보에 같은 순위를 준다(재시도 때 구간 글이 그대로 이어지게). `raw = {"single_call": True, "intake_ranking": [...], "intake_reason": ...}`.
  - `@dataclass(frozen=True) route.SingleCallResult(route: StoredRoute, result: FactExtractionResult)`
  - `async route.extract_with_intake(pool, store_id, src, pending, *, text, media, glossary, usage_sink, usage_base, raw_sink) -> SingleCallResult` — 원장 문맥 `EXTRACT`, 판정은 `entry="UPLOAD"` 로 저장.
  - `pipeline._extract_facts_all(..., prefetched: FactExtractionResult | None = None)` — 구간이 없을 때 첫 호출 대신 이 결과를 쓴다.

**pipeline 입구 블록 흐름:**

```python
        if intake_enabled:
            cache = intake_cache or intake_route.IntakeCache()
            route = await intake_route.route_source(
                pool, store_id, src, cache=cache, usage_sink=usage_sink, usage_base=usage_base)
            pending = route if isinstance(route, intake_route.SingleCallPending) else None
            if pending is None and route.source.logic == "NONE" \
                    and route.normalizer not in SECTIONED_NORMALIZERS:
                return await _finish_intake_none(pool, store_id, source_id, job_id, started)
            text, media, segments = await _preprocess(
                pool, store_id, src, usage_sink=usage_sink, usage_context=stt_context, cache=cache)
            if pending is not None:
                # 작은 자료 — 분류와 추출을 한 호출로(S3). 잘리면 보통 경로로 돌아간다
                async with pool.acquire() as conn:
                    glossary_now = await repo.glossary(conn, store_id)
                try:
                    single = await intake_route.extract_with_intake(
                        pool, store_id, src, pending, text=text, media=media,
                        glossary=glossary_now, usage_sink=usage_sink, usage_base=usage_base,
                        raw_sink=raw_sink)
                    route, prefetched = single.route, single.result
                except TruncatedOutputError:
                    logger.warning("한 호출 출력 잘림 — 분류 후 보통 추출로 간다 source=%s", source_id)
                    route = await intake_route.classify_and_save(
                        pool, store_id, src, pending.probe, hints=pending.hints,
                        usage_sink=usage_sink, usage_base=usage_base)
                if route.source.logic == "NONE":
                    # 뽑은 사실은 원장에 적지 않는다(Review Focus 2)
                    return await _finish_intake_none(pool, store_id, source_id, job_id, started)
            plan = plan_extraction(...)   # 지금과 같다
```

`prefetched` 는 블록 앞에서 `None` 으로 시작한다. `_extract_facts_all` 호출에 `prefetched=prefetched if not segments else None` 을 넘긴다. 구간이 생기면 한 호출 결과를 버리고 경고를 남긴다(작은 자료라 생기지 않는다). `TruncatedOutputError` 는 `app.ingest.raw_responses` 에서 들여온다.

`_extract_facts_all` 의 "구간 없음" 분기:

```python
        if prefetched is not None:
            # 한 호출이 이미 뽑았다 — 같은 입력을 다시 부르지 않는다
            parts = [(None, prefetched)]
        else:
            parts = await _extract_part(text, media, None)
```

- [ ] **Step 1: 실패하는 테스트 작성** (`tests.test_wb_intake_pipeline` 의 `_run` 을 쓰지 않고 새 대역을 둔다. `tests.test_w3a_pipeline_wiring` 의 `_ConnLease`·`_Tx`·`_planning` 은 재사용한다)

```python
# api/tests/test_wb2_single_call_pipeline.py
"""Phase B 추가 S3 — 한 호출 경로. 무관이면 원장 없음, 재시도는 저장 판정 재사용."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.ingest import pipeline
from app.ingest.intake import route as intake_route
from app.ingest.intake.decide import IntakeClassificationError, Ranked, SectionDecision
from app.ingest.intake.ir import Candidate, Locator, ProbeResult
from app.ingest.intake.records import StoredRoute
from app.ingest.pipeline import ExtractionOutcome, PreparedAssembly
from app.ingest.raw_responses import TruncatedOutputError
from app.ingest.schemas import IntakeFactExtractionResult, IntakeRank
from tests.test_w3a_pipeline_wiring import _ConnLease, _planning, _Tx

PROBE = ProbeResult("DOC_TEXT", (Candidate("c1", Locator("PAGE", "1", "1"), "음료Z 샷 2"),
                                 Candidate("c2", Locator("PAGE", "2", "2"), "마감")),
                    complete=True)


def _d(cid, logic):
    r = (Ranked(logic, 0.9),)
    return SectionDecision(cid, logic, () if logic == "NONE" else ("RECIPE",), False, False,
                           False, None, r, r)


def test_single_call_route_gives_every_candidate_the_ranking():
    result = IntakeFactExtractionResult(
        intake_ranking=[IntakeRank(logic="PROCEDURE", score=0.6),
                        IntakeRank(logic="RECIPE", score=0.3)], intake_reason="절차")
    decisions, source, outcome = intake_route.single_call_route(
        PROBE, result, hints=(), model="gemini-3.6-flash")
    assert [d.logic for d in decisions] == ["PROCEDURE", "PROCEDURE"]
    assert source.logic == "PROCEDURE" and decisions[0].extractors == ("RECIPE",)
    assert outcome.raw["single_call"] is True and set(outcome.model_sections) == {"c1", "c2"}


def test_single_call_route_without_ranking_is_error():
    with pytest.raises(IntakeClassificationError):
        intake_route.single_call_route(PROBE, IntakeFactExtractionResult(), hints=(),
                                       model="m")


def _run_source(tmp_path, *, route_value, single=None, single_error=None):
    src = {"source_id": 7, "store_id": 1, "source_type": "SCAN",
           "file_url": "sources/1/scan/x.docx", "content_hash": "h", "status": "PROCESSING"}
    conn = AsyncMock()
    conn.transaction = MagicMock(side_effect=lambda: _Tx())
    conn.fetchval = AsyncMock(return_value=3)
    conn.fetch = AsyncMock(return_value=[])

    class Pool:
        def acquire(self):
            return _ConnLease(conn)

    async def fake_preprocess(pool, store_id, s, *, usage_sink=None, usage_context=None,
                              cache=None):
        cache.sections = {"c1": "[1쪽]\n음료Z 샷 2", "c2": "[2쪽]\n마감"}
        return "[1쪽]\n음료Z 샷 2\n\n[2쪽]\n마감", [], []

    m = NS(extract=AsyncMock(return_value=ExtractionOutcome([], [], 1, 0, [], {})),
           prepare=AsyncMock(return_value=PreparedAssembly((), {}, {}, (), {}, _planning())),
           classify_save=AsyncMock(return_value=StoredRoute(
               9, "DOC_TEXT", [_d("c1", "RECIPE"), _d("c2", "RECIPE")], _d("source", "RECIPE"))),
           single=AsyncMock(return_value=single, side_effect=single_error),
           none=AsyncMock(return_value=pipeline.INTAKE_NONE))
    with patch.object(pipeline, "get_pool", return_value=Pool()), \
         patch.object(intake_route, "route_source", AsyncMock(return_value=route_value)), \
         patch.object(intake_route, "extract_with_intake", m.single), \
         patch.object(intake_route, "classify_and_save", m.classify_save), \
         patch.object(pipeline, "_preprocess", fake_preprocess), \
         patch.object(pipeline, "_finish_intake_none", m.none), \
         patch.object(pipeline.recovery, "load", AsyncMock(return_value=None)), \
         patch.object(pipeline.recovery, "replace", AsyncMock()), \
         patch.object(pipeline.recovery, "layout_hash", return_value="h"), \
         patch.object(pipeline.repo, "get_source", AsyncMock(return_value=src)), \
         patch.object(pipeline.repo, "set_status", AsyncMock()), \
         patch.object(pipeline.repo, "enabled_categories", AsyncMock(return_value={"기타": 1})), \
         patch.object(pipeline.repo, "glossary", AsyncMock(return_value=[])), \
         patch.object(pipeline.storage, "workdir", return_value=tmp_path / "w"), \
         patch.object(pipeline, "_extract_facts_all", m.extract), \
         patch.object(pipeline, "_record_segment_failures", AsyncMock()), \
         patch.object(pipeline, "_prepare_fact_assembly", m.prepare), \
         patch.object(pipeline, "_persist_fact_cards", AsyncMock(return_value=0)), \
         patch("app.config.get_settings", return_value=Settings(_env_file=None)):
        result = asyncio.run(pipeline.process_source(1, 7, job_id=3))
    return result, m


PENDING = intake_route.SingleCallPending(PROBE, ())
DONE_RESULT = IntakeFactExtractionResult(intake_ranking=[IntakeRank(logic="RECIPE", score=0.9)])


def _single(logic):
    return intake_route.SingleCallResult(
        StoredRoute(11, "DOC_TEXT", [_d("c1", logic), _d("c2", logic)], _d("source", logic)),
        DONE_RESULT)


def test_single_call_prefetches_extraction(tmp_path):
    result, m = _run_source(tmp_path, route_value=PENDING, single=_single("RECIPE"))
    m.single.assert_awaited_once()
    assert m.extract.await_args.kwargs["prefetched"] is DONE_RESULT
    m.classify_save.assert_not_awaited()


def test_single_call_none_writes_nothing(tmp_path):
    # Review Focus 2
    result, m = _run_source(tmp_path, route_value=PENDING, single=_single("NONE"))
    assert result == pipeline.INTAKE_NONE
    m.extract.assert_not_awaited()
    m.prepare.assert_not_awaited()


def test_truncated_single_call_falls_back_to_classify_then_normal_extract(tmp_path):
    result, m = _run_source(tmp_path, route_value=PENDING,
                            single_error=TruncatedOutputError("잘림"))
    m.classify_save.assert_awaited_once()
    assert m.extract.await_args.kwargs["prefetched"] is None


def test_stored_route_never_uses_single_call(tmp_path):
    # Review Focus 3·4 — 저장 판정(재시도) 또는 스위치 꺼짐이면 지금 경로
    stored = StoredRoute(9, "DOC_TEXT", [_d("c1", "RECIPE"), _d("c2", "RECIPE")],
                         _d("source", "RECIPE"))
    result, m = _run_source(tmp_path, route_value=stored)
    m.single.assert_not_awaited()
    assert m.extract.await_args.kwargs["prefetched"] is None


class _RLease:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, *exc):
        return False


class _RPool:
    def acquire(self):
        return _RLease()


SRC = {"source_id": 7, "store_id": 1, "source_type": "SCAN",
       "file_url": "sources/1/scan/x.docx"}


def _route_source(**settings):
    s = Settings(_env_file=None).model_copy(update=settings)
    cls = AsyncMock()
    with patch.object(intake_route.records, "latest_decision", AsyncMock(return_value=None)), \
         patch.object(intake_route.records, "source_owner_hints", AsyncMock(return_value=("NOTICE",))), \
         patch.object(intake_route, "probe_source", AsyncMock(return_value=PROBE)), \
         patch.object(intake_route, "classify_and_save", cls), \
         patch.object(intake_route, "get_settings", return_value=s):
        out = asyncio.run(intake_route.route_source(
            _RPool(), 1, SRC, cache=intake_route.IntakeCache(), usage_sink=None,
            usage_base=(1, 3, "REGISTRATION", "PRODUCT", None, 42)))
    return out, cls


def test_route_source_switch_off_classifies():
    out, cls = _route_source(intake_single_call_small=False)
    cls.assert_awaited_once()


def test_route_source_switch_on_returns_pending_without_classify():
    out, cls = _route_source(intake_single_call_small=True)
    assert isinstance(out, intake_route.SingleCallPending) and out.hints == ("NOTICE",)
    cls.assert_not_awaited()


def test_extract_facts_all_uses_prefetched_without_calling():
    from app.ingest.schemas import ExtractedAssertion
    a = ExtractedAssertion(local_ref="f1", original_assertion="음료Z 샷 2", subject="음료Z",
                           attribute="샷", value="2", unit="샷", confidence=0.9)
    pre = IntakeFactExtractionResult(assertions=[a], intake_ranking=[IntakeRank(logic="RECIPE", score=0.9)])
    called = AsyncMock()
    seen = []

    async def checkpoint(items, seg):
        seen.append((len(items), seg))

    with patch("app.ingest.extract.extract_facts", called), \
         patch("app.config.get_settings", return_value=Settings(_env_file=None)):
        out = asyncio.run(pipeline._extract_facts_all(
            source_id=7, source_type="SCAN", text="음료Z 샷 2", media=[], glossary=[],
            segments=[], checkpoint=checkpoint, prefetched=pre))
    called.assert_not_awaited()
    assert len(out.assertions) == 1 and seen == [(1, None)]
```

`extract_with_intake` 자체 테스트(대역 `extract.extract_facts_with_intake`·`records.save_decision`)를 같은 파일에 더한다.
- 원장 문맥이 `stage == "EXTRACT"` 다.
- 저장 `entry == "UPLOAD"` 이고 `outcome.raw["single_call"] is True` 다.
- 결과 순위가 NOTICE 면 `route.source.logic == "NOTICE"` 다.

- [ ] **Step 2: 실패를 확인한다.**
- [ ] **Step 3: 구현한다** — Interfaces 와 위 흐름대로. `route_source` 의 분기는 다음과 같다.

```python
    probe = await probe_source(pool, store_id, src, cache=cache, usage_sink=usage_sink,
                               usage_base=usage_base)
    if single_call_eligible(probe, get_settings()):
        # 작은 자료 — 여기서는 분류하지 않고 본 추출 한 호출로 판정을 함께 받는다(S3)
        return SingleCallPending(probe, tuple(hints))
    return await classify_and_save(pool, store_id, src, probe, hints=hints,
                                   usage_sink=usage_sink, usage_base=usage_base)
```

`single_call_route`:

```python
def single_call_route(probe: ProbeResult, result, *, hints, model: str):
    ranking = [Ranked(r.logic, r.score) for r in getattr(result, "intake_ranking", [])]
    if not ranking:
        raise IntakeClassificationError("한 호출 결과에 용도 판정이 없다")
    model_sections = {c.candidate_id: ranking for c in probe.candidates}
    th = Thresholds.from_settings(get_settings())
    registered = registry.registered_logics()
    candidates = tuple(replace(c, sampled=True) for c in probe.candidates)
    decisions = decide_all(candidates, model_sections, hints=hints, th=th, registered=registered)
    source = source_decision(decisions, hints=hints, th=th, registered=registered)
    raw = {"single_call": True,
           "intake_ranking": [[r.logic, r.score] for r in ranking],
           "intake_reason": getattr(result, "intake_reason", "")}
    return decisions, source, ClassifyOutcome(model_sections, raw, model, "")
```

`extract_with_intake` 은 `pipeline._ctx_for(usage_base, source_id, "EXTRACT")` 문맥으로 `extract.extract_facts_with_intake` 를 부르고, `single_call_route(..., model=get_settings().gemini_model)` 결과를 `records.save_decision(..., logical_call_id=ctx.logical_call_id if ctx else None)` 로 저장한다. 연결은 저장할 때만 짧게 빌린다.

- [ ] **Step 4: 통과를 확인한다.** 새 파일과 `tests/test_wb_intake_pipeline.py tests/test_wb_intake_held_facts.py tests/test_wb_intake_owner_override.py`, 그리고 전체 스위트 → 실패 0. 기존 대역이 `route_source` 를 `StoredRoute` 로 돌려주므로 영향이 없어야 한다.
- [ ] **Step 5: 격리 검사·변경 확인.**

---

### Task 6: 한 호출 평가 모드 (하네스)

**Files:**
- Modify: `api/scripts/run_intake_classifier_eval.py`
- Modify: `api/tests/test_wb_intake_eval.py`
- Modify: `api/eval/intake/README.md`

**규칙:**
- `--single-call` 을 주면 사례마다 후보 글을 이어 붙인 한 글로 `extract.extract_facts_with_intake` 를 부르고, `intake_ranking` 으로 자료 단위 판정을 만들어 같은 지표로 채점한다. 구간 정확도는 모든 구간에 같은 판정을 준다.
- 사례 중 전체 글자가 `intake_probe_text_chars` 이하인 것만 쓴다(작은 자료 조건). 쓴 사례 수와 뺀 사례 수를 보고서에 적는다.
- 기본은 mock 이고, 비용 0, DB·네트워크를 쓰지 않는다. `--real --confirm-paid` 규칙은 그대로다(실행하지 않는다).
- README 에 "켜기 전 비교 절차"를 적는다(사용자 승인 뒤 실행).
  1. 같은 작은 사례에서 분리 경로(`분류 1회 + 추출 1회`)와 한 호출을 각 3회씩 돌린다(D17).
  2. 용도 판정 정확도, 사실 수·참조 대비 재현, 토큰·USD 를 나란히 적는다.
  3. 한 호출이 판정 정확도에서 떨어지지 않고 비용이 줄면 `INTAKE_SINGLE_CALL_SMALL=true` 를 켠다.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_single_call_mock_run_uses_only_small_cases(tmp_path):
    import os
    out = tmp_path / "eval.md"
    res = subprocess.run([sys.executable, "scripts/run_intake_classifier_eval.py", "--single-call",
                          "--out", str(out)], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "INGEST_MODE": "mock"})
    assert res.returncode == 0, res.stderr
    text = out.read_text(encoding="utf-8")
    assert "한 호출" in text and "0원" in text and "작은 사례" in text
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인.** `cd api && .venv/bin/python -m pytest -q tests/test_wb_intake_eval.py`
- [ ] **Step 3: 변경 확인.**

---

### Task 7: 측정 보고 · 실제 DB 검증 · 문서

**Files:**
- Create: `api/app/usage/intake_report.py` (순수 집계·서식)
- Create: `api/scripts/intake_cost_report.py` (DB 조회 + 출력)
- Test: `api/tests/test_wb2_intake_report.py`
- Modify: `api/scripts/verify_w_intake.py` (i-15~i-17)
- Modify: `docs/dev/plan/W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md` (§9-3 "작은 자료 호출 줄이기(2026-10-14)" — S1~S5 와 이 계획 링크)
- Modify: `docs/dev/plan/W_FACT_ONLY_ROADMAP_20261010.md` (§1 Phase B 행에 추가 계획 한 줄)
- Modify: 이 계획 맨 아래 "실행 기록"

**Interfaces:**
- Produces:
  - `intake_report.summarize(stage_rows: list[dict], source_rows: list[dict]) -> dict`. `stage_rows` 는 `{stage, calls, cost_usd, known_cost_usd, prompt_tokens, completion_tokens}` 다. `source_rows` 는 `{source_id, normalizer, chars, images, complete, single_call, bundled}` 다. 결과에 단계별 표, CLASSIFY 비용 비율, 작은 자료(`complete`) 수·비율, 한 호출·묶음·단독 분류 수가 들어간다.
  - `intake_report.render(summary: dict) -> str`(마크다운)
  - CLI: `python scripts/intake_cost_report.py --store <store_id> [--since YYYY-MM-DD] [--out PATH]`

조회 SQL(스크립트). 둘 다 `store_id` 로 좁힌다.

```sql
-- 단계별(운영 제품 호출만)
select stage, count(distinct logical_call_id) as calls,
       coalesce(sum(cost_usd), 0) as cost_usd, coalesce(sum(known_cost_usd), 0) as known_cost_usd,
       coalesce(sum(prompt_tokens), 0) as prompt_tokens,
       coalesce(sum(completion_tokens), 0) as completion_tokens
from ai_usage_attempts
where store_id = $1 and cost_purpose = 'PRODUCT' and started_at >= $2
group by stage order by stage;

-- 자료별 최신 판정
select distinct on (d.source_id) d.source_id, d.normalizer,
       coalesce((d.sample_summary->>'chars')::int, 0) as chars,
       coalesce((d.sample_summary->>'images')::int, 0) as images,
       coalesce((d.sample_summary->>'complete')::boolean, false) as complete,
       coalesce((d.model_sections->>'single_call')::boolean, false) as single_call,
       coalesce(d.logical_call_id like '%:bundle%', false) as bundled
from intake_route_decisions d
where d.store_id = $1 and d.created_at >= $2
order by d.source_id, d.decision_id desc;
```

`ai_usage_attempts` 의 `store_id`·`prompt_tokens`·`completion_tokens`·`logical_call_id` 열 이름과 타입을 `supabase/migrations/20260915090000_mc0_usage_ledger.sql` 에서 먼저 확인하고 맞춘다(단언의 의미는 바꾸지 않는다).

- [ ] **Step 1: 실패하는 테스트**

```python
# api/tests/test_wb2_intake_report.py
"""Phase B 추가 S5 — 작은 자료·묶음·한 호출 측정 보고(순수)."""
from decimal import Decimal

from app.usage import intake_report


def test_summarize_shares_and_counts():
    stages = [
        {"stage": "CLASSIFY", "calls": 2, "cost_usd": Decimal("0.002"),
         "known_cost_usd": Decimal("0.002"), "prompt_tokens": 2000, "completion_tokens": 100},
        {"stage": "EXTRACT", "calls": 4, "cost_usd": Decimal("0.018"),
         "known_cost_usd": Decimal("0.018"), "prompt_tokens": 9000, "completion_tokens": 900},
    ]
    sources = [
        {"source_id": 1, "normalizer": "DOC_TEXT", "chars": 120, "images": 0, "complete": True,
         "single_call": True, "bundled": False},
        {"source_id": 2, "normalizer": "DOC_TEXT", "chars": 3000, "images": 0, "complete": False,
         "single_call": False, "bundled": True},
        {"source_id": 3, "normalizer": "DOC_IMAGE", "chars": 0, "images": 1, "complete": True,
         "single_call": False, "bundled": True},
        {"source_id": 4, "normalizer": "AUDIO", "chars": 300, "images": 0, "complete": False,
         "single_call": False, "bundled": False},
    ]
    s = intake_report.summarize(stages, sources)
    assert s["classify_cost_share"] == Decimal("0.1")
    assert (s["sources"], s["small"], s["single_call"], s["bundled"], s["standalone"]) == (4, 2, 1, 2, 1)


def test_render_mentions_sections_and_no_data():
    text = intake_report.render(intake_report.summarize([], []))
    assert "단계별" in text and "자료 없음" in text


def test_zero_cost_does_not_divide_by_zero():
    s = intake_report.summarize([{"stage": "EXTRACT", "calls": 1, "cost_usd": Decimal(0),
                                  "known_cost_usd": Decimal(0), "prompt_tokens": 0,
                                  "completion_tokens": 0}], [])
    assert s["classify_cost_share"] is None
```

`standalone` 은 한 호출도 묶음도 아닌 자료 수다(자료 단독 분류). `classify_cost_share` 는 전체 `cost_usd` 가 0이면 `None` 이다.

- [ ] **Step 2: 실패 확인 → `intake_report.py`·`intake_cost_report.py` 구현 → 통과 확인.**
- [ ] **Step 3: 실제 DB 시나리오를 더한다** (`verify_w_intake.py`. 기존 대역·헬퍼 `_patches`·`_docx_source`·`_job`·`_store` 를 쓴다).
  - **i-15 묶음:** 작은 docx 3개를 한 작업으로 처리하면 분류 대역 호출 1회, 판정 3행의 `logical_call_id` 가 모두 `:bundle1` 로 끝나고, 세 자료 모두 DONE 이다.
  - **i-16 한 호출:** `intake_single_call_small=True` 설정으로 작은 docx 하나를 처리한다. 분류 대역 0회, 한 호출 대역(`app.ingest.extract.extract_facts_with_intake` 를 FACTS 열쇠 방식으로 만든 대역) 1회, 판정 행 `model_sections->>'single_call' = 'true'`, 카드 생성. 같은 자료를 추출 실패로 다시 처리하게 만든 뒤 재처리하면 분류·한 호출 모두 0회이고 보통 추출이 1회다.
  - **i-17 한 호출 무관:** 한 호출 대역이 NONE 을 내면 원장 사실 0, 작업 NO_RESULT·error_code INTAKE_NONE 이다.
  - **보고 스크립트:** i-15~i-17 뒤 그 매장으로 `intake_report.summarize` 를 조회해, 한 호출 1·묶음 3 이상이 집계되는지 확인한다.
- [ ] **Step 4: 실제 DB 전체 검증**

```bash
docker run -d --rm --name askbuddy-w-verify -p 127.0.0.1:55439:5432 \
  -e POSTGRES_PASSWORD=synthetic-local-test -e POSTGRES_DB=usage_verify pgvector/pgvector:pg17
cd api && GEMINI_API_KEY= OPENAI_API_KEY= ANTHROPIC_API_KEY= PYTHONPATH=. PYTHONUTF8=1 \
  .venv/bin/python -B scripts/verify_r_schema_rebuild.py
docker stop askbuddy-w-verify
```

기대: 기존 전부 통과, `PASS WB i-15`~`i-17` 이다.

- [ ] **Step 5: 전체 단위 테스트·격리 검사·`pnpm check`(web 을 건드리지 않았으면 생략하고 그렇게 적는다).**
- [ ] **Step 6: 문서를 갱신한다.** 실행 기록에 테스트 수·검증 결과·하지 않은 것(실모델 비교 평가, 스위치 켜기)을 사실대로 적는다.
- [ ] **Step 7: 보고하고 멈춘다.** 커밋·푸시를 하지 않고, 할지 묻지도 않는다.

---

## 실행 기록

| 항목 | 값 |
|---|---|
| 기준선 pytest | `2387 passed, 6 skipped, 4 xfailed` (계획 시작). Task 7 직전 `2432 passed, 6 skipped, 4 xfailed` |
| 최종 pytest | `2436 passed, 6 skipped, 4 xfailed` (Task 7 에서 `test_wb2_intake_report.py` 4건 추가 — 미관측 비용 1건 포함) |
| 최종 검토 반영 | I-1 칩이 NONE 을 뒤집으면 한 호출 사실을 버리고 보통 추출, I-2 음성·영상은 작업 묶음에서 제외, I-3 새 설정 `intake_bundle_max_candidates`(기본 24, `ge=2`)로 묶음 후보 수 제한. 테스트 5건 추가 → `2441 passed, 6 skipped, 4 xfailed` |
| 실제 DB 검증 | **통과 (2026-10-15).** API 키를 비우고 `verify_r_schema_rebuild.py` 실행, 종료 코드 0·FAIL 0. `PASS WB i-15`~`i-17`·보고 확인(한 호출 3·묶음 3·단독 0·작은 자료 6/6)·`PASS WB all scenarios`, 묶음 경로로 바뀐 i-14 도 통과. (10-14 에는 로컬 Docker 가 응답하지 않아 실행 못 했다) |
| 격리 검사 | `check_store_id.py api/app/ingest api/app/cards api/app/checklist api/app/publish api/app/usage` → 기존 `repository.py` 15건만, 새 위반 0. `api/scripts/intake_cost_report.py` 위반 없음 |
| 유료 호출 | 0 (한 호출 비교 평가는 사용자 승인 대기) |
| 스위치 | `intake_single_call_small` 기본 꺼짐 |
| web | 바꾸지 않아 `pnpm check` 생략 |
| 하지 않은 것 | 실모델 비교 평가(한 호출 대 분류+추출), 스위치 켜기, 실제 DB 검증(위) |
