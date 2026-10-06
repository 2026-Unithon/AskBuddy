# SCAN 구역 기반 다단계 추출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SCAN 자료를 구역 지도 → 띠 전사 → 재확인 → 사실 전개의 다단계로 처리하는 `scan_extract_mode="LAYOUT"` 경로를 만들고, 레시피북에서 참조 대비 재현율을 잰다.

**Architecture:** `app/ingest/layout/` 가 쪽 이미지·구역·전사·재확인·전개를 단계별 파일로 맡고, `app/ingest/providers/` 가 공급자(Gemini·Anthropic) 호출을 같은 계측·원래 응답 기록·재사용 키 경로로 통일한다. `process_source` 는 SCAN·LAYOUT 일 때만 이 모듈을 불러 구역 1개를 구간 1개로 체크포인트한다. 이후 원장·조립은 기존 코드.

**Tech Stack:** Python 3.12, FastAPI 앱 내부 모듈, pydantic v2, Pillow, pypdf, pypdfium2(신규), anthropic SDK 1.x(신규), google-genai(기존), pytest + pytest-asyncio.

**Spec:** `docs/dev/plan/W_SCAN_LAYOUT_EXTRACTION_DESIGN.md`

## Global Constraints

- 평가 자료의 브랜드명·상호·메뉴 고유명을 코드·주석·프롬프트·테스트 픽스처·문서에 쓰지 않는다. 테스트는 `메뉴A`·`메뉴B` 같은 익명 이름만.
- 주석은 한국어. 프롬프트는 `api/prompts/` 파일로 분리한다(코드 하드코딩 금지).
- 모델명·임계값·상한은 `api/app/config.py` 단일 출처(불변식 8). 형식 `공급자:모델`.
- DB 를 새로 조회하는 코드는 `store_id` 필수 인자 + `WHERE store_id = $1`.
- 운영 기본값 `scan_extract_mode = "SINGLE"`. SINGLE 경로 동작·기존 테스트는 바뀌지 않는다.
- LAYOUT·real 에서 필요한 공급자 키가 없으면 설정 로드 시 `ValueError` 로 멈춘다(조용한 폴백 금지).
- 모델의 자기 보고를 판정 근거로 쓰지 않는다. 완료는 코드 검사로 판정한다.
- 판독 불가 칸은 사실을 만들지 않고 미해결(쪽·구역·칸·사유)로 남긴다.
- 커밋하지 않는다. 커밋·머지는 사용자가 한다. 각 Task 의 마지막 단계는 "작업 트리에 둔다".
- `requirements.txt` 는 한 줄씩 append 한다(`pip freeze >` 금지).
- 정해진 모델 ID: `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-4-5`(날짜 접미사 없음), `gemini-3.6-flash`.

## 설계와 다른 점 (계획 단계 결정)

1. **OpenAI 어댑터는 이번에 만들지 않는다.** 설계 7절의 실험 순서(Flash↔Haiku, Sonnet↔Opus)에 OpenAI 가 없다. 필요해지면 `providers/` 에 같은 형태로 추가한다.
2. **금액 상한은 "실행 전 추정"이 아니라 "실제 사용액 누적 + 상한 도달 시 다음 호출 거부"** 다. 띠 수는 구역 지도가 나와야 알 수 있어 사전 추정이 부정확하다. 호출 수 상한(설정)은 그대로 항상 켜져 있다.
3. **요율 없는 모델:** `--max-usd` 를 주면 Anthropic 모델은 요율이 있어야 실행된다(없으면 거부). Gemini 요율이 비어 있으면 비용을 UNKNOWN 으로 기록하고 실행은 허용한다 — 7 USD 상한은 Anthropic 사용액이다.
4. **PARTIAL 재시도:** LAYOUT 모드의 잃은 구역 재시도는 `extract_reuse_enabled` 가 켜져 구역 지도 응답이 재사용될 때만 허용한다. 꺼져 있으면 `PARTIAL_RETRY_UNAVAILABLE` (구역 ID 가 같은 영역을 가리킨다는 보장이 없다).
5. **행 단위 문제(행 누락·열 수 불일치)는 칸 질의가 아니라 해당 띠를 재확인 모델로 다시 전사**한다. 칸 단위 문제(띠 겹침 불일치)만 칸 질의 루프로 간다.
6. **재확인의 "도구"는 공급자 tool-use 가 아니라 구조화 출력 턴**(`crops` 요청 또는 `answers`)이다. 공급자 중립이고 원래 응답 기록이 그대로 남는다. 상한은 코드가 센다.
7. **판독 불가·전개 미반영 칸은 구역 실패로 세지 않고 미해결로만 드러낸다.** 설계 6절은 이런 구역을 PARTIAL 로 보지만, 구역 실패로 세면 PARTIAL 재시도가 그 구역을 다시 뽑아 이미 만든 카드와 겹친다. 작업 `PARTIAL` 은 구역 예외·띠 상한·금액 상한 때만. 설계 1절 완료 기준("미해결 또는 PARTIAL 로 드러난다")은 그대로 만족한다.

## Review Focus

1. 라벨 없는 표에서 같은 행이 겹친 두 띠에 모두 나온다 → 사실이 두 번 생기지 않는다 (Task 4 `test_merge_unlabeled_overlap_dedup`).
2. 모델이 머리글보다 많거나 적은 칸을 낸다 → 죽지 않고 그 행을 재전사 대상으로 표시한다 (Task 4 `test_column_count_flag`).
3. 구역 지도가 쪽 일부만 덮는다 → 덮이지 않은 글자 영역이 UNCLASSIFIED 구역으로 추가된다 (Task 3 `test_uncovered_ink_becomes_region`).
4. 실행 중 금액 상한에 닿는다 → 그 뒤 구역은 FAILED, 작업 전체는 예외 없이 PARTIAL 로 끝난다 (Task 7 `test_budget_exceeded_marks_region_failed`).
5. 재확인이 칸을 판독 불가로 답한다 → 그 칸의 값으로 사실이 만들어지지 않고 미해결에 쪽·구역·칸이 남는다 (Task 6 `test_unreadable_cell_not_expanded`).

---

## 파일 구조

```
api/app/ingest/providers/
  __init__.py          # ModelSpec · parse_model_spec · measured_generate
  types.py             # CallResult (gemini.py 에서 이동, gemini 는 재수출)
  measured.py          # 공급자 중립 계측 호출(원가 receipt·원래 응답·재사용 키)
  anthropic_call.py    # Anthropic 원시 호출
  budget.py            # 실행 금액 누적·상한
api/app/ingest/layout/
  __init__.py          # run_layout_extraction (오케스트레이터)
  schemas.py           # 모델 출력 스키마(strict) + 내부 자료형
  pages.py             # ① 쪽 이미지
  regions.py           # ② 구역 지도 + 빈 영역 검사
  transcribe.py        # ③ 띠 분할·전사·병합·검사
  recheck.py           # ④ 띠 재전사 · 칸 질의 루프
  expand.py            # ⑤ 행 → 사실, 토큰 반영 검사
  prompts.py           # 프롬프트 파일 읽기·치환
api/prompts/layout_region.ko.txt · layout_table_band.ko.txt · layout_prose.ko.txt ·
            layout_photo.ko.txt · layout_recheck.ko.txt · layout_expand.ko.txt
api/tests/test_layout_providers.py · test_layout_pages.py · test_layout_regions.py ·
          test_layout_transcribe.py · test_layout_recheck.py · test_layout_expand.py ·
          test_layout_pipeline.py
```
수정: `api/app/config.py`, `api/app/ingest/extract/gemini.py`, `api/app/ingest/schemas.py`, `api/app/ingest/pipeline.py`, `api/scripts/run_extract_eval.py`, `api/config/rate_card.json`, `api/requirements.txt`.

---

### Task 1: 공급자 계층 · 설정 · 예산

**Files:**
- Create: `api/app/ingest/providers/__init__.py`, `types.py`, `measured.py`, `anthropic_call.py`, `budget.py`
- Modify: `api/app/ingest/extract/gemini.py` (`CallResult` 이동, `_call` 에 `model` 인자, `_measured_call` 위임)
- Modify: `api/app/config.py` (LAYOUT 설정 + 키 검사)
- Modify: `api/requirements.txt` (append `anthropic>=1.11`, `pypdfium2>=5.14`), `api/config/rate_card.json`
- Test: `api/tests/test_layout_providers.py`

**Interfaces:**
- Produces:
  - `ModelSpec(provider: Literal["gemini","anthropic"], model: str)` (frozen dataclass), `parse_model_spec(text: str) -> ModelSpec`
  - `async measured_generate(spec, prompt: str, images: list[Path], schema: type[BaseModel], *, usage_sink=None, usage_context=None, raw_sink=None, max_output_tokens: int | None = None, what: str, mock_build: Callable[[], BaseModel] | None = None) -> BaseModel`
  - `budget.set_limit(usd: Decimal | None)`, `budget.spent() -> Decimal`, `budget.unpriced() -> set[str]`, `budget.BudgetExceeded`
  - `CallResult` (그대로 `app.ingest.extract.gemini.CallResult` 로도 import 가능)

- [ ] **Step 1: 의존성 설치·append**

```bash
cd api && source .venv/bin/activate && pip install "anthropic>=1.11" "pypdfium2>=5.14"
printf 'anthropic>=1.11\npypdfium2>=5.14\n' >> requirements.txt
```

- [ ] **Step 2: 실패하는 테스트 작성** — `api/tests/test_layout_providers.py`

```python
"""공급자 계층 — 모델 지정 해석, Anthropic 응답 변환, 예산 상한, 계측 경로 공통화."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, ConfigDict

from app.ingest import providers
from app.ingest.providers import anthropic_call, budget
from app.ingest.providers.types import CallResult


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


def test_parse_model_spec():
    s = providers.parse_model_spec("anthropic:claude-sonnet-5-5")
    assert (s.provider, s.model) == ("anthropic", "claude-sonnet-5-5")
    with pytest.raises(ValueError):
        providers.parse_model_spec("claude-sonnet-5-5")
    with pytest.raises(ValueError):
        providers.parse_model_spec("openai:gpt")


def _resp(text, stop="end_turn"):
    usage = NS(input_tokens=11, output_tokens=7, cache_read_input_tokens=0,
               model_dump=lambda: {"input_tokens": 11, "output_tokens": 7})
    return NS(content=[NS(type="text", text=text)], stop_reason=stop,
              stop_details=None, usage=usage)


@pytest.mark.asyncio
async def test_anthropic_call_maps_usage_and_stop(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = AsyncMock(return_value=_resp('{"value": "1"}', "max_tokens"))
    client = NS(messages=NS(create=fake))
    st = NS(anthropic_api_key="k", layout_anthropic_effort="low", layout_max_output_tokens=100)
    with patch.object(anthropic_call, "get_settings", return_value=st), \
         patch.object(anthropic_call, "_client", return_value=client):
        out = await anthropic_call.call("claude-sonnet-5-5", "p", [img], _Out, None)
    assert out.text == '{"value": "1"}'
    assert out.finish_reason == "MAX_TOKENS"
    assert out.usage["prompt_tokens"] == 11 and out.usage["completion_tokens"] == 7
    kwargs = fake.call_args.kwargs
    assert kwargs["output_config"]["effort"] == "low"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["messages"][0]["content"][0]["type"] == "image"


@pytest.mark.asyncio
async def test_anthropic_haiku_has_no_effort(tmp_path):
    fake = AsyncMock(return_value=_resp('{"value": "1"}'))
    st = NS(anthropic_api_key="k", layout_anthropic_effort="low", layout_max_output_tokens=100)
    with patch.object(anthropic_call, "get_settings", return_value=st), \
         patch.object(anthropic_call, "_client", return_value=NS(messages=NS(create=fake))):
        await anthropic_call.call("claude-haiku-4-5", "p", [], _Out, None)
    assert "effort" not in fake.call_args.kwargs["output_config"]


@pytest.mark.asyncio
async def test_anthropic_refusal_raises():
    fake = AsyncMock(return_value=_resp("", "refusal"))
    st = NS(anthropic_api_key="k", layout_anthropic_effort=None, layout_max_output_tokens=100)
    with patch.object(anthropic_call, "get_settings", return_value=st), \
         patch.object(anthropic_call, "_client", return_value=NS(messages=NS(create=fake))):
        with pytest.raises(RuntimeError, match="거절"):
            await anthropic_call.call("claude-sonnet-5-5", "p", [], _Out, None)


def test_budget_accumulates_and_blocks(monkeypatch):
    card = NS(model_rate=lambda m: {"input_per_1m": Decimal("2"), "output_per_1m": Decimal("10")}
              if m == "claude-sonnet-5-5" else {"input_per_1m": None, "output_per_1m": None})
    monkeypatch.setattr(budget, "load_rate_card", lambda: card)
    budget.set_limit(Decimal("0.00003"))
    budget.check_before_call()
    budget.add_usage("claude-sonnet-5-5", {"prompt_tokens": 10, "completion_tokens": 1})
    assert budget.spent() == Decimal("0.00003")
    with pytest.raises(budget.BudgetExceeded):
        budget.check_before_call()
    budget.add_usage("gemini-3.6-flash", {"prompt_tokens": 10})
    assert "gemini-3.6-flash" in budget.unpriced()
    budget.set_limit(None)
    budget.check_before_call()


@pytest.mark.asyncio
async def test_measured_generate_mock_mode_uses_builder():
    st = NS(ingest_mode="mock")
    with patch.object(providers, "get_settings", return_value=st):
        out = await providers.measured_generate(
            providers.parse_model_spec("anthropic:claude-sonnet-5-5"), "p", [], _Out,
            what="테스트", mock_build=lambda: _Out(value="m"))
    assert out.value == "m"


@pytest.mark.asyncio
async def test_measured_generate_real_parses_and_charges(monkeypatch):
    st = NS(ingest_mode="real")
    budget.set_limit(None)
    seen = {}
    async def fake_call(model, prompt, images, schema, max_output_tokens):
        seen["model"] = model
        return CallResult('{"value": "ok"}', {"prompt_tokens": 1, "completion_tokens": 1}, "STOP")
    monkeypatch.setattr(anthropic_call, "call", fake_call)
    with patch.object(providers, "get_settings", return_value=st):
        out = await providers.measured_generate(
            providers.parse_model_spec("anthropic:claude-sonnet-5-5"), "p", [], _Out, what="테스트")
    assert out.value == "ok" and seen["model"] == "claude-sonnet-5-5"


def test_layout_requires_anthropic_key():
    from app.config import Settings
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings(_env_file=None, ingest_mode="real", scan_extract_mode="LAYOUT", anthropic_api_key="")
    Settings(_env_file=None, ingest_mode="real", scan_extract_mode="SINGLE", anthropic_api_key="")
```

- [ ] **Step 3: 실패 확인**

Run: `cd api && pytest tests/test_layout_providers.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingest.providers'`

- [ ] **Step 4: `providers/types.py` — CallResult 이동**

```python
"""공급자 호출 결과. 모든 공급자가 같은 형태로 돌려준다."""
from typing import NamedTuple


class CallResult(NamedTuple):
    """모델 호출 한 번의 결과.

    finish_reason — 공급자 종료 사유를 STOP·MAX_TOKENS 등으로 맞춘 문자열. 못 받으면 None.
    raw_response_id — 원래 응답 행(extraction_raw_responses). 기록하지 않았으면 None.
    reused — 모델을 부르지 않고 같은 입력의 지난 성공 응답을 되썼다 (W1-3).
    """

    text: str
    usage: dict
    finish_reason: str | None
    raw_response_id: int | None = None
    reused: bool = False
```

`gemini.py` 에서 `class CallResult(NamedTuple): ...` 정의를 지우고 `from app.ingest.providers.types import CallResult  # noqa: F401  (기존 import 경로 호환)` 로 바꾼다.

- [ ] **Step 5: `gemini._call` 에 model 인자**

`async def _call(prompt, media, schema=None, max_output_tokens=None, model: str | None = None)` 로 바꾸고 `model=s.gemini_model` 을 `model=model or s.gemini_model` 로. 나머지는 그대로.

- [ ] **Step 6: `providers/measured.py` — `_measured_call` 본문을 공급자 중립으로 이동**

```python
"""공급자 중립 계측 호출 — 원가 receipt · 원래 응답 기록 · 재사용 키 (W1-1·W1-3·CP-00B).

`gemini._measured_call` 에 있던 본문을 옮겼다. 모델 이름과 원시 호출만 바깥에서 받는다.
settings 는 호출부가 넘긴다(테스트 대역이 호출부 모듈의 get_settings 를 바꾼다).
"""
import logging
from pathlib import Path
from typing import Awaitable, Callable

from app.ingest import raw_responses
from app.ingest.providers.types import CallResult

logger = logging.getLogger(__name__)


async def measured_call(*, settings, model: str, caller: Callable[[], Awaitable[CallResult]],
                        prompt: str, media: list[Path], schema, sink, context,
                        prompt_hash: str | None, raw_sink, max_output_tokens: int | None) -> CallResult:
    from app.ingest import reuse
    from app.usage import recorder

    s = settings
    key = None
    if raw_sink is not None and context is not None:
        key = await reuse.key_for(context, s, model=model, mode=s.ingest_mode,
                                  prompt=prompt, media=media, schema=schema,
                                  max_output_tokens=max_output_tokens)
        if reuse.lookup_allowed(context, s):
            hit = await reuse.find(raw_sink, context, key, schema)
            if hit is not None:
                await _ledger_reuse(sink, context, s, model, prompt_hash, hit)
                return CallResult(hit.response_text, {}, hit.finish_reason,
                                  hit.raw_response_id, reused=True)
    if context is None:
        reply = await caller()
    else:
        async with recorder.attempt(sink, context, model=model,
                                    mode=s.ingest_mode, prompt_hash=prompt_hash) as rec:
            rec.measure_input(
                input_bytes=len(prompt.encode("utf-8")) + sum(
                    m.stat().st_size for m in media if m.exists()),
                frame_count=len(media) or None,
            )
            reply = await caller()
            rec.reported_model = model
            if reply.usage:
                rec.observe(**reply.usage)
            else:
                rec.partial("공급자가 usage 를 보고하지 않았다")

    raw_id = await raw_responses.record(
        raw_sink, context, model=model, mode=s.ingest_mode,
        prompt_hash=prompt_hash, schema=schema, finish_reason=reply.finish_reason,
        response_text=reply.text, usage=reply.usage, reuse_key=key)
    return reply._replace(raw_response_id=raw_id)


async def _ledger_reuse(sink, context, s, model, prompt_hash, hit) -> None:
    """재사용을 원장에 남긴다 — 이번 실행의 논리 호출로, 비용 0(NOT_BILLABLE)."""
    from app.ingest.reuse import CACHE_STATE_REUSED
    from app.usage import recorder

    async with recorder.attempt(sink, context, model=model,
                                mode=s.ingest_mode, prompt_hash=prompt_hash) as rec:
        rec.not_billable(f"재사용: raw_response_id={hit.raw_response_id}")
        rec.cache_state = CACHE_STATE_REUSED
    logger.info("재사용 call=%s raw_response_id=%s — 모델을 부르지 않았다",
                context.logical_call_id, hit.raw_response_id)
```

`gemini.py` 의 `_measured_call` 본문과 `_ledger_reuse` 를 지우고 아래로 바꾼다(시그니처 동일):

```python
async def _measured_call(prompt: str, media: list[Path], sink, context,
                         *, prompt_hash: str | None = None,
                         schema=None, raw_sink=None,
                         max_output_tokens: int | None = None) -> CallResult:
    """계측을 감싼 Gemini 호출. 본문은 공급자 중립 measured_call 로 옮겼다."""
    from app.ingest.providers import measured

    s = get_settings()
    schema = schema or ExtractionResult
    return await measured.measured_call(
        settings=s, model=s.gemini_model,
        caller=lambda: _call(prompt, media, schema, max_output_tokens=max_output_tokens),
        prompt=prompt, media=media, schema=schema, sink=sink, context=context,
        prompt_hash=prompt_hash, raw_sink=raw_sink, max_output_tokens=max_output_tokens)
```

- [ ] **Step 7: `providers/budget.py`**

```python
"""실행 금액 누적과 상한 (실험용). 상한이 없으면 아무것도 막지 않는다.

요율은 `api/config/rate_card.json`. 요율 없는 모델은 비용을 모른다고 기록할 뿐 0 으로 세지 않는다.
상한에 닿으면 **다음 호출을 부르기 전에** 멈춘다 — 이미 받은 응답은 버리지 않는다.
"""
from decimal import Decimal

from app.usage.rates import load_rate_card


class BudgetExceeded(RuntimeError):
    """금액 상한 도달. 호출부는 그 구역을 실패로 남기고 나머지를 이어간다."""


_LIMIT: Decimal | None = None
_SPENT = Decimal("0")
_UNPRICED: set[str] = set()
_MILLION = Decimal("1000000")


def set_limit(usd: Decimal | None) -> None:
    global _LIMIT, _SPENT
    _LIMIT, _SPENT = usd, Decimal("0")
    _UNPRICED.clear()


def check_before_call() -> None:
    if _LIMIT is not None and _SPENT >= _LIMIT:
        raise BudgetExceeded(f"금액 상한 {_LIMIT} USD 도달 (누적 {_SPENT})")


def add_usage(model: str, usage: dict) -> None:
    global _SPENT
    rate = load_rate_card().model_rate(model)
    if rate["input_per_1m"] is None or rate["output_per_1m"] is None:
        _UNPRICED.add(model)
        return
    out_tokens = int(usage.get("completion_tokens") or 0) + int(usage.get("thought_tokens") or 0)
    _SPENT += (Decimal(int(usage.get("prompt_tokens") or 0)) * rate["input_per_1m"]
               + Decimal(out_tokens) * rate["output_per_1m"]) / _MILLION


def spent() -> Decimal:
    return _SPENT


def unpriced() -> set[str]:
    return set(_UNPRICED)
```

- [ ] **Step 8: `providers/anthropic_call.py`**

```python
"""Anthropic 원시 호출. 이미지(base64) + 지시문 → 구조화 출력(json_schema).

레이아웃 스키마는 모두 strict(extra=forbid, 기본값 없음)라 pydantic schema 를 그대로 쓴다.
temperature 는 보내지 않는다 — Sonnet 5.5 는 기본값이 아닌 sampling 값을 거절한다.
"""
import base64
import logging
from pathlib import Path

import anthropic

from app.config import get_settings
from app.ingest.providers.types import CallResult

logger = logging.getLogger(__name__)

_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
_FINISH = {"end_turn": "STOP", "max_tokens": "MAX_TOKENS"}


def _client(api_key: str):
    return anthropic.AsyncAnthropic(api_key=api_key)


def _image_block(path: Path) -> dict:
    media_type = _MEDIA.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(f"지원하지 않는 이미지 형식: {path.name}")
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


async def call(model: str, prompt: str, images: list[Path], schema,
               max_output_tokens: int | None) -> CallResult:
    s = get_settings()
    if not s.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 가 없다")
    output_config: dict = {"format": {"type": "json_schema", "schema": schema.model_json_schema()}}
    # Haiku 4.5 는 effort 를 받지 않는다
    if s.layout_anthropic_effort and not model.startswith("claude-haiku"):
        output_config["effort"] = s.layout_anthropic_effort
    resp = await _client(s.anthropic_api_key).messages.create(
        model=model,
        max_tokens=max_output_tokens or s.layout_max_output_tokens,
        messages=[{"role": "user",
                   "content": [*(_image_block(p) for p in images), {"type": "text", "text": prompt}]}],
        output_config=output_config,
    )
    if resp.stop_reason == "refusal":
        category = getattr(resp.stop_details, "category", None) if resp.stop_details else None
        raise RuntimeError(f"모델이 거절했다 category={category}")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    u = resp.usage
    usage = {"prompt_tokens": int(u.input_tokens), "completion_tokens": int(u.output_tokens)}
    cached = getattr(u, "cache_read_input_tokens", None)
    if cached is not None:
        usage["cached_tokens"] = int(cached)
    usage["raw"] = u.model_dump()
    return CallResult(text, usage, _FINISH.get(resp.stop_reason, resp.stop_reason))
```

- [ ] **Step 9: `providers/__init__.py`**

```python
"""역할별 모델 호출. `공급자:모델` 지정을 해석해 같은 계측 경로로 부른다."""
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel

from app.config import get_settings
from app.ingest import raw_responses
from app.ingest.providers import anthropic_call, budget, measured

_PROVIDERS = ("gemini", "anthropic")


@dataclass(frozen=True)
class ModelSpec:
    provider: Literal["gemini", "anthropic"]
    model: str


def parse_model_spec(text: str) -> ModelSpec:
    provider, sep, model = (text or "").partition(":")
    if not sep or not model or provider not in _PROVIDERS:
        raise ValueError(f"모델 지정은 '공급자:모델' 이고 공급자는 {_PROVIDERS} 중 하나다: {text!r}")
    return ModelSpec(provider, model)  # type: ignore[arg-type]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def measured_generate(spec: ModelSpec, prompt: str, images: list[Path], schema: type[BaseModel],
                            *, usage_sink=None, usage_context=None, raw_sink=None,
                            max_output_tokens: int | None = None, what: str,
                            mock_build: Callable[[], BaseModel] | None = None) -> BaseModel:
    """한 번 부르고 스키마로 검증해 돌려준다. 잘림·파싱 실패는 예외다(raw_responses 규칙)."""
    s = get_settings()
    if s.ingest_mode == "mock":
        if mock_build is None:
            raise RuntimeError(f"{what}: mock 모드인데 합성 결과가 없다")
        from app.ingest.extract import mock
        return await mock._as_recorded(mock_build, schema, raw_sink=raw_sink,
                                       usage_context=usage_context, prompt=prompt, media=images)

    budget.check_before_call()
    if spec.provider == "gemini":
        from app.ingest.extract import gemini

        async def caller():
            return await gemini._call(prompt, images, schema,
                                      max_output_tokens=max_output_tokens, model=spec.model)
    else:
        async def caller():
            return await anthropic_call.call(spec.model, prompt, images, schema, max_output_tokens)

    reply = await measured.measured_call(
        settings=s, model=spec.model, caller=caller, prompt=prompt, media=images, schema=schema,
        sink=usage_sink, context=usage_context, prompt_hash=_hash(prompt), raw_sink=raw_sink,
        max_output_tokens=max_output_tokens)
    if not reply.reused:
        budget.add_usage(spec.model, reply.usage)
    sink = None if reply.reused else raw_sink
    return await raw_responses.parse_checked(
        sink, usage_context, reply.raw_response_id, reply.finish_reason,
        lambda: schema.model_validate_json(reply.text), what=what)
```

- [ ] **Step 10: `config.py` — 설정과 키 검사**

`gemini_model` 아래에 추가:

```python
    anthropic_api_key: str = ""
    # SCAN 추출 경로. SINGLE — 기존 단일 호출(기준선). LAYOUT — 구역 기반 다단계(설계 W_SCAN_LAYOUT_EXTRACTION_DESIGN)
    scan_extract_mode: Literal["SINGLE", "LAYOUT"] = "SINGLE"
    # 역할별 모델 '공급자:모델'. 판단은 비싼 모델, 반복은 싼 모델
    layout_region_model: str = "anthropic:claude-sonnet-5-5"
    layout_transcribe_model: str = "gemini:gemini-3.6-flash"
    layout_recheck_model: str = "anthropic:claude-sonnet-5-5"
    layout_expand_model: str = "gemini:gemini-3.6-flash"
    # Anthropic effort. None 이면 보내지 않는다(모델 기본값). Haiku 에는 보내지 않는다
    layout_anthropic_effort: Literal["low", "medium", "high"] | None = "low"
    layout_max_output_tokens: int = Field(default=16000, ge=1)
    layout_render_dpi: int = Field(default=200, ge=72)       # 벡터 PDF 렌더 DPI
    layout_region_image_max_px: int = Field(default=1600, ge=256)  # 구역 지도에 넣는 쪽 이미지 긴 변
    layout_band_rows: int = Field(default=5, ge=1)           # 띠 하나의 행 수
    layout_band_overlap_rows: int = Field(default=1, ge=0)   # 띠 사이 겹치는 행 수
    layout_default_row_px: int = Field(default=40, ge=4)     # 예상 행 수가 없을 때 행 높이(원본 px)
    layout_zoom: float = Field(default=2.0, ge=1.0, le=4.0)  # 띠 확대 배율
    layout_ink_threshold: int = Field(default=160, ge=1, le=254)    # 흑백 임계(이하가 글자)
    layout_uncovered_min_area_px: int = Field(default=400, ge=1)    # 빈 영역 검사 최소 면적
    layout_max_bands_per_source: int = Field(default=80, ge=1)
    layout_recheck_max_turns: int = Field(default=3, ge=1)
    layout_recheck_max_calls_per_source: int = Field(default=30, ge=0)
    layout_expand_batch_rows: int = Field(default=10, ge=1)
    layout_fact_confidence: float = Field(default=0.9, ge=0, le=1)
    layout_concurrency: int = Field(default=4, ge=1)
```

기존 `model_validator` 옆에 추가:

```python
    @model_validator(mode="after")
    def _layout_keys(self):
        if self.scan_extract_mode == "LAYOUT" and self.ingest_mode == "real":
            specs = [self.layout_region_model, self.layout_transcribe_model,
                     self.layout_recheck_model, self.layout_expand_model]
            if any(x.startswith("anthropic:") for x in specs) and not self.anthropic_api_key:
                raise ValueError("LAYOUT 모드가 Anthropic 모델을 쓰는데 ANTHROPIC_API_KEY 가 없다")
            if any(x.startswith("gemini:") for x in specs) and not self.gemini_api_key:
                raise ValueError("LAYOUT 모드가 Gemini 모델을 쓰는데 GEMINI_API_KEY 가 없다")
        return self
```
(기존 validator 이름·import 를 확인해 `model_validator` import 가 없으면 추가한다.)

- [ ] **Step 11: 요율표** — `api/config/rate_card.json` 의 `models` 에 추가하고 `version` 을 `"2026-10-06-anthropic"`, `note` 끝에 `" Anthropic 요율 출처: claude-api 문서 Current Models 표(cached 2026-09-25)."` 를 붙인다.

```json
    "claude-sonnet-5-5": {"input_per_1m_tokens": 2.00, "output_per_1m_tokens": 10.00, "cached_input_per_1m_tokens": 0.20},
    "claude-opus-5-5": {"input_per_1m_tokens": 4.00, "output_per_1m_tokens": 20.00, "cached_input_per_1m_tokens": 0.20},
    "claude-haiku-4-5": {"input_per_1m_tokens": 1.00, "output_per_1m_tokens": 5.00, "cached_input_per_1m_tokens": null}
```

- [ ] **Step 12: 통과 확인 + 회귀**

Run: `cd api && pytest tests/test_layout_providers.py tests/test_raw_responses.py tests/test_extraction_eval.py -q`
Expected: 모두 PASS. `test_raw_responses.py` 가 `gemini._measured_call`·`_ledger_reuse` 를 직접 patch 하던 곳이 있으면 대상을 `app.ingest.providers.measured` 로 옮기되 검증 내용은 바꾸지 않는다.
이어서 `pytest -q` 전체를 한 번 돌려 회귀가 없음을 확인한다.

- [ ] **Step 13: 작업 트리에 둔다** (커밋하지 않음)

---

### Task 2: 레이아웃 스키마와 쪽 이미지

**Files:**
- Create: `api/app/ingest/layout/__init__.py` (빈 docstring 만; Task 7 에서 채움), `schemas.py`, `pages.py`
- Test: `api/tests/test_layout_pages.py`

**Interfaces:**
- Produces (`layout/schemas.py`):
  - 모델 출력(strict): `TableInfo`, `Region`, `RegionMap`, `BandRow`, `BandRows`, `ProseLines`, `CropRequest`, `CellAnswer`, `RecheckTurn`, `LayoutFact`, `ExpandResult`
  - 내부: `Box = tuple[int, int, int, int]`, `PageImage(number, path, width, height)`, `PlacedRegion(page, region_id, kind, box, order, table, added_by)`, `TranscribedRow(label, cells, band_index)`, `CellFlag(cell_id, row_index, col, reason, band_index)`, `TableResult(region, header, rows, flags, band_boxes, rerouted)`, `ProseResult(region, lines)`, `Caps(bands_left, recheck_calls_left)`
- Produces (`layout/pages.py`): `page_images(path: Path, workdir: Path, *, render_dpi: int, max_pages: int | None) -> list[PageImage]`, `blank_page(workdir: Path) -> PageImage`

- [ ] **Step 1: 실패하는 테스트** — `api/tests/test_layout_pages.py`

```python
from pathlib import Path

import pytest
from PIL import Image

from app.ingest.layout import pages


def _img(tmp_path: Path, name: str, size=(300, 200)) -> Path:
    p = tmp_path / name
    Image.new("RGB", size, "white").save(p)
    return p


def test_png_is_one_page(tmp_path):
    src = _img(tmp_path, "a.png")
    out = pages.page_images(src, tmp_path / "w", render_dpi=200, max_pages=None)
    assert [(p.number, p.width, p.height) for p in out] == [(1, 300, 200)]
    assert out[0].path.exists() and out[0].path.suffix == ".png"


def test_scanned_pdf_uses_embedded_image_at_native_size(tmp_path):
    pdf = tmp_path / "s.pdf"
    Image.new("RGB", (640, 480), "white").save(pdf, "PDF", resolution=144)
    out = pages.page_images(pdf, tmp_path / "w", render_dpi=200, max_pages=None)
    assert len(out) == 1 and (out[0].width, out[0].height) == (640, 480)


def test_pdf_render_fallback(tmp_path, monkeypatch):
    pdf = tmp_path / "s.pdf"
    Image.new("RGB", (144, 72), "white").save(pdf, "PDF", resolution=72)
    monkeypatch.setattr(pages, "_embedded_image", lambda page: None)
    out = pages.page_images(pdf, tmp_path / "w", render_dpi=144, max_pages=None)
    assert (out[0].width, out[0].height) == (288, 144)


def test_max_pages(tmp_path):
    pdf = tmp_path / "m.pdf"
    a, b = Image.new("RGB", (50, 50), "white"), Image.new("RGB", (50, 50), "white")
    a.save(pdf, "PDF", save_all=True, append_images=[b])
    with pytest.raises(ValueError, match="쪽 수"):
        pages.page_images(pdf, tmp_path / "w", render_dpi=72, max_pages=1)


def test_blank_page(tmp_path):
    p = pages.blank_page(tmp_path)
    assert p.number == 1 and p.path.exists()
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_layout_pages.py -q` → FAIL (`No module named 'app.ingest.layout'`)

- [ ] **Step 3: `layout/__init__.py`** — `"""SCAN 구역 기반 다단계 추출 (설계 W_SCAN_LAYOUT_EXTRACTION_DESIGN)."""` 한 줄.

- [ ] **Step 4: `layout/schemas.py`**

```python
"""레이아웃 경로의 자료형.

모델 출력 스키마는 strict 다(extra=forbid, 기본값 없음) — Anthropic json_schema 가 그대로 받는다.
좌표: 모델은 0~1 정규화, 코드는 원본 px 정수 `Box=(x0, y0, x1, y1)`.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

Box = tuple[int, int, int, int]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TableInfo(_Strict):
    header_columns: list[str]
    expected_rows: int | None
    row_label_column: int | None


class Region(_Strict):
    kind: Literal["TABLE", "PROSE", "FORM", "PHOTO", "FOOTNOTE"]
    bbox: list[float]          # [x0, y0, x1, y1] 0~1
    reading_order: int
    table: TableInfo | None


class RegionMap(_Strict):
    regions: list[Region]


class BandRow(_Strict):
    row_label: str | None
    cells: list[str]
    cut_top: bool
    cut_bottom: bool


class BandRows(_Strict):
    rows: list[BandRow]


class ProseLines(_Strict):
    lines: list[str]


class CropRequest(_Strict):
    bbox: list[float]          # 구역 안 0~1
    scale: float


class CellAnswer(_Strict):
    cell_id: str
    value: str | None
    unreadable_reason: str | None


class RecheckTurn(_Strict):
    crops: list[CropRequest]
    answers: list[CellAnswer]


class LayoutFact(_Strict):
    row_ref: str               # 행 라벨 또는 '행N'
    original_assertion: str
    subject: str
    variant: str
    attribute: str
    value: str
    unit: str
    polarity: Literal["AFFIRM", "NEGATE"]
    conditions: list[str]
    exceptions: list[str]
    order: int


class ExpandResult(_Strict):
    facts: list[LayoutFact]


@dataclass
class PageImage:
    number: int
    path: Path
    width: int
    height: int


@dataclass
class PlacedRegion:
    page: int
    region_id: str             # p{쪽}-r{순번}
    kind: str                  # Region.kind 또는 UNCLASSIFIED
    box: Box
    order: int
    table: TableInfo | None
    added_by: Literal["MODEL", "COVERAGE", "FALLBACK"]


@dataclass
class TranscribedRow:
    label: str | None
    cells: list[str]
    band_index: int


@dataclass
class CellFlag:
    cell_id: str               # {region_id}:{row_index}:{col} 또는 {region_id}:{row_index}:row
    row_index: int
    col: int | None            # None 이면 행 단위 문제
    reason: Literal["OVERLAP_MISMATCH", "COLUMN_COUNT", "ROW_MISSING", "ROW_COUNT"]
    band_index: int


@dataclass
class TableResult:
    region: PlacedRegion
    header: list[str]
    rows: list[TranscribedRow]
    flags: list[CellFlag]
    band_boxes: list[Box]
    rerouted: bool = False
    unreadable: dict[tuple[int, int], str] = field(default_factory=dict)  # (row, col) → 사유


@dataclass
class ProseResult:
    region: PlacedRegion
    lines: list[str]


@dataclass
class Caps:
    bands_left: int
    recheck_calls_left: int
```

- [ ] **Step 5: `layout/pages.py`**

```python
"""① 쪽 이미지. 스캔 PDF 는 박힌 원본 이미지를 그대로, 벡터 PDF 는 렌더링, 사진은 그대로."""
import io
from pathlib import Path

from PIL import Image

from app.ingest.layout.schemas import PageImage

_MIN_TEXT_CHARS = 20   # 이보다 글이 적고 이미지가 하나면 스캔 쪽으로 본다


def _embedded_image(page) -> Image.Image | None:
    """스캔 쪽이면 박힌 이미지 하나를 돌려준다. 글이 있거나 이미지가 여럿이면 None."""
    try:
        images = list(page.images)
    except Exception:
        return None
    text = (page.extract_text() or "").strip()
    if len(images) != 1 or len(text) >= _MIN_TEXT_CHARS:
        return None
    return Image.open(io.BytesIO(images[0].data)).convert("RGB")


def _render(path: Path, index: int, dpi: int) -> Image.Image:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        return pdf[index].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        pdf.close()


def _save(img: Image.Image, workdir: Path, number: int) -> PageImage:
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / f"page-{number}.png"
    img.save(out)
    return PageImage(number, out, img.width, img.height)


def page_images(path: Path, workdir: Path, *, render_dpi: int,
                max_pages: int | None) -> list[PageImage]:
    if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
        return [_save(Image.open(path).convert("RGB"), workdir, 1)]
    import pypdf

    reader = pypdf.PdfReader(str(path))
    if max_pages is not None and len(reader.pages) > max_pages:
        raise ValueError(f"쪽 수 {len(reader.pages)} 가 상한 {max_pages} 를 넘는다")
    out = []
    for i, page in enumerate(reader.pages):
        img = _embedded_image(page) or _render(path, i, render_dpi)
        out.append(_save(img, workdir, i + 1))
    return out


def blank_page(workdir: Path) -> PageImage:
    """mock 모드용 빈 쪽. 원본을 내려받지 않는 mock 에서 경로를 끝까지 돌리기 위해 쓴다."""
    return _save(Image.new("RGB", (800, 600), "white"), workdir, 1)
```

- [ ] **Step 6: 통과 확인** — Run: `pytest tests/test_layout_pages.py -q` → PASS

- [ ] **Step 7: 작업 트리에 둔다**

---

### Task 3: 구역 지도와 빈 영역 검사

**Files:**
- Create: `api/app/ingest/layout/prompts.py`, `api/app/ingest/layout/regions.py`, `api/prompts/layout_region.ko.txt`
- Test: `api/tests/test_layout_regions.py`

**Interfaces:**
- Consumes: `measured_generate`, `parse_model_spec` (Task 1); `PageImage`, `PlacedRegion`, `RegionMap`, `Region`, `Box` (Task 2)
- Produces:
  - `prompts.render(name: str, **values: str) -> str` — `api/prompts/layout_{name}.ko.txt` 의 `{key}` 치환
  - `regions.place_regions(page: PageImage, region_map: RegionMap, *, min_px: int = 8) -> list[PlacedRegion]`
  - `regions.uncovered_boxes(image_path: Path, covered: list[Box], *, ink_threshold: int, min_area_px: int, grid_px: int = 8) -> list[Box]`
  - `async regions.map_page(page: PageImage, workdir: Path, *, ctx, usage_sink, raw_sink) -> tuple[list[PlacedRegion], list[str]]` — `ctx(label: str)` 는 UsageContext 또는 None 을 돌려주는 함수, 두 번째 반환값은 미해결 사유

- [ ] **Step 1: 실패하는 테스트** — `api/tests/test_layout_regions.py`

```python
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from app.ingest.layout import regions
from app.ingest.layout.schemas import PageImage, Region, RegionMap, TableInfo


def _page(tmp_path, draw_boxes=()):
    p = tmp_path / "page.png"
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    for b in draw_boxes:
        d.rectangle(b, fill="black")
    img.save(p)
    return PageImage(1, p, 400, 300)


def test_place_regions_scales_clamps_and_orders(tmp_path):
    page = _page(tmp_path)
    rm = RegionMap(regions=[
        Region(kind="PROSE", bbox=[0.5, 0.5, 1.2, 1.0], reading_order=2, table=None),
        Region(kind="TABLE", bbox=[0.0, 0.0, 0.5, 0.5], reading_order=1,
               table=TableInfo(header_columns=["A", "B"], expected_rows=3, row_label_column=0)),
        Region(kind="PROSE", bbox=[0.1, 0.1, 0.101, 0.101], reading_order=3, table=None),
    ])
    out = regions.place_regions(page, rm)
    assert [r.region_id for r in out] == ["p1-r1", "p1-r2"]
    assert out[0].kind == "TABLE" and out[0].box == (0, 0, 200, 150)
    assert out[1].box == (200, 150, 400, 300)        # 1.2 → 쪽 끝으로 자름
    assert all(r.added_by == "MODEL" for r in out)


def test_uncovered_ink_becomes_region(tmp_path):
    page = _page(tmp_path, draw_boxes=[(10, 10, 60, 40), (300, 250, 360, 290)])
    out = regions.uncovered_boxes(page.path, [(0, 0, 100, 100)],
                                  ink_threshold=160, min_area_px=200)
    assert len(out) == 1
    x0, y0, x1, y1 = out[0]
    assert x0 <= 300 and y0 <= 250 and x1 >= 360 and y1 >= 290


def test_uncovered_ignores_small_specks(tmp_path):
    page = _page(tmp_path, draw_boxes=[(200, 200, 202, 202)])
    assert regions.uncovered_boxes(page.path, [], ink_threshold=160, min_area_px=200) == []


@pytest.mark.asyncio
async def test_map_page_falls_back_on_model_failure(tmp_path):
    page = _page(tmp_path, draw_boxes=[(10, 10, 60, 40)])
    st = NS(layout_region_model="anthropic:claude-sonnet-5-5", layout_region_image_max_px=200,
            layout_ink_threshold=160, layout_uncovered_min_area_px=200)

    async def boom(*a, **k):
        raise RuntimeError("합성 실패")
    with patch.object(regions, "get_settings", return_value=st), \
         patch.object(regions, "measured_generate", boom):
        placed, unresolved = await regions.map_page(page, tmp_path, ctx=lambda l: None,
                                                    usage_sink=None, raw_sink=None)
    assert [(r.kind, r.added_by, r.box) for r in placed] == [("UNCLASSIFIED", "FALLBACK", (0, 0, 400, 300))]
    assert unresolved and "구역 지도 실패" in unresolved[0]


@pytest.mark.asyncio
async def test_map_page_adds_coverage_region(tmp_path):
    page = _page(tmp_path, draw_boxes=[(10, 10, 60, 40), (300, 250, 360, 290)])
    st = NS(layout_region_model="anthropic:claude-sonnet-5-5", layout_region_image_max_px=200,
            layout_ink_threshold=160, layout_uncovered_min_area_px=200)

    async def fake(spec, prompt, images, schema, **k):
        return RegionMap(regions=[Region(kind="PROSE", bbox=[0, 0, 0.25, 0.25],
                                         reading_order=1, table=None)])
    with patch.object(regions, "get_settings", return_value=st), \
         patch.object(regions, "measured_generate", fake):
        placed, _ = await regions.map_page(page, tmp_path, ctx=lambda l: None,
                                           usage_sink=None, raw_sink=None)
    assert [r.added_by for r in placed] == ["MODEL", "COVERAGE"]
    assert placed[1].kind == "UNCLASSIFIED" and placed[1].region_id == "p1-r2"
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_layout_regions.py -q` → FAIL

- [ ] **Step 3: `layout/prompts.py`**

```python
"""레이아웃 프롬프트 파일. 코드에 지시문을 두지 않는다."""
from pathlib import Path

_DIR = Path(__file__).resolve().parents[3] / "prompts"


def render(name: str, **values: str) -> str:
    text = (_DIR / f"layout_{name}.ko.txt").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text
```

- [ ] **Step 4: `api/prompts/layout_region.ko.txt`**

```
너는 문서 한 쪽을 처음 훑어보는 사람이다. 내용을 옮기지 말고 **어디에 무엇이 있는지만** 나눈다.

구역 종류:
- TABLE: 행과 열이 있는 표. 머리글 열 이름을 왼쪽부터 그대로 적는다
- PROSE: 문단·목록 글
- FORM: 칸에 값을 적는 양식
- PHOTO: 사진·그림
- FOOTNOTE: 표나 본문 아래의 작은 글씨 각주·단서

규칙:
- bbox 는 [왼쪽, 위, 오른쪽, 아래] 를 쪽 전체 대비 0~1 로 적는다. 글자가 잘리지 않게 넉넉히 잡는다
- 쪽의 모든 글자가 어느 구역엔가 들어가야 한다. 작은 글씨도 빠뜨리지 않는다
- 표가 쪽을 넘어 이어지면 이 쪽에 보이는 부분만 한 구역으로 잡는다
- table.expected_rows 는 머리글을 뺀 데이터 행 수의 대략값, 셀 수 없으면 null
- table.row_label_column 은 행 번호가 적힌 열의 위치(0부터), 없으면 null
- TABLE 이 아니면 table 은 null
- reading_order 는 사람이 읽는 순서(1부터)
```

- [ ] **Step 5: `layout/regions.py`**

```python
"""② 구역 지도. 판단 모델이 구역을 나누고, 코드가 좌표를 정리하고 빠진 글자 영역을 잡는다."""
import logging
from pathlib import Path

from PIL import Image

from app.config import get_settings
from app.ingest.layout import prompts
from app.ingest.layout.schemas import Box, PageImage, PlacedRegion, Region, RegionMap
from app.ingest.providers import measured_generate, parse_model_spec

logger = logging.getLogger(__name__)


def _to_box(bbox: list[float], w: int, h: int) -> Box:
    x0, y0, x1, y1 = (list(bbox) + [0, 0, 1, 1])[:4]
    clamp = lambda v: min(max(float(v), 0.0), 1.0)  # noqa: E731
    x0, x1 = sorted((clamp(x0), clamp(x1)))
    y0, y1 = sorted((clamp(y0), clamp(y1)))
    return (round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))


def place_regions(page: PageImage, region_map: RegionMap, *, min_px: int = 8) -> list[PlacedRegion]:
    out: list[PlacedRegion] = []
    for r in sorted(region_map.regions, key=lambda r: r.reading_order):
        box = _to_box(r.bbox, page.width, page.height)
        if box[2] - box[0] < min_px or box[3] - box[1] < min_px:
            continue
        out.append(PlacedRegion(page.number, f"p{page.number}-r{len(out) + 1}", r.kind, box,
                                len(out) + 1, r.table if r.kind == "TABLE" else None, "MODEL"))
    return out


def uncovered_boxes(image_path: Path, covered: list[Box], *, ink_threshold: int,
                    min_area_px: int, grid_px: int = 8) -> list[Box]:
    """어느 구역에도 안 든 글자 덩어리. 격자 칸 단위로 이웃을 묶는다(numpy 없이)."""
    img = Image.open(image_path).convert("L")
    w, h = img.size
    cols, rows = (w + grid_px - 1) // grid_px, (h + grid_px - 1) // grid_px
    px = img.load()
    inked = set()
    for gy in range(rows):
        for gx in range(cols):
            x0, y0 = gx * grid_px, gy * grid_px
            cx, cy = x0 + grid_px // 2, y0 + grid_px // 2
            if any(b[0] <= cx < b[2] and b[1] <= cy < b[3] for b in covered):
                continue
            if any(px[x, y] <= ink_threshold
                   for y in range(y0, min(y0 + grid_px, h))
                   for x in range(x0, min(x0 + grid_px, w))):
                inked.add((gx, gy))
    out: list[Box] = []
    seen: set = set()
    for start in inked:
        if start in seen:
            continue
        stack, cells = [start], []
        seen.add(start)
        while stack:
            gx, gy = stack.pop()
            cells.append((gx, gy))
            for nx, ny in ((gx + 1, gy), (gx - 1, gy), (gx, gy + 1), (gx, gy - 1)):
                if (nx, ny) in inked and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        box = (min(xs) * grid_px, min(ys) * grid_px,
               min((max(xs) + 1) * grid_px, w), min((max(ys) + 1) * grid_px, h))
        if (box[2] - box[0]) * (box[3] - box[1]) >= min_area_px:
            out.append(box)
    return sorted(out, key=lambda b: (b[1], b[0]))


def _thumbnail(page: PageImage, workdir: Path, max_px: int) -> Path:
    img = Image.open(page.path)
    img.thumbnail((max_px, max_px))
    out = workdir / f"page-{page.number}-map.png"
    img.save(out)
    return out


def _whole_page(page: PageImage) -> RegionMap:
    return RegionMap(regions=[Region(kind="PROSE", bbox=[0, 0, 1, 1], reading_order=1, table=None)])


async def map_page(page: PageImage, workdir: Path, *, ctx, usage_sink,
                   raw_sink) -> tuple[list[PlacedRegion], list[str]]:
    s = get_settings()
    unresolved: list[str] = []
    try:
        region_map = await measured_generate(
            parse_model_spec(s.layout_region_model), prompts.render("region"),
            [_thumbnail(page, workdir, s.layout_region_image_max_px)], RegionMap,
            usage_sink=usage_sink, usage_context=ctx(f"p{page.number}.map"), raw_sink=raw_sink,
            what="구역 지도", mock_build=lambda: _whole_page(page))
        placed = place_regions(page, region_map)
    except Exception as exc:
        logger.warning("구역 지도 실패 page=%s: %s — 쪽 전체를 한 구역으로 둔다", page.number, exc)
        unresolved.append(f"[구역 지도 실패] {page.number}쪽: {type(exc).__name__} — 쪽 전체를 한 구역으로 읽었다")
        placed = []
    if not placed:
        return [PlacedRegion(page.number, f"p{page.number}-r1", "UNCLASSIFIED",
                             (0, 0, page.width, page.height), 1, None, "FALLBACK")], unresolved
    for box in uncovered_boxes(page.path, [r.box for r in placed],
                               ink_threshold=s.layout_ink_threshold,
                               min_area_px=s.layout_uncovered_min_area_px):
        placed.append(PlacedRegion(page.number, f"p{page.number}-r{len(placed) + 1}",
                                   "UNCLASSIFIED", box, len(placed) + 1, None, "COVERAGE"))
    return placed, unresolved
```

- [ ] **Step 6: 통과 확인** — Run: `pytest tests/test_layout_regions.py -q` → PASS

- [ ] **Step 7: 작업 트리에 둔다**

---

### Task 4: 띠 전사와 구조 검사

**Files:**
- Create: `api/app/ingest/layout/transcribe.py`, `api/prompts/layout_table_band.ko.txt`, `api/prompts/layout_prose.ko.txt`, `api/prompts/layout_photo.ko.txt`
- Test: `api/tests/test_layout_transcribe.py`

**Interfaces:**
- Consumes: Task 1·2·3 (`measured_generate`, `parse_model_spec`, `prompts.render`, 스키마)
- Produces:
  - `plan_bands(box: Box, expected_rows: int | None, *, rows_per_band: int, overlap_rows: int, default_row_px: int) -> list[Box]`
  - `crop_zoom(image_path: Path, box: Box, scale: float, out_path: Path) -> Path`
  - `merge_bands(bands: list[list[BandRow]], header: list[str]) -> tuple[list[TranscribedRow], list[CellFlag]]` — 겹침 비교 플래그 포함(region_id 는 호출부가 `cell_id` 접두로 채우도록 `""`)
  - `fill_down(rows: list[TranscribedRow]) -> None`
  - `check_table(rows, header, expected_rows, row_label_column) -> list[CellFlag]`
  - `needs_reroute(rows, header) -> bool`
  - `async transcribe_table(region: PlacedRegion, page: PageImage, workdir: Path, *, caps: Caps, ctx, usage_sink, raw_sink, spec_text: str | None = None, band_indexes: list[int] | None = None) -> TableResult`
  - `async transcribe_text(region, page, workdir, *, kind_prompt: Literal["prose", "photo"], caps, ctx, usage_sink, raw_sink) -> ProseResult`

- [ ] **Step 1: 실패하는 테스트** — `api/tests/test_layout_transcribe.py`

```python
from PIL import Image

from app.ingest.layout import transcribe as t
from app.ingest.layout.schemas import BandRow, TranscribedRow


def _row(label, cells, top=False, bottom=False):
    return BandRow(row_label=label, cells=cells, cut_top=top, cut_bottom=bottom)


def test_plan_bands_overlap_and_cover():
    bands = t.plan_bands((0, 0, 100, 200), 10, rows_per_band=4, overlap_rows=1, default_row_px=40)
    assert bands[0] == (0, 0, 100, 80)
    assert bands[1][1] == 60                     # 한 행(20px) 겹침
    assert bands[-1][3] == 200
    assert t.plan_bands((0, 0, 100, 50), None, rows_per_band=4, overlap_rows=1,
                        default_row_px=40) == [(0, 0, 100, 50)]


def test_crop_zoom(tmp_path):
    src = tmp_path / "p.png"
    Image.new("RGB", (100, 100), "white").save(src)
    out = t.crop_zoom(src, (10, 10, 30, 20), 2.0, tmp_path / "c.png")
    assert Image.open(out).size == (40, 20)


def test_merge_labeled_overlap_keeps_first_and_flags_mismatch():
    header = ["번호", "이름", "값"]
    rows, flags = t.merge_bands([
        [_row("1", ["1", "메뉴A", "10"]), _row("2", ["2", "메뉴B", "20"])],
        [_row("2", ["2", "메뉴B", "28"]), _row("3", ["3", "메뉴C", "30"])],
    ], header)
    assert [r.label for r in rows] == ["1", "2", "3"]
    assert rows[1].cells[2] == "20"
    assert [(f.row_index, f.col, f.reason) for f in flags] == [(1, 2, "OVERLAP_MISMATCH")]


def test_merge_unlabeled_overlap_dedup():
    header = ["이름", "값"]
    rows, flags = t.merge_bands([
        [_row(None, ["메뉴A", "10"]), _row(None, ["메뉴B", "20"])],
        [_row(None, ["메뉴B", "20"]), _row(None, ["메뉴C", "30"])],
    ], header)
    assert [r.cells[0] for r in rows] == ["메뉴A", "메뉴B", "메뉴C"] and flags == []


def test_merge_drops_cut_rows_at_band_edges():
    header = ["이름", "값"]
    rows, _ = t.merge_bands([
        [_row(None, ["메뉴A", "10"]), _row(None, ["메뉴", ""], bottom=True)],
        [_row(None, ["메뉴B", "20"], top=False)],
    ], header)
    assert [r.cells[0] for r in rows] == ["메뉴A", "메뉴B"]


def test_fill_down():
    rows = [TranscribedRow("1", ["1", "섞기", "a"], 0), TranscribedRow("2", ["2", "↑", "b"], 0)]
    t.fill_down(rows)
    assert rows[1].cells[1] == "섞기"


def test_column_count_flag():
    rows = [TranscribedRow("1", ["1", "메뉴A"], 0), TranscribedRow("2", ["2", "메뉴B", "20", "?"], 0),
            TranscribedRow("3", ["3", "메뉴C", "30"], 0)]
    flags = t.check_table(rows, ["번호", "이름", "값"], None, 0)
    assert {(f.row_index, f.reason) for f in flags} == {(0, "COLUMN_COUNT"), (1, "COLUMN_COUNT")}


def test_row_missing_and_count_flags():
    rows = [TranscribedRow("1", ["1", "a"], 0), TranscribedRow("3", ["3", "c"], 1)]
    flags = t.check_table(rows, ["번호", "이름"], 4, 0)
    reasons = sorted(f.reason for f in flags)
    assert reasons == ["ROW_COUNT", "ROW_MISSING"]


def test_needs_reroute():
    bad = [TranscribedRow(None, ["한 줄 글"], 0), TranscribedRow(None, ["또 한 줄"], 0)]
    assert t.needs_reroute(bad, ["번호", "이름", "값"]) is True
    good = [TranscribedRow("1", ["1", "a", "b"], 0)]
    assert t.needs_reroute(good, ["번호", "이름", "값"]) is False
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_layout_transcribe.py -q` → FAIL

- [ ] **Step 3: 프롬프트 3개**

`api/prompts/layout_table_band.ko.txt`:
```
첨부 이미지는 표의 일부를 가로로 잘라 확대한 띠다. **보이는 칸을 그대로 옮긴다.** 해석·환산·요약하지 않는다.

머리글 열(왼쪽부터): {header}

규칙:
- 행마다 cells 에 머리글 순서대로 칸 글자를 그대로 적는다. 칸 수는 머리글 열 수와 같아야 한다
- 빈 칸은 "" 로, 'x' 나 '-' 표시는 그대로 적는다
- 위 행과 합쳐진(병합된) 칸은 "↑" 로 적는다. 값을 복사하지 않는다
- 행 번호가 보이면 row_label 에 적고, 없으면 null
- 띠의 위 끝에서 잘려 일부만 보이는 행은 cut_top=true, 아래 끝에서 잘린 행은 cut_bottom=true
- 읽을 수 없는 글자를 추측하지 않는다. 확실하지 않은 칸은 보이는 대로 적고 끝에 "(?)" 를 붙인다
- 머리글 행은 옮기지 않는다
```

`api/prompts/layout_prose.ko.txt`:
```
첨부 이미지는 문서의 글 구역을 잘라 확대한 것이다. **보이는 글을 줄 단위로 그대로 옮긴다.**
요약·설명·환산하지 않는다. 읽을 수 없는 글자는 추측하지 말고 "(?)" 로 남긴다.
줄 순서는 사람이 읽는 순서다. 표처럼 보여도 그대로 줄로 옮긴다(칸 사이는 " | ").
```

`api/prompts/layout_photo.ko.txt`:
```
첨부 이미지는 문서 안의 사진·그림 구역이다. 사진 속에 **보이는 글자**와 **업무에 필요한 사실로 보이는 것**만 줄 단위로 적는다.
보이지 않는 것을 추정하지 않는다. 장식·분위기 묘사는 적지 않는다.
```

- [ ] **Step 4: `layout/transcribe.py`**

```python
"""③ 구역별 전사. 표는 띠로 잘라 칸 원문만 받고, 병합·검사는 코드가 한다."""
import asyncio
import logging
import re
from pathlib import Path

from PIL import Image

from app.config import get_settings
from app.ingest.layout import prompts
from app.ingest.layout.schemas import (BandRow, BandRows, Box, Caps, CellFlag, PageImage,
                                       PlacedRegion, ProseLines, ProseResult, TableResult,
                                       TranscribedRow)
from app.ingest.providers import measured_generate, parse_model_spec

logger = logging.getLogger(__name__)
_FILL = "↑"


def plan_bands(box: Box, expected_rows: int | None, *, rows_per_band: int, overlap_rows: int,
               default_row_px: int) -> list[Box]:
    x0, y0, x1, y1 = box
    height = y1 - y0
    rows = expected_rows or max(1, height // default_row_px)
    row_h = height / rows
    band_h = row_h * rows_per_band
    step = row_h * max(1, rows_per_band - overlap_rows)
    if band_h >= height:
        return [box]
    bands, top = [], 0.0
    while True:
        bottom = min(top + band_h, height)
        bands.append((x0, y0 + round(top), x1, y0 + round(bottom)))
        if bottom >= height:
            return bands
        top += step


def crop_zoom(image_path: Path, box: Box, scale: float, out_path: Path) -> Path:
    img = Image.open(image_path).crop(box)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                     Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def _same(a: list[str], b: list[str]) -> bool:
    return [c.strip() for c in a] == [c.strip() for c in b]


def merge_bands(bands: list[list[BandRow]], header: list[str]) -> tuple[list[TranscribedRow], list[CellFlag]]:
    rows: list[TranscribedRow] = []
    flags: list[CellFlag] = []
    by_label: dict[str, int] = {}
    last = len(bands) - 1
    for bi, band in enumerate(bands):
        prev_tail = [r for r in rows if r.band_index == bi - 1][-3:]
        for r in band:
            if (r.cut_top and bi > 0) or (r.cut_bottom and bi < last):
                continue                        # 이웃 띠에 온전히 있다
            label = (r.row_label or "").strip() or None
            if label is not None and label in by_label:
                idx = by_label[label]
                for col, (a, b) in enumerate(zip(rows[idx].cells, r.cells)):
                    if a.strip() != b.strip():
                        flags.append(CellFlag(f":{idx}:{col}", idx, col, "OVERLAP_MISMATCH", bi))
                continue
            if label is None and any(_same(p.cells, r.cells) for p in prev_tail):
                continue                        # 라벨 없는 겹침 행
            if label is not None:
                by_label[label] = len(rows)
            rows.append(TranscribedRow(label, list(r.cells), bi))
    return rows, flags


def fill_down(rows: list[TranscribedRow]) -> None:
    for i, row in enumerate(rows):
        for col, cell in enumerate(row.cells):
            if cell.strip() == _FILL and i > 0 and col < len(rows[i - 1].cells):
                row.cells[col] = rows[i - 1].cells[col]


def check_table(rows: list[TranscribedRow], header: list[str], expected_rows: int | None,
                row_label_column: int | None) -> list[CellFlag]:
    flags: list[CellFlag] = []
    for i, r in enumerate(rows):
        if len(r.cells) != len(header):
            flags.append(CellFlag(f":{i}:row", i, None, "COLUMN_COUNT", r.band_index))
    numbers = {}
    for i, r in enumerate(rows):
        if r.label and re.fullmatch(r"\d+", r.label.strip()):
            numbers[int(r.label)] = i
    if numbers:
        lo, hi = min(numbers), max(numbers)
        missing = [n for n in range(lo, hi + 1) if n not in numbers]
        for n in missing:
            before = max((k for k in numbers if k < n), default=lo)
            i = numbers[before]
            flags.append(CellFlag(f":{i}:row", i, None, "ROW_MISSING", rows[i].band_index))
    if expected_rows and len(rows) < expected_rows:
        i = len(rows) - 1
        flags.append(CellFlag(f":{i}:row", i, None, "ROW_COUNT", rows[i].band_index if rows else 0))
    return flags


def needs_reroute(rows: list[TranscribedRow], header: list[str]) -> bool:
    if not rows:
        return True
    bad = sum(1 for r in rows if len(r.cells) != len(header))
    return bad * 2 > len(rows)


async def _band_call(spec_text, region, page, workdir, bi, box, header, caps, ctx, usage_sink, raw_sink):
    s = get_settings()
    if caps.bands_left <= 0:
        raise RuntimeError("띠 호출 상한 도달")
    caps.bands_left -= 1
    img = crop_zoom(page.path, box, s.layout_zoom, workdir / f"{region.region_id}-b{bi}.png")
    result = await measured_generate(
        parse_model_spec(spec_text), prompts.render("table_band", header=" | ".join(header)),
        [img], BandRows, usage_sink=usage_sink, usage_context=ctx(f"{region.region_id}.b{bi}"),
        raw_sink=raw_sink, what="띠 전사",
        mock_build=lambda: BandRows(rows=[BandRow(row_label=str(k + 1),
                                                  cells=[f"{h}{k + 1}" for h in header],
                                                  cut_top=False, cut_bottom=False)
                                          for k in range(2)]))
    return result.rows


async def transcribe_table(region: PlacedRegion, page: PageImage, workdir: Path, *, caps: Caps,
                           ctx, usage_sink, raw_sink, spec_text: str | None = None,
                           band_indexes: list[int] | None = None) -> TableResult:
    """band_indexes 를 주면 그 띠만 다시 부른다(재전사). 결과 TableResult 는 그 띠의 행만 담는다."""
    s = get_settings()
    info = region.table
    header = list(info.header_columns) if info else []
    boxes = plan_bands(region.box, info.expected_rows if info else None,
                       rows_per_band=s.layout_band_rows, overlap_rows=s.layout_band_overlap_rows,
                       default_row_px=s.layout_default_row_px)
    targets = band_indexes if band_indexes is not None else list(range(len(boxes)))
    gate = asyncio.Semaphore(s.layout_concurrency)

    async def one(bi):
        async with gate:
            return await _band_call(spec_text or s.layout_transcribe_model, region, page, workdir,
                                    bi, boxes[bi], header, caps, ctx, usage_sink, raw_sink)
    results = await asyncio.gather(*(one(bi) for bi in targets))
    by_band: list[list[BandRow]] = [[] for _ in boxes]
    for bi, band_rows in zip(targets, results):
        by_band[bi] = band_rows
    rows, flags = merge_bands([by_band[bi] for bi in range(len(boxes))], header)
    fill_down(rows)
    flags += check_table(rows, header, info.expected_rows if info else None,
                         info.row_label_column if info else None)
    for f in flags:
        f.cell_id = f"{region.region_id}{f.cell_id}"
    return TableResult(region, header, rows, flags, boxes, rerouted=needs_reroute(rows, header))


async def transcribe_text(region: PlacedRegion, page: PageImage, workdir: Path, *, kind_prompt: str,
                          caps: Caps, ctx, usage_sink, raw_sink) -> ProseResult:
    s = get_settings()
    boxes = plan_bands(region.box, None, rows_per_band=s.layout_band_rows * 3,
                       overlap_rows=s.layout_band_overlap_rows, default_row_px=s.layout_default_row_px)
    lines: list[str] = []
    for bi, box in enumerate(boxes):
        if caps.bands_left <= 0:
            raise RuntimeError("띠 호출 상한 도달")
        caps.bands_left -= 1
        img = crop_zoom(page.path, box, s.layout_zoom, workdir / f"{region.region_id}-t{bi}.png")
        got = await measured_generate(
            parse_model_spec(s.layout_transcribe_model), prompts.render(kind_prompt), [img], ProseLines,
            usage_sink=usage_sink, usage_context=ctx(f"{region.region_id}.t{bi}"), raw_sink=raw_sink,
            what="글 전사", mock_build=lambda: ProseLines(lines=[f"{region.region_id} 합성 줄"]))
        for line in got.lines:
            if line.strip() and line.strip() not in lines[-3:]:   # 겹침 줄 중복 제거
                lines.append(line.strip())
    return ProseResult(region, lines)
```

- [ ] **Step 5: 통과 확인** — Run: `pytest tests/test_layout_transcribe.py -q` → PASS

- [ ] **Step 6: 작업 트리에 둔다**

---

### Task 5: 재확인 — 띠 재전사와 칸 질의 루프

**Files:**
- Create: `api/app/ingest/layout/recheck.py`, `api/prompts/layout_recheck.ko.txt`
- Test: `api/tests/test_layout_recheck.py`

**Interfaces:**
- Consumes: `transcribe_table`, `crop_zoom`, `merge_bands` 결과형 `TableResult`, `CellFlag`, `Caps`, `RecheckTurn`, `CellAnswer`, `CropRequest`
- Produces:
  - `async recheck_rows(table: TableResult, page, workdir, *, caps, ctx, usage_sink, raw_sink) -> TableResult` — 행 단위 플래그의 띠를 재확인 모델로 다시 전사해 행을 합친 새 `TableResult`
  - `async resolve_cells(table: TableResult, page, workdir, *, caps, ctx, usage_sink, raw_sink) -> None` — 칸 플래그를 답으로 채우거나 `table.unreadable[(row, col)]` 에 사유
  - `crop_box(region_box: Box, req: CropRequest) -> Box`

- [ ] **Step 1: 실패하는 테스트** — `api/tests/test_layout_recheck.py`

```python
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from PIL import Image

from app.ingest.layout import recheck
from app.ingest.layout.schemas import (Caps, CellAnswer, CellFlag, CropRequest, PageImage,
                                       PlacedRegion, RecheckTurn, TableInfo, TableResult,
                                       TranscribedRow)

ST = NS(layout_recheck_model="anthropic:claude-sonnet-5-5", layout_recheck_max_turns=2,
        layout_zoom=2.0)


def _table(tmp_path):
    p = tmp_path / "page.png"
    Image.new("RGB", (200, 200), "white").save(p)
    page = PageImage(1, p, 200, 200)
    region = PlacedRegion(1, "p1-r1", "TABLE", (0, 0, 200, 200), 1,
                          TableInfo(header_columns=["이름", "값"], expected_rows=2,
                                    row_label_column=None), "MODEL")
    rows = [TranscribedRow(None, ["메뉴A", "10"], 0), TranscribedRow(None, ["메뉴B", "2?"], 0)]
    flags = [CellFlag("p1-r1:1:1", 1, 1, "OVERLAP_MISMATCH", 0)]
    return page, TableResult(region, ["이름", "값"], rows, flags, [(0, 0, 200, 200)])


def test_crop_box_inside_region():
    assert recheck.crop_box((100, 100, 300, 200), CropRequest(bbox=[0.5, 0, 1, 1], scale=3)) == (200, 100, 300, 200)


@pytest.mark.asyncio
async def test_resolve_cells_requests_crop_then_answers(tmp_path):
    page, table = _table(tmp_path)
    turns = [RecheckTurn(crops=[CropRequest(bbox=[0.5, 0.5, 1, 1], scale=3)], answers=[]),
             RecheckTurn(crops=[], answers=[CellAnswer(cell_id="p1-r1:1:1", value="25",
                                                        unreadable_reason=None)])]
    calls = []

    async def fake(spec, prompt, images, schema, **k):
        calls.append(len(images))
        return turns[len(calls) - 1]
    caps = Caps(bands_left=10, recheck_calls_left=5)
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "measured_generate", fake):
        await recheck.resolve_cells(table, page, tmp_path, caps=caps, ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert table.rows[1].cells[1] == "25"
    assert calls == [1, 2]                     # 두 번째 턴에 요청한 확대 이미지가 붙는다
    assert caps.recheck_calls_left == 3


@pytest.mark.asyncio
async def test_resolve_cells_cap_marks_unreadable(tmp_path):
    page, table = _table(tmp_path)

    async def never(spec, prompt, images, schema, **k):
        return RecheckTurn(crops=[CropRequest(bbox=[0, 0, 1, 1], scale=2)], answers=[])
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "measured_generate", never):
        await recheck.resolve_cells(table, page, tmp_path, caps=Caps(10, 5), ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert table.unreadable == {(1, 1): "cap"}


@pytest.mark.asyncio
async def test_resolve_cells_model_says_unreadable(tmp_path):
    page, table = _table(tmp_path)

    async def says(spec, prompt, images, schema, **k):
        return RecheckTurn(crops=[], answers=[CellAnswer(cell_id="p1-r1:1:1", value=None,
                                                          unreadable_reason="번짐")])
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "measured_generate", says):
        await recheck.resolve_cells(table, page, tmp_path, caps=Caps(10, 5), ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert table.unreadable == {(1, 1): "번짐"}


@pytest.mark.asyncio
async def test_no_recheck_budget_marks_all_unreadable(tmp_path):
    page, table = _table(tmp_path)
    with patch.object(recheck, "get_settings", return_value=ST):
        await recheck.resolve_cells(table, page, tmp_path, caps=Caps(10, 0), ctx=lambda l: None,
                                    usage_sink=None, raw_sink=None)
    assert table.unreadable == {(1, 1): "cap"}
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_layout_recheck.py -q` → FAIL

- [ ] **Step 3: `api/prompts/layout_recheck.ko.txt`**

```
첨부 이미지는 표 구역과(첫 장), 필요하면 네가 요청한 확대 이미지들이다.
아래 칸들의 값이 띠마다 다르게 읽혔거나 확실하지 않다. 원본을 보고 **보이는 값만** 확정한다.

확인할 칸:
{cells}

응답:
- 확정할 수 있는 칸은 answers 에 cell_id 와 value 를 적는다
- 아무리 봐도 읽을 수 없으면 value=null, unreadable_reason 에 이유를 적는다. 추측하지 않는다
- 더 크게 봐야 하면 crops 에 구역 안 좌표 [왼쪽, 위, 오른쪽, 아래](0~1)와 배율(scale, 1~4)을 요청하고 answers 는 비워도 된다
- 모든 칸에 답하면 crops 는 비운다
```

- [ ] **Step 4: `layout/recheck.py`**

```python
"""④ 재확인. 행 문제는 띠 재전사, 칸 문제는 구조화 출력 턴 루프(확대 요청 또는 답)."""
import logging
from pathlib import Path

from app.config import get_settings
from app.ingest.layout import prompts
from app.ingest.layout.schemas import (BandRow, Box, Caps, CropRequest, PageImage, RecheckTurn,
                                       TableResult)
from app.ingest.layout.transcribe import (check_table, crop_zoom, fill_down, merge_bands,
                                          transcribe_table)
from app.ingest.providers import measured_generate, parse_model_spec

logger = logging.getLogger(__name__)
_CAP = "cap"


def crop_box(region_box: Box, req: CropRequest) -> Box:
    x0, y0, x1, y1 = region_box
    w, h = x1 - x0, y1 - y0
    bx = [min(max(float(v), 0.0), 1.0) for v in (list(req.bbox) + [0, 0, 1, 1])[:4]]
    return (x0 + round(bx[0] * w), y0 + round(bx[1] * h), x0 + round(bx[2] * w), y0 + round(bx[3] * h))


async def recheck_rows(table: TableResult, page: PageImage, workdir: Path, *, caps: Caps, ctx,
                       usage_sink, raw_sink) -> TableResult:
    """행 단위 플래그가 걸린 띠를 재확인 모델로 다시 전사하고, 원래 결과와 다시 합친다."""
    s = get_settings()
    bands = sorted({f.band_index for f in table.flags if f.col is None})
    if not bands or caps.recheck_calls_left <= 0:
        return table
    bands = bands[:caps.recheck_calls_left]
    caps.recheck_calls_left -= len(bands)
    caps.bands_left += len(bands)            # 재전사는 띠 상한이 아니라 재확인 상한으로 센다
    redo = await transcribe_table(table.region, page, workdir, caps=caps, ctx=lambda l: ctx(f"{l}.re"),
                                  usage_sink=usage_sink, raw_sink=raw_sink,
                                  spec_text=s.layout_recheck_model, band_indexes=bands)
    # 다시 읽은 띠는 새 행으로, 나머지 띠는 기존 행으로 띠별 목록을 다시 만들어 합친다
    per_band: list[list[BandRow]] = []
    for bi in range(len(table.band_boxes)):
        source = redo.rows if bi in bands else table.rows
        per_band.append([BandRow(row_label=r.label, cells=list(r.cells), cut_top=False, cut_bottom=False)
                         for r in source if r.band_index == bi])
    merged, flags = merge_bands(per_band, table.header)
    fill_down(merged)
    info = table.region.table
    flags += check_table(merged, table.header, info.expected_rows if info else None,
                         info.row_label_column if info else None)
    for f in flags:
        f.cell_id = f"{table.region.region_id}{f.cell_id}"
    return TableResult(table.region, table.header, merged, flags, table.band_boxes,
                       rerouted=table.rerouted, unreadable=table.unreadable)


async def resolve_cells(table: TableResult, page: PageImage, workdir: Path, *, caps: Caps, ctx,
                        usage_sink, raw_sink) -> None:
    s = get_settings()
    pending = {f.cell_id: f for f in table.flags if f.col is not None}
    if not pending:
        return
    region = table.region
    images = [crop_zoom(page.path, region.box, 1.0, workdir / f"{region.region_id}-rc.png")]
    for turn in range(s.layout_recheck_max_turns):
        if not pending or caps.recheck_calls_left <= 0:
            break
        caps.recheck_calls_left -= 1
        cells = "\n".join(
            f"- {cid}: {f.row_index + 1}번째 행 '{table.header[f.col] if f.col < len(table.header) else f.col}' 칸, "
            f"지금 읽은 값 '{table.rows[f.row_index].cells[f.col] if f.col < len(table.rows[f.row_index].cells) else ''}'"
            for cid, f in pending.items())
        got: RecheckTurn = await measured_generate(
            parse_model_spec(s.layout_recheck_model),
            prompts.render("recheck", cells=cells), list(images), RecheckTurn,
            usage_sink=usage_sink, usage_context=ctx(f"{region.region_id}.rc{turn}"),
            raw_sink=raw_sink, what="재확인",
            mock_build=lambda: RecheckTurn(crops=[], answers=[]))
        for a in got.answers:
            f = pending.pop(a.cell_id, None)
            if f is None:
                continue
            if a.value is not None:
                table.rows[f.row_index].cells[f.col] = a.value
            else:
                table.unreadable[(f.row_index, f.col)] = a.unreadable_reason or "판독 불가"
        for k, req in enumerate(got.crops):
            box = crop_box(region.box, req)
            images.append(crop_zoom(page.path, box, min(max(req.scale, 1.0), 4.0),
                                    workdir / f"{region.region_id}-rc{turn}-{k}.png"))
    for f in pending.values():
        table.unreadable[(f.row_index, f.col)] = _CAP
```

테스트는 `recheck.measured_generate`·`recheck.transcribe_table` 을 patch 하므로 두 이름은 모듈 전역 import 로 둔다.

- [ ] **Step 5: `recheck_rows` 테스트 추가** — 같은 파일에:

```python
@pytest.mark.asyncio
async def test_recheck_rows_retranscribes_flagged_band(tmp_path):
    page, table = _table(tmp_path)
    table.flags = [CellFlag("p1-r1:1:row", 1, None, "COLUMN_COUNT", 0)]
    table.rows[1].cells = ["메뉴B"]
    seen = {}

    async def fake_tt(region, page, workdir, *, caps, ctx, usage_sink, raw_sink, spec_text=None, band_indexes=None):
        seen["spec"], seen["bands"] = spec_text, band_indexes
        return TableResult(region, ["이름", "값"], [TranscribedRow(None, ["메뉴A", "10"], 0),
                                                   TranscribedRow(None, ["메뉴B", "20"], 0)], [], [(0, 0, 200, 200)])
    caps = Caps(10, 5)
    with patch.object(recheck, "get_settings", return_value=ST), \
         patch.object(recheck, "transcribe_table", fake_tt):
        out = await recheck.recheck_rows(table, page, tmp_path, caps=caps, ctx=lambda l: None,
                                         usage_sink=None, raw_sink=None)
    assert seen == {"spec": ST.layout_recheck_model, "bands": [0]}
    assert [r.cells for r in out.rows] == [["메뉴A", "10"], ["메뉴B", "20"]]
    assert caps.recheck_calls_left == 4
```

- [ ] **Step 6: 통과 확인** — Run: `pytest tests/test_layout_recheck.py -q` → PASS

- [ ] **Step 7: 작업 트리에 둔다**

---

### Task 6: 사실 전개와 토큰 반영 검사

**Files:**
- Create: `api/app/ingest/layout/expand.py`, `api/prompts/layout_expand.ko.txt`
- Modify: `api/app/ingest/schemas.py` (`ExtractedAssertion._layout_locator` PrivateAttr)
- Test: `api/tests/test_layout_expand.py`

**Interfaces:**
- Consumes: `TableResult`, `ProseResult`, `LayoutFact`, `ExpandResult`, `measured_generate`, 기존 `app.ingest.extract.extract_facts`
- Produces:
  - `row_text(table: TableResult, i: int) -> str`
  - `row_tokens(table: TableResult, i: int) -> list[tuple[str, str]]` — `("NUM", "275")` / `("NEG", 열이름)`, 판독 불가 칸 제외
  - `missing_tokens(tokens, facts: list[LayoutFact]) -> list[tuple[str, str]]`
  - `async expand_table(table: TableResult, *, ctx, usage_sink, raw_sink) -> tuple[list[ExtractedAssertion], list[str]]`
  - `async expand_text(prose: ProseResult, *, source_id: int, glossary, ctx, usage_sink, raw_sink) -> tuple[list[ExtractedAssertion], list[str]]`
  - `ExtractedAssertion._layout_locator: dict | None` (PrivateAttr) — `{"page": N, "region": "p1-r2", "bbox": [x0,y0,x1,y1], "row": "17"}` (row 는 표만)

- [ ] **Step 1: 실패하는 테스트** — `api/tests/test_layout_expand.py`

```python
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from app.ingest.layout import expand
from app.ingest.layout.schemas import (ExpandResult, LayoutFact, PlacedRegion, TableInfo,
                                       TableResult, TranscribedRow)

ST = NS(layout_expand_model="gemini:gemini-3.6-flash", layout_expand_batch_rows=10,
        layout_fact_confidence=0.9)


def _table():
    region = PlacedRegion(2, "p2-r1", "TABLE", (0, 0, 100, 100), 1,
                          TableInfo(header_columns=["번호", "이름", "가격", "얼음"], expected_rows=2,
                                    row_label_column=0), "MODEL")
    rows = [TranscribedRow("1", ["1", "메뉴A", "1,500", "x"], 0),
            TranscribedRow("2", ["2", "메뉴B", "2000", "가득"], 0)]
    return TableResult(region, ["번호", "이름", "가격", "얼음"], rows, [], [(0, 0, 100, 100)])


def _fact(row, value, attribute="가격", polarity="AFFIRM", original=""):
    return LayoutFact(row_ref=row, original_assertion=original or value, subject="메뉴", variant="",
                      attribute=attribute, value=value, unit="원" if attribute == "가격" else "",
                      polarity=polarity, conditions=[], exceptions=[], order=0)


def test_row_tokens_skip_label_column_and_unreadable():
    t = _table()
    assert expand.row_tokens(t, 0) == [("NUM", "1500"), ("NEG", "얼음")]
    t.unreadable[(1, 2)] = "번짐"
    assert expand.row_tokens(t, 1) == []


def test_missing_tokens():
    tokens = [("NUM", "1500"), ("NEG", "얼음")]
    facts = [_fact("1", "1500")]
    assert expand.missing_tokens(tokens, facts) == [("NEG", "얼음")]
    facts.append(_fact("1", "", attribute="얼음", polarity="NEGATE"))
    assert expand.missing_tokens(tokens, facts) == []


@pytest.mark.asyncio
async def test_expand_table_retries_missing_then_unresolved():
    t = _table()
    replies = [ExpandResult(facts=[_fact("1", "1500"), _fact("2", "2000")]),
               ExpandResult(facts=[])]

    async def fake(spec, prompt, images, schema, **k):
        return replies.pop(0)
    with patch.object(expand, "get_settings", return_value=ST), \
         patch.object(expand, "measured_generate", fake):
        assertions, unresolved = await expand.expand_table(t, ctx=lambda l: None,
                                                           usage_sink=None, raw_sink=None)
    assert len(assertions) == 2
    assert assertions[0]._layout_locator == {"page": 2, "region": "p2-r1", "bbox": [0, 0, 100, 100], "row": "1"}
    assert assertions[0].local_ref == "p2-r1.1.0" and assertions[0].confidence == 0.9
    assert unresolved == ["[전개 미반영] 2쪽 p2-r1 행 1: 얼음(x)"]


@pytest.mark.asyncio
async def test_unreadable_cell_not_expanded():
    t = _table()
    t.unreadable[(1, 2)] = "번짐"
    captured = {}

    async def fake(spec, prompt, images, schema, **k):
        captured["prompt"] = prompt
        return ExpandResult(facts=[_fact("1", "1500"),
                                   _fact("1", "", attribute="얼음", polarity="NEGATE")])
    with patch.object(expand, "get_settings", return_value=ST), \
         patch.object(expand, "measured_generate", fake):
        assertions, unresolved = await expand.expand_table(t, ctx=lambda l: None,
                                                           usage_sink=None, raw_sink=None)
    assert "2000" not in captured["prompt"] and "[판독 불가]" in captured["prompt"]
    assert "[판독 불가] 2쪽 p2-r1 행 2 '가격' 칸: 번짐" in unresolved
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_layout_expand.py -q` → FAIL

- [ ] **Step 3: `schemas.py` (ingest)** — `ExtractedAssertion` 의 `_check_flags` 아래에:

```python
    # 서버가 채운다(LAYOUT 경로). 쪽·구역·좌표·행 — 원장 PAGE 위치로 그대로 남는다. schema 에 실리지 않는다
    _layout_locator: dict | None = PrivateAttr(default=None)
```

- [ ] **Step 4: `api/prompts/layout_expand.ko.txt`**

```
아래는 표에서 **그대로 옮긴 행들**이다. 각 행을 업무 사실로 펼친다. 새 사실을 지어내지 않는다.

머리글: {header}

행:
{rows}

규칙:
- 하나의 사실 = 하나의 값. 한 칸에 값이 여럿이면 나눈다 (예: "우유8부(225ml)" → 값 225, 단위 ml, 조건 "채움 기준 8부")
- row_ref 에 그 사실이 나온 행 라벨을 적는다
- original_assertion 에 칸 원문을 그대로 적는다
- 'x' 칸은 그 열을 쓰지 않는다는 뜻이다 → polarity=NEGATE, attribute 에 열 이름
- 위 행과 같은 값이라도 행마다 따로 적는다
- 제조 순서처럼 단계가 있으면 단계마다 사실 하나, order 에 1부터
- 규격(HOT/ICE/사이즈)은 variant 에, 없으면 ""
- "[판독 불가]" 칸은 사실로 만들지 않는다
- 칸 안의 숫자를 빠뜨리지 않는다. 모든 숫자는 어떤 사실의 value 나 original_assertion 에 들어가야 한다
{missing}
```

- [ ] **Step 5: `layout/expand.py`**

```python
"""⑤ 사실 전개. 몇 행씩 싼 모델에 텍스트로 주고, 빠진 숫자·x 칸은 코드가 짚어 다시 묻는다."""
import logging
import re

from app.config import get_settings
from app.ingest.layout import prompts
from app.ingest.layout.schemas import ExpandResult, LayoutFact, ProseResult, TableResult
from app.ingest.providers import measured_generate, parse_model_spec
from app.ingest.schemas import Evidence, ExtractedAssertion

logger = logging.getLogger(__name__)
_NUM = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d])")
_UNREADABLE = "[판독 불가]"


def _label(table: TableResult, i: int) -> str:
    return table.rows[i].label or f"행{i + 1}"


def _label_col(table: TableResult) -> int | None:
    return table.region.table.row_label_column if table.region.table else None


def row_text(table: TableResult, i: int) -> str:
    cells = []
    for col, cell in enumerate(table.rows[i].cells):
        name = table.header[col] if col < len(table.header) else f"열{col + 1}"
        value = _UNREADABLE if (i, col) in table.unreadable else cell
        cells.append(f"{name}={value}")
    return f"[{_label(table, i)}] " + " ; ".join(cells)


def row_tokens(table: TableResult, i: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for col, cell in enumerate(table.rows[i].cells):
        if col == _label_col(table) or (i, col) in table.unreadable:
            continue
        text = cell.replace(",", "")
        if text.strip().lower() == "x":
            out.append(("NEG", table.header[col] if col < len(table.header) else f"열{col + 1}"))
            continue
        out += [("NUM", n) for n in _NUM.findall(text)]
    return out


def _fact_text(f: LayoutFact) -> str:
    return " ".join([f.value, f.unit, f.original_assertion, *f.conditions, *f.exceptions]).replace(",", "")


def missing_tokens(tokens: list[tuple[str, str]], facts: list[LayoutFact]) -> list[tuple[str, str]]:
    missing = []
    for kind, tok in tokens:
        if kind == "NUM":
            pat = re.compile(rf"(?<![\d.]){re.escape(tok)}(?![\d])")
            ok = any(pat.search(_fact_text(f)) for f in facts)
        else:
            ok = any(f.polarity == "NEGATE" and (tok in f.attribute or tok in f.original_assertion)
                     for f in facts)
        if not ok:
            missing.append((kind, tok))
    return missing


def _to_assertion(f: LayoutFact, table_or_prose, index: int, row: str | None) -> ExtractedAssertion:
    s = get_settings()
    region = table_or_prose.region
    a = ExtractedAssertion(
        local_ref=f"{region.region_id}.{row or 't'}.{index}", original_assertion=f.original_assertion,
        subject=f.subject, attribute=f.attribute, value=f.value, variant=f.variant, unit=f.unit,
        polarity=f.polarity, conditions=list(f.conditions), exceptions=list(f.exceptions),
        order=f.order, evidence=Evidence(), confidence=s.layout_fact_confidence)
    loc = {"page": region.page, "region": region.region_id, "bbox": list(region.box)}
    if row is not None:
        loc["row"] = row
    a._layout_locator = loc
    return a


async def _call(table, rows_text, missing, label, ctx, usage_sink, raw_sink) -> ExpandResult:
    s = get_settings()
    return await measured_generate(
        parse_model_spec(s.layout_expand_model),
        prompts.render("expand", header=" | ".join(table.header), rows=rows_text, missing=missing),
        [], ExpandResult, usage_sink=usage_sink, usage_context=ctx(label), raw_sink=raw_sink,
        what="사실 전개", mock_build=lambda: ExpandResult(facts=[]))


async def expand_table(table: TableResult, *, ctx, usage_sink, raw_sink) -> tuple[list[ExtractedAssertion], list[str]]:
    s = get_settings()
    region = table.region
    assertions: list[ExtractedAssertion] = []
    unresolved = [f"[판독 불가] {region.page}쪽 {region.region_id} 행 {_label(table, r)} "
                  f"'{table.header[c] if c < len(table.header) else c}' 칸: {why}"
                  for (r, c), why in sorted(table.unreadable.items())]
    n = s.layout_expand_batch_rows
    for start in range(0, len(table.rows), n):
        idx = list(range(start, min(start + n, len(table.rows))))
        text = "\n".join(row_text(table, i) for i in idx)
        got = await _call(table, text, "", f"{region.region_id}.x{start // n}", ctx, usage_sink, raw_sink)
        facts = list(got.facts)
        gaps = {i: missing_tokens(row_tokens(table, i), [f for f in facts if f.row_ref == _label(table, i)])
                for i in idx}
        if any(gaps.values()):
            hint = "\n이전 응답에서 빠진 값: " + " ; ".join(
                f"[{_label(table, i)}] " + ", ".join(t for _, t in g) for i, g in gaps.items() if g)
            retry = await _call(table, text, hint, f"{region.region_id}.x{start // n}r",
                                ctx, usage_sink, raw_sink)
            facts += retry.facts
        for i in idx:
            label = _label(table, i)
            mine = [f for f in facts if f.row_ref == label]
            for k, f in enumerate(mine):
                assertions.append(_to_assertion(f, table, k, label))
            for kind, tok in missing_tokens(row_tokens(table, i), mine):
                shown = f"{tok}(x)" if kind == "NEG" else tok
                unresolved.append(f"[전개 미반영] {region.page}쪽 {region.region_id} 행 {label}: {shown}")
    return assertions, unresolved


async def expand_text(prose: ProseResult, *, source_id: int, glossary, ctx, usage_sink,
                      raw_sink) -> tuple[list[ExtractedAssertion], list[str]]:
    """문단·각주·사진 글은 기존 사실 추출(텍스트 입력)로 넘긴다."""
    from app.ingest.extract import extract_facts

    if not prose.lines:
        return [], []
    result = await extract_facts(source_id=source_id, source_type="SCAN", text="\n".join(prose.lines),
                                 glossary=glossary, media=[], usage_sink=usage_sink,
                                 usage_context=ctx(f"{prose.region.region_id}.x"), raw_sink=raw_sink)
    region = prose.region
    for a in result.assertions:
        a.local_ref = f"{region.region_id}.t.{a.local_ref}"
        a.requires = [f"{region.region_id}.t.{r}" for r in a.requires]
        a._layout_locator = {"page": region.page, "region": region.region_id, "bbox": list(region.box)}
    return list(result.assertions), list(result.unresolved)
```

- [ ] **Step 6: 통과 확인** — Run: `pytest tests/test_layout_expand.py -q` → PASS

- [ ] **Step 7: 작업 트리에 둔다**

---

### Task 7: 오케스트레이터와 파이프라인 연결

**Files:**
- Modify: `api/app/ingest/layout/__init__.py` (`run_layout_extraction`, `STATS`)
- Modify: `api/app/ingest/pipeline.py` (`_preprocess_scan` LAYOUT 분기, `process_source` 분기·재시도 조건, `_persist_ledger` 위치·버전)
- Test: `api/tests/test_layout_pipeline.py`

**Interfaces:**
- Consumes: Task 2~6 전부, `pipeline.ExtractionOutcome`, `pipeline._ctx_for`, `occurrences.validate_assertions`, `budget.BudgetExceeded`
- Produces:
  - `async run_layout_extraction(*, source_id: int, path: Path | None, workdir: Path, glossary, usage_sink, usage_base, raw_sink, checkpoint, only_segments: set[str] | None) -> ExtractionOutcome`
  - `layout.STATS: dict[int, dict]` — source_id → `{"pages", "regions", "coverage_regions", "fallback_regions", "rows", "expected_rows", "rechecked_cells", "unreadable_cells", "unexpanded_tokens", "failed_regions", "rerouted"}` (평가 하네스가 읽는다, 프로세스 안에서만)

- [ ] **Step 1: 실패하는 테스트** — `api/tests/test_layout_pipeline.py`

```python
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from PIL import Image

from app.ingest import layout
from app.ingest.layout import schemas as ls
from app.ingest.providers import budget


def _settings(**over):
    base = dict(ingest_mode="mock", layout_region_model="anthropic:claude-sonnet-5-5",
                layout_transcribe_model="gemini:gemini-3.6-flash",
                layout_recheck_model="anthropic:claude-sonnet-5-5",
                layout_expand_model="gemini:gemini-3.6-flash", layout_render_dpi=72,
                ingest_scan_max_pages=None, layout_max_bands_per_source=80,
                layout_recheck_max_calls_per_source=30, layout_concurrency=2,
                extract_locator_hints=False, extract_clear_ungrounded_values=False)
    base.update(over)
    return NS(**base)


async def _run(tmp_path, regions_by_page, **kw):
    img = tmp_path / "a.png"
    Image.new("RGB", (400, 300), "white").save(img)
    saved = []

    async def checkpoint(assertions, seg):
        saved.append((seg, len(assertions)))
    with patch.object(layout, "get_settings", return_value=_settings()), \
         patch.object(layout, "map_page", regions_by_page), \
         patch.object(layout, "_process_region", kw.get("process")):
        out = await layout.run_layout_extraction(
            source_id=9, path=img, workdir=tmp_path / "w", glossary=[], usage_sink=None,
            usage_base=None, raw_sink=None, checkpoint=checkpoint, only_segments=kw.get("only"))
    return out, saved


def _regions(n):
    async def fake(page, workdir, **k):
        return [ls.PlacedRegion(page.number, f"p{page.number}-r{i + 1}", "PROSE", (0, 0, 10, 10),
                                i + 1, None, "MODEL") for i in range(n)], []
    return fake


@pytest.mark.asyncio
async def test_each_region_is_a_segment(tmp_path):
    async def process(region, page, workdir, ctx, caps, glossary, source_id, usage_sink, raw_sink, stats):
        from app.ingest.schemas import ExtractedAssertion, Evidence
        return [ExtractedAssertion(local_ref="f1", original_assertion="o", subject="s", attribute="a",
                                   value="1", evidence=Evidence(), confidence=0.9)], [], "o"
    out, saved = await _run(tmp_path, _regions(2), process=process)
    assert out.segments_total == 2 and out.segments_failed == 0
    assert saved == [("p1-r1", 1), ("p1-r2", 1)]
    assert {a.segment_id for a in out.assertions} == {"p1-r1", "p1-r2"}
    assert layout.STATS[9]["regions"] == 2


@pytest.mark.asyncio
async def test_budget_exceeded_marks_region_failed(tmp_path):
    calls = []

    async def process(region, page, workdir, ctx, caps, glossary, source_id, usage_sink, raw_sink, stats):
        calls.append(region.region_id)
        if region.region_id == "p1-r2":
            raise budget.BudgetExceeded("합성 상한")
        return [], [], ""
    out, _ = await _run(tmp_path, _regions(3), process=process)
    assert out.failed_segment_ids == ["p1-r2", "p1-r3"]       # 상한 뒤 구역은 부르지 않는다
    assert calls == ["p1-r1", "p1-r2"]
    assert out.segments_failed == 2


@pytest.mark.asyncio
async def test_only_segments(tmp_path):
    seen = []

    async def process(region, *a, **k):
        seen.append(region.region_id)
        return [], [], ""
    out, _ = await _run(tmp_path, _regions(3), process=process, only={"p1-r2"})
    assert seen == ["p1-r2"] and out.segments_total == 3


@pytest.mark.asyncio
async def test_mock_mode_end_to_end(tmp_path, monkeypatch):
    """합성 경로 전체: 구역 지도(쪽 전체 PROSE) → 글 전사 → expand_text(mock 사실 추출).

    api/.env 가 INGEST_MODE=real 이어도 실제 모델을 부르지 않게 환경변수로 mock 을 강제한다
    (pydantic-settings 는 환경변수가 .env 보다 우선). 설정 캐시를 앞뒤로 비운다.
    """
    from app.config import get_settings
    monkeypatch.setenv("INGEST_MODE", "mock")
    monkeypatch.setenv("SCAN_EXTRACT_MODE", "LAYOUT")
    get_settings.cache_clear()
    monkeypatch.setattr(budget, "_LIMIT", None)
    img = tmp_path / "a.png"
    Image.new("RGB", (400, 300), "white").save(img)
    saved = []

    async def checkpoint(assertions, seg):
        saved.append(seg)
    out = await layout.run_layout_extraction(
        source_id=10, path=img, workdir=tmp_path / "w", glossary=[], usage_sink=None,
        usage_base=None, raw_sink=None, checkpoint=checkpoint, only_segments=None)
    assert out.segments_total >= 1 and out.segments_failed == 0
    assert saved and saved[0] == "p1-r1"
    get_settings.cache_clear()
```

마지막 테스트는 mock 사실 추출이 빈 목록을 돌려줘도 통과한다(구간 수·실패 0 만 본다). 환경변수로 mock 을 강제했으므로 공급자를 부르지 않는다.

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_layout_pipeline.py -q` → FAIL

- [ ] **Step 3: `layout/__init__.py`**

```python
"""SCAN 구역 기반 다단계 추출 (설계 W_SCAN_LAYOUT_EXTRACTION_DESIGN).

구역 하나 = 구간(segment) 하나. 구역을 끝내는 즉시 checkpoint 로 원장에 적는다.
금액 상한에 닿으면 남은 구역은 부르지 않고 실패로 남긴다(작업은 PARTIAL).
"""
import logging
from pathlib import Path

from app.config import get_settings
from app.ingest.layout import expand, recheck, transcribe
from app.ingest.layout.pages import blank_page, page_images
from app.ingest.layout.regions import map_page
from app.ingest.layout.schemas import Caps
from app.ingest.providers import budget

logger = logging.getLogger(__name__)

# 평가 하네스가 읽는 단계별 손실 기록. 프로세스 안에서만 산다(제품 응답에 싣지 않는다)
STATS: dict[int, dict] = {}


def _new_stats() -> dict:
    return dict(pages=0, regions=0, coverage_regions=0, fallback_regions=0, rows=0, expected_rows=0,
                rechecked_cells=0, unreadable_cells=0, unexpanded_tokens=0, failed_regions=0, rerouted=0)


async def _process_region(region, page, workdir, ctx, caps, glossary, source_id, usage_sink,
                          raw_sink, stats):
    """구역 하나 → (사실, 미해결, 서버 검사용 글)."""
    if region.kind == "TABLE":
        table = await transcribe.transcribe_table(region, page, workdir, caps=caps, ctx=ctx,
                                                  usage_sink=usage_sink, raw_sink=raw_sink)
        if not table.rerouted:
            table = await recheck.recheck_rows(table, page, workdir, caps=caps, ctx=ctx,
                                               usage_sink=usage_sink, raw_sink=raw_sink)
            before = sum(1 for f in table.flags if f.col is not None)
            await recheck.resolve_cells(table, page, workdir, caps=caps, ctx=ctx,
                                        usage_sink=usage_sink, raw_sink=raw_sink)
            stats["rechecked_cells"] += before
            stats["unreadable_cells"] += len(table.unreadable)
            stats["rows"] += len(table.rows)
            stats["expected_rows"] += (region.table.expected_rows or 0) if region.table else 0
            facts, unresolved = await expand.expand_table(table, ctx=ctx, usage_sink=usage_sink,
                                                          raw_sink=raw_sink)
            stats["unexpanded_tokens"] += sum(1 for u in unresolved if u.startswith("[전개 미반영]"))
            text = "\n".join(expand.row_text(table, i) for i in range(len(table.rows)))
            return facts, unresolved, text
        stats["rerouted"] += 1
    kind_prompt = "photo" if region.kind == "PHOTO" else "prose"
    prose = await transcribe.transcribe_text(region, page, workdir, kind_prompt=kind_prompt, caps=caps,
                                             ctx=ctx, usage_sink=usage_sink, raw_sink=raw_sink)
    facts, unresolved = await expand.expand_text(prose, source_id=source_id, glossary=glossary, ctx=ctx,
                                                 usage_sink=usage_sink, raw_sink=raw_sink)
    return facts, unresolved, "\n".join(prose.lines)


async def run_layout_extraction(*, source_id: int, path: Path | None, workdir: Path, glossary,
                                usage_sink, usage_base, raw_sink, checkpoint,
                                only_segments: set[str] | None):
    from app.ingest import occurrences
    from app.ingest.pipeline import ExtractionOutcome, _ctx_for

    s = get_settings()
    stats = STATS[source_id] = _new_stats()
    workdir.mkdir(parents=True, exist_ok=True)
    pages = ([blank_page(workdir)] if path is None else
             page_images(path, workdir, render_dpi=s.layout_render_dpi, max_pages=s.ingest_scan_max_pages))
    stats["pages"] = len(pages)
    caps = Caps(bands_left=s.layout_max_bands_per_source,
                recheck_calls_left=s.layout_recheck_max_calls_per_source)

    def ctx(label: str):
        return _ctx_for(usage_base, source_id, "EXTRACT", segment_id=label)

    merged, unresolved, failed, total = [], [], [], 0
    stop = False
    for page in pages:
        placed, notes = await map_page(page, workdir, ctx=ctx, usage_sink=usage_sink, raw_sink=raw_sink)
        unresolved += notes
        for region in placed:
            total += 1
            stats["regions"] += 1
            stats["coverage_regions"] += region.added_by == "COVERAGE"
            stats["fallback_regions"] += region.added_by == "FALLBACK"
            rid = region.region_id
            if only_segments is not None and rid not in only_segments:
                continue
            if stop:
                failed.append(rid)
                continue
            try:
                facts, notes, text = await _process_region(region, page, workdir, ctx, caps, glossary,
                                                           source_id, usage_sink, raw_sink, stats)
                for a in facts:
                    a.segment_id = rid
                notes += occurrences.validate_assertions(
                    facts, source_type="SCAN", text=text, media=[],
                    locator_hints=False,
                    clear_ungrounded=bool(getattr(s, "extract_clear_ungrounded_values", False)))
                if checkpoint is not None:
                    await checkpoint(facts, rid)
                merged += facts
                unresolved += notes
            except budget.BudgetExceeded as exc:
                logger.warning("금액 상한 — %s 부터 남은 구역을 부르지 않는다: %s", rid, exc)
                failed.append(rid)
                stop = True
            except Exception as exc:
                logger.warning("구역 실패 source=%s %s: %s", source_id, rid, exc)
                failed.append(rid)
    stats["failed_regions"] = len(failed)
    if total and len(failed) == total and only_segments is None:
        raise RuntimeError(f"모든 구역({total}개) 추출이 실패했다")
    return ExtractionOutcome(merged, unresolved, total, len(failed), failed, None)
```

(`map_page` 실패는 Task 3 에서 이미 FALLBACK 으로 흡수한다. `map_page` 안에서 `BudgetExceeded` 가 나면 FALLBACK 구역이 되고 이어지는 구역 처리에서 다시 `BudgetExceeded` 로 멈춘다.)

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_layout_pipeline.py -q` → PASS

- [ ] **Step 5: `pipeline.py` 연결**

(a) `_preprocess_scan` 맨 앞(`row` 확인 뒤, 다운로드 뒤):

```python
    from app.config import get_settings as _gs
    if _gs().scan_extract_mode == "LAYOUT":
        # 구역 경로는 원본 파일만 받는다. 텍스트 레이어·HYBRID 판단은 하지 않는다
        pages = document.pdf_page_count(path) if path.suffix.lower() == ".pdf" else 1
        async with pool.acquire() as conn:
            await repo.update_scan_result(conn, source_id, page_count=pages,
                                          ocr_text=None, ocr_engine="layout")
        return "", [path], []
```

(b) `_preprocess` 의 mock 건너뛰기: SCAN·LAYOUT 은 mock 이어도 `MOCK_PLACEHOLDER, [], []` 를 그대로 돌려준다(원본 없음 → 오케스트레이터가 `blank_page` 사용). 변경 없음.

(c) `process_source` 의 `outcome = await _extract_facts_all(...)` 를 감싼다:

```python
            layout_mode = (src["source_type"] == "SCAN"
                           and get_settings().scan_extract_mode == "LAYOUT")
            if layout_mode:
                from app.ingest.layout import run_layout_extraction
                outcome = await run_layout_extraction(
                    source_id=source_id, path=media[0] if media else None,
                    workdir=storage.workdir(source_id) / "layout", glossary=glossary,
                    usage_sink=usage_sink, usage_base=usage_base, raw_sink=raw_sink,
                    checkpoint=_checkpoint,
                    only_segments=set(retry_segments) if retry_segments is not None else None)
            else:
                outcome = await _extract_facts_all(...)   # 기존 호출 그대로
```

(d) 재시도 구성 검사(`_same_layout` 를 쓰는 조건)에서 LAYOUT 모드는 별도 판정:

```python
        layout_retry_ok = (src["source_type"] == "SCAN"
                           and get_settings().scan_extract_mode == "LAYOUT"
                           and bool(getattr(get_settings(), "extract_reuse_enabled", False)))
        if ((previous and previous['layout_hash'] != fingerprint)
                or (retry_segments is not None and not layout_retry_ok and (
                    not previous or not _same_layout(segments, retry_segments, expected_segments_total)))):
```
(기존 조건식의 두 번째 줄에 `not layout_retry_ok and` 만 끼운다.)

(e) `_persist_ledger` 의 위치·버전:

```python
        layout_loc = getattr(a, "_layout_locator", None)
        if layout_loc:
            locator_type, locator = "PAGE", dict(layout_loc)
        else:
            locator_type, locator = occurrences.locator_for(...)   # 기존 그대로
```
그리고 `extract_version` 을 사실마다: LAYOUT 사실이면 `f"layout:{s.layout_transcribe_model}+{s.layout_expand_model}/{s.ingest_mode}"`, 아니면 기존 값. `source_fact_occurrences` 에 위치를 쓰는 곳이 같은 `locator_type, locator` 변수를 쓰는지 확인하고, 다른 곳에서 다시 계산하면 같은 분기를 넣는다.

- [ ] **Step 6: 파이프라인 회귀 테스트 추가** — `tests/test_layout_pipeline.py` 에:

```python
def test_layout_locator_persisted_as_page():
    from app.ingest.schemas import ExtractedAssertion, Evidence
    a = ExtractedAssertion(local_ref="f1", original_assertion="o", subject="s", attribute="a",
                           value="1", evidence=Evidence(), confidence=0.9)
    a._layout_locator = {"page": 2, "region": "p2-r1", "bbox": [0, 0, 1, 1], "row": "3"}
    from app.ingest import pipeline
    assert pipeline._locator_of("SCAN", a, hints=False) == ("PAGE", {"page": 2, "region": "p2-r1",
                                                                      "bbox": [0, 0, 1, 1], "row": "3"})
```
이를 위해 (e) 의 분기를 `pipeline._locator_of(source_type, a, *, hints) -> tuple[str, dict]` 작은 함수로 뽑아 `_persist_ledger` 가 부르게 한다.

- [ ] **Step 7: 전체 확인**

Run: `cd api && pytest -q`
Expected: 전부 PASS (SINGLE 경로 테스트 포함).
Run: `python3 ../.claude/skills/store-isolation-check/check_store_id.py app/ingest` (저장소 루트 기준 경로로) — 새 경고 없음.

- [ ] **Step 8: 작업 트리에 둔다**

---

### Task 8: 평가 하네스 — 금액 상한과 단계별 손실

**Files:**
- Modify: `api/scripts/run_extract_eval.py`
- Test: `api/tests/test_extraction_eval.py` (기존 파일에 추가)

**Interfaces:**
- Consumes: `budget.set_limit/spent/unpriced`, `layout.STATS`, `parse_model_spec`, `load_rate_card`
- Produces: CLI `--max-usd <float>`, `--env-override KEY=VALUE`(여러 번); 리포트 JSON `settings.layout`(모드·역할별 모델), `layout_stats`(source_key → STATS), `spend`({"usd_known": str, "unpriced_models": [...]})
- 왜 `--env-override` 인가: 하네스는 `load_dotenv(override=True)` 라 셸 환경변수로 설정을 바꿀 수 없다. 공용 `api/.env` 를 실험마다 고치지 않도록 실행 한 번에만 적용한다.

- [ ] **Step 1: 실패하는 테스트** — `tests/test_extraction_eval.py` 끝에:

```python
def test_max_usd_requires_anthropic_rates(monkeypatch):
    import importlib, sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    ree = importlib.import_module("run_extract_eval")
    card = SimpleNamespace(model_rate=lambda m: {"input_per_1m": None, "output_per_1m": None})
    monkeypatch.setattr(ree, "load_rate_card", lambda: card)
    st = SimpleNamespace(scan_extract_mode="LAYOUT", layout_region_model="anthropic:claude-sonnet-5-5",
                         layout_transcribe_model="gemini:gemini-3.6-flash",
                         layout_recheck_model="anthropic:claude-sonnet-5-5",
                         layout_expand_model="gemini:gemini-3.6-flash")
    with pytest.raises(SystemExit, match="요율"):
        ree._check_budget_rates(st)


def test_env_override_applies_after_dotenv(monkeypatch):
    import importlib, sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    ree = importlib.import_module("run_extract_eval")
    from app.config import get_settings
    monkeypatch.delenv("SCAN_EXTRACT_MODE", raising=False)
    monkeypatch.setenv("INGEST_MODE", "mock")
    ree._apply_env_overrides(["SCAN_EXTRACT_MODE=LAYOUT"])
    try:
        assert get_settings().scan_extract_mode == "LAYOUT"
    finally:
        monkeypatch.delenv("SCAN_EXTRACT_MODE", raising=False)
        get_settings.cache_clear()
    with pytest.raises(SystemExit, match="KEY=VALUE"):
        ree._apply_env_overrides(["broken"])
```
(파일 상단에 `Path`, `SimpleNamespace`, `pytest` import 가 없으면 추가한다.)

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_extraction_eval.py -q -k max_usd` → FAIL

- [ ] **Step 3: 구현** — `run_extract_eval.py` 에:

```python
from decimal import Decimal  # noqa: E402
from app.ingest.providers import budget, parse_model_spec  # noqa: E402
from app.usage.rates import load_rate_card  # noqa: E402


def _layout_specs(s) -> list[str]:
    return [s.layout_region_model, s.layout_transcribe_model, s.layout_recheck_model, s.layout_expand_model]


def _check_budget_rates(s) -> None:
    """금액 상한을 걸려면 Anthropic 모델 요율이 있어야 한다. Gemini 요율이 없으면 비용 UNKNOWN 으로 둔다."""
    if getattr(s, "scan_extract_mode", "SINGLE") != "LAYOUT":
        return
    card = load_rate_card()
    missing = [x for x in _layout_specs(s) if x.startswith("anthropic:")
               and card.model_rate(parse_model_spec(x).model)["input_per_1m"] is None]
    if missing:
        raise SystemExit(f"--max-usd: Anthropic 모델 요율이 없다 {missing} — api/config/rate_card.json")
```

```python
def _apply_env_overrides(pairs: list[str]) -> None:
    """이번 실행에만 설정을 덮는다. .env 를 읽은 뒤에 적용하고 설정 캐시를 비운다."""
    import os
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise SystemExit(f"--env-override 는 KEY=VALUE 형식이다: {pair!r}")
        os.environ[key.strip()] = value
    get_settings.cache_clear()
```

`main()` 의 인자에 `ap.add_argument("--max-usd", type=float, default=None, help="이번 실행의 Anthropic 사용액 상한(USD). 닿으면 남은 구역은 실패로 남긴다")` 와 `ap.add_argument("--env-override", action="append", default=[], help="이번 실행에만 적용할 설정 KEY=VALUE")` 를 추가하고, 파싱 직후(다른 설정 읽기보다 먼저):

```python
    _apply_env_overrides(args.env_override)
    if args.max_usd is not None:
        _check_budget_rates(get_settings())
        budget.set_limit(Decimal(str(args.max_usd)))
    else:
        budget.set_limit(None)
```

리포트 JSON 을 쓰는 곳(`write_report` 호출부의 snapshot/metrics)에 추가:

```python
    from app.ingest import layout as _layout
    s = get_settings()
    snapshot["layout"] = {"mode": s.scan_extract_mode, "models": _layout_specs(s)}
    snapshot["layout_stats"] = {source_keys.get(sid, str(sid)): st for sid, st in _layout.STATS.items()}
    snapshot["spend"] = {"usd_known": str(budget.spent()), "unpriced_models": sorted(budget.unpriced())}
```
(`source_keys` 는 기존 source_id→source_key 매핑 변수 이름에 맞춘다.) md 리포트에도 `spend`·`layout_stats` 를 표로 한 단락 추가한다.

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_extraction_eval.py -q` → PASS

- [ ] **Step 5: 작업 트리에 둔다**

---

### Task 9: 실제 측정과 기록 (컨트롤러 수행)

코드 변경이 아니다. 실제 모델을 부르므로 Anthropic 사용액을 매 실행 확인한다(총 ≤ 7 USD).

- [ ] **Step 1: 사용자 1회 확인** — `rate_card.json` 의 Anthropic 단가(위 Task 1 Step 11)를 사용자에게 보여주고 확인받는다. Gemini 단가가 있으면 함께 채운다(없으면 UNKNOWN 으로 진행).

- [ ] **Step 2: 실험 2 — LAYOUT 기본 구성**

공용 `api/.env` 는 고치지 않는다. Task 8 의 `--env-override` 로 실행 한 번에만 바꾼다.

```
cd api && python scripts/reset_eval_store.py --store store-a
python scripts/run_extract_eval.py --store store-a --only-source a-scan-recipebook --label layout-default \
  --max-usd 2 --env-override SCAN_EXTRACT_MODE=LAYOUT
python scripts/compare_reference.py --store store-a --source-key a-scan-recipebook --label layout-default
```

- [ ] **Step 3: 실험 3 — 전사 모델 Haiku** (`--env-override LAYOUT_TRANSCRIBE_MODEL=anthropic:claude-haiku-4-5`)
- [ ] **Step 4: 실험 4 — 판단 모델 Opus** (예산이 남을 때만: `LAYOUT_REGION_MODEL`·`LAYOUT_RECHECK_MODEL=anthropic:claude-opus-5-5`)
- [ ] **Step 5: 최선 구성 3회** — 변동(재현율 최소·최대·중앙값) 보고
- [ ] **Step 6: 기록** — `docs/dev/review/W_SCAN_LAYOUT_EXTRACTION_RESULT_<날짜>.md`: 조건·지표·단계별 손실·사용액·참조 편향 주석(Claude 구성과 Gemini 구성 분리)·완료 기준 대조. 품질 목표 미달이면 원인 단계와 다음 조치를 적고 멈춰 사용자와 상의한다.
```
