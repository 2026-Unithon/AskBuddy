"""한 번 호출 추출 — 분류+사실+줄 처리 보고를 Sonnet 한 호출로 받고, 끊긴 줄만 이어서 다시 뽑는다.

설계: docs/dev/plan/W_SINGLE_CALL_EXTRACT_DESIGN_20261107.md (S7·S8·S9·S11).
- 끊김은 정답 개수가 아니라 **입력 줄 번호가 모두 처리됐는가**로 판정한다(§4-3).
- 끊김·호출 실패·잘림·빈 결과면 최대 `extract_max_attempts` 번 시도한다. 2번째부터는 처리 안 된 줄만 보낸다(§4-4).
- 남은 줄은 처리 안 된 범위로 돌려준다. 뽑힌 사실은 그대로 쓴다(S9).
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.ingest import raw_responses
from app.ingest.schemas import SingleCallExtractionResult

logger = logging.getLogger(__name__)

_LINE = re.compile(r"^\[#(\d+)\]", re.M)
_PAGE_ONLY = re.compile(r"^\[\d+쪽\]$")
_OVERLAP = "[겹침] "
PROMPTS = Path(__file__).resolve().parents[3] / "prompts"
COVERAGE_SUFFIX = PROMPTS / "extract_facts_single_suffix.ko.txt"
CONTINUATION_SUFFIX = PROMPTS / "extract_facts_continuation.ko.txt"

# 처리 안 된 범위의 사유
TRUNCATED = "TRUNCATED"      # 처리 도중 끊김(빠진 줄·max_tokens)
CALL_FAILED = "CALL_FAILED"  # 호출 실패·응답 형식 오류·거절
EMPTY = "EMPTY"              # 줄 없는 자료(사진 등)에서 사실도 판정도 없음


# ── 순수 로직 ──────────────────────────────────────────────────────────

def number_lines(text: str) -> tuple[str, list[int]]:
    """글 줄마다 `[#N]` 을 붙인다. 이미 번호가 있으면(카톡 메시지 번호) 그대로 쓴다.

    빈 줄·쪽 표지(`[N쪽]`)는 번호를 붙이지 않는다. 안내문 한 줄(사진·글자층 없는 PDF)은 자료 글이 아니다.
    """
    from app.ingest.occurrences import has_text_evidence

    existing = [int(n) for n in _LINE.findall(text or "")]
    if existing:
        return text, existing
    if not has_text_evidence(text):
        return text, []
    out, ids, n = [], [], 0
    for line in (text or "").split("\n"):
        if not line.strip() or _PAGE_ONLY.match(line.strip()):
            out.append(line)
            continue
        n += 1
        ids.append(n)
        out.append(f"[#{n}] {line}")
    return "\n".join(out), ids


@dataclass(frozen=True)
class Judgement:
    unprocessed: list[int]
    empty: bool


def _is_none(result) -> bool:
    ranking = getattr(result, "intake_ranking", None) or []
    return bool(ranking) and max(ranking, key=lambda r: r.score).logic == "NONE"


def judge(line_ids: list[int], result) -> Judgement:
    """입력 줄 번호와 보고를 맞춰 처리 안 된 줄을 찾는다(설계 §4-3 규칙 1~3)."""
    refs = {a.local_ref for a in result.assertions}
    done = {c.line for c in result.coverage
            if (c.refs and all(r in refs for r in c.refs)) or (not c.refs and c.no_content.strip())}
    unprocessed = [n for n in line_ids if n not in done]
    # 줄 없는 자료(사진 등): 사실도 없고 업무와 무관 판정도 아니면 빈 결과다
    empty = not line_ids and not result.assertions and not _is_none(result)
    return Judgement(unprocessed, empty)


def to_ranges(ids: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for n in sorted(ids):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def continuation_text(numbered: str, unprocessed: list[int], *, overlap: int = 2) -> str:
    """처리 안 된 줄만 남긴다. 각 범위 앞 `overlap` 줄은 문맥으로 `[겹침]` 을 붙여 둔다. 쪽 표지는 남긴다."""
    todo = set(unprocessed)
    context = {n - k for n in todo for k in range(1, overlap + 1)} - todo
    out = []
    for line in numbered.split("\n"):
        m = _LINE.match(line)
        if m is None:
            if _PAGE_ONLY.match(line.strip()):
                out.append(line)
            continue
        n = int(m.group(1))
        if n in todo:
            out.append(line)
        elif n in context:
            out.append(_OVERLAP + line)
    return "\n".join(out)


def _key(a) -> tuple:
    norm = lambda s: re.sub(r"\s+", "", (s or "").lower())  # noqa: E731
    return norm(a.subject), norm(a.variant), norm(a.attribute), norm(a.value)


def merge(base, more, *, attempt: int):
    """이어서 뽑은 결과를 앞 결과에 더한다. 이름표는 `a{시도}` 를 앞에 붙여 겹치지 않게 한다.

    앞에서 이미 뽑은 사실(같은 대상·규격·속성·값)은 다시 넣지 않고, 그 줄 보고는 앞 사실을 가리키게 한다.
    자료 판정(순위·이유)은 앞 결과의 것을 유지한다.
    """
    seen = {_key(a): a.local_ref for a in base.assertions}
    rename: dict[str, str] = {}
    added = []
    for a in more.assertions:
        k = _key(a)
        if k in seen:
            rename[a.local_ref] = seen[k]
            continue
        new_ref = f"a{attempt}{a.local_ref}"
        rename[a.local_ref] = new_ref
        seen[k] = new_ref
        added.append(a)
    renamed = [a.model_copy(update={"local_ref": rename[a.local_ref],
                                    "requires": [rename.get(r, r) for r in a.requires]})
               for a in added]
    reported = {c.line for c in base.coverage}
    coverage = list(base.coverage) + [
        c.model_copy(update={"refs": [rename.get(r, r) for r in c.refs]})
        for c in more.coverage if c.line not in reported]
    unresolved = list(base.unresolved) + [u for u in more.unresolved if u not in base.unresolved]
    return base.model_copy(update={"assertions": list(base.assertions) + renamed,
                                   "coverage": coverage, "unresolved": unresolved})


# ── 호출 ──────────────────────────────────────────────────────────────

OWNER_FORCED_NOTE = ("\n점주가 이 자료를 업무 자료로 지정했다. 용도 판정이 NONE 이어도 `assertions` 를 비우지 말고 "
                     "업무 사실을 뽑는다.")


def render_prompt(*, source_type: str, text: str, glossary, hints, continuing: bool,
                  owner_forced: bool = False) -> str:
    """한 호출 지시문 = 위치 표지 사실 추출 + 용도 판정 꼬리 + 줄 처리 보고(+ 이어서 뽑기)."""
    from app.ingest.extract.gemini import render_facts_intake_prompt

    prompt = render_facts_intake_prompt(source_type=source_type, text=text, glossary=glossary,
                                        hints=tuple(hints), locator_hints=True).rstrip("\n")
    prompt += "\n" + COVERAGE_SUFFIX.read_text(encoding="utf-8").rstrip("\n")
    if continuing:
        prompt += "\n" + CONTINUATION_SUFFIX.read_text(encoding="utf-8").rstrip("\n")
    if owner_forced:
        prompt += OWNER_FORCED_NOTE
    return prompt + "\n"


def _attempt_context(ctx, attempt: int):
    """시도마다 논리 호출 ID 를 가른다 — 원장 unique(store, logical_call_id, attempt_no)."""
    if ctx is None:
        return None
    return ctx.model_copy(update={"logical_call_id": f"{ctx.logical_call_id}:a{attempt}"})


def _wrap_mock(base, line_ids: list[int], hints) -> SingleCallExtractionResult:
    """mock 추출 결과에 칩 첫째(없으면 RECIPE) 판정과 '모든 줄 처리' 보고를 붙인다."""
    data = base.model_dump()
    refs = [a["local_ref"] for a in data["assertions"]]
    coverage = [{"line": n, "refs": refs if i == 0 and refs else [],
                 "no_content": "" if i == 0 and refs else "mock"} for i, n in enumerate(line_ids)]
    out = SingleCallExtractionResult.model_validate({
        "assertions": data["assertions"], "unresolved": data.get("unresolved", []),
        "coverage": coverage,
        "intake_ranking": [{"logic": hints[0] if hints else "RECIPE", "score": 0.9}],
        "intake_reason": "mock"})
    out._raw_response_id = getattr(base, "raw_response_id", None)
    return out


async def _call_once(prompt: str, media: list[Path], ctx, *, line_ids: list[int] = (),
                     hints=(), usage_sink=None, raw_sink=None, mock_args: dict | None = None
                     ) -> SingleCallExtractionResult:
    """한 번 부르고 스키마로 읽는다. 잘림은 TruncatedOutputError, 그 밖의 실패는 예외 그대로.

    mock 모드는 기존 `extract.extract_facts` 를 거친다 — 테스트·검증 스크립트가 그 함수를 대역으로
    바꿔 사실을 넣는다. 결과에 판정과 '모든 줄 처리' 보고를 붙인다.
    """
    s = get_settings()
    schema = SingleCallExtractionResult
    from app.ingest import extract
    # mock/실제는 추출 모듈과 같은 설정으로 가른다 — 테스트·검증이 그 설정을 바꿔 모델을 막는다.
    # 따로 보면 .env 의 INGEST_MODE=real 이 새어 실제 호출이 나간다(2026-11-07 검증에서 발견)
    if extract.get_settings().ingest_mode != "real":
        base = await extract.extract_facts(**(mock_args or {}), media=media,
                                           usage_context=ctx, raw_sink=raw_sink)
        return _wrap_mock(base, list(line_ids), hints)
    from app.ingest.providers import anthropic_call, budget, measured, parse_model_spec

    spec = parse_model_spec(s.extract_model)
    if spec.provider != "anthropic":
        raise RuntimeError(f"한 번 호출 추출은 Anthropic 모델만 쓴다(S1): {s.extract_model}")
    budget.check_before_call()

    async def caller():
        return await anthropic_call.call_extract(spec.model, prompt, media, schema,
                                                 effort=s.extract_anthropic_effort,
                                                 max_tokens=s.extract_anthropic_max_tokens)

    reply = await measured.measured_call(
        settings=s, model=spec.model, caller=caller, prompt=prompt, media=media, schema=schema,
        sink=usage_sink, context=ctx, prompt_hash=hashlib.sha256(prompt.encode()).hexdigest()[:16],
        raw_sink=raw_sink, max_output_tokens=s.extract_anthropic_max_tokens)
    sink = None if reply.reused else raw_sink
    result = await raw_responses.parse_checked(
        sink, ctx, reply.raw_response_id, reply.finish_reason,
        lambda: schema.model_validate_json(reply.text), what="한 번 호출 추출")
    result._raw_response_id = reply.raw_response_id
    return result


@dataclass
class SingleCallOutcome:
    """시도를 마친 결과. `result` 가 None 이면 한 번도 성공하지 못했다(판정도 없다)."""
    result: SingleCallExtractionResult | None
    unprocessed: list[dict] = field(default_factory=list)
    attempts: int = 0
    numbered_text: str = ""


def _first_line(numbered: str, n: int) -> str:
    for line in numbered.split("\n"):
        m = _LINE.match(line)
        if m and int(m.group(1)) == n:
            return line[m.end():].strip()[:40]
    return ""


async def extract_single(*, source_id: int, source_type: str, text: str, media: list[Path],
                         glossary, hints=(), usage_sink=None, usage_context=None, raw_sink=None,
                         only_lines: list[int] | None = None,
                         owner_forced: bool = False) -> SingleCallOutcome:
    """분류+사실을 한 호출로 받고, 처리 안 된 줄만 이어서 최대 `extract_max_attempts` 번까지 시도한다.

    `only_lines` 가 있으면(사장님 [다시 시도]) 그 줄부터 이어서 뽑는다. 비용 상한 도달은 다시 시도하지 않는다.
    """
    from app.ingest.providers.budget import BudgetExceeded

    s = get_settings()
    numbered, line_ids = number_lines(text)
    todo = list(only_lines) if only_lines is not None else list(line_ids)
    result = None
    reason = TRUNCATED
    attempts = 0
    # 테스트 대역 설정(SimpleNamespace)에 칸이 없으면 기본 3번이다(S7)
    for attempt in range(1, getattr(s, "extract_max_attempts", 3) + 1):
        attempts = attempt
        continuing = result is not None or only_lines is not None
        body = continuation_text(numbered, todo) if continuing and line_ids else numbered
        prompt = render_prompt(source_type=source_type, text=body, glossary=glossary, hints=hints,
                               continuing=continuing and bool(line_ids), owner_forced=owner_forced)
        try:
            got = await _call_once(prompt, media, _attempt_context(usage_context, attempt),
                                   line_ids=todo, hints=hints, usage_sink=usage_sink, raw_sink=raw_sink,
                                   mock_args={"source_id": source_id, "source_type": source_type,
                                              "text": body, "glossary": glossary})
        except BudgetExceeded:
            raise
        except raw_responses.TruncatedOutputError as exc:
            reason = TRUNCATED
            logger.warning("한 번 호출 잘림 source=%s 시도 %d: %s", source_id, attempt, exc)
            continue
        except Exception as exc:  # 호출 실패·형식 오류·거절은 다음 시도로
            reason = CALL_FAILED
            logger.warning("한 번 호출 실패 source=%s 시도 %d: %s", source_id, attempt, exc)
            continue
        # 사실마다 자기가 나온 원래 응답을 가리키게 한다 — 이어서 뽑은 사실도 그 시도의 응답을 본다
        raw_id = getattr(got, "raw_response_id", None)
        for a in got.assertions:
            a._raw_response_id = raw_id
        result = got if result is None else merge(result, got, attempt=attempt)
        verdict = judge(todo, result)
        if line_ids:
            if not verdict.unprocessed:
                todo = []
                break
            todo = verdict.unprocessed
            reason = TRUNCATED
            logger.warning("한 번 호출 끊김 source=%s 시도 %d 남은 줄 %d", source_id, attempt, len(todo))
        elif verdict.empty:
            reason = EMPTY
        else:
            todo = []
            break
    unprocessed: list[dict] = []
    if line_ids and todo:
        unprocessed = [{"from_line": a, "to_line": b, "reason": reason,
                        "first_line": _first_line(numbered, a), "attempts": attempts}
                       for a, b in to_ranges(todo)]
    elif not line_ids and (result is None or judge([], result).empty):
        unprocessed = [{"from_line": 0, "to_line": 0, "reason": reason if result is None else EMPTY,
                        "first_line": "", "attempts": attempts}]
    return SingleCallOutcome(result, unprocessed, attempts, numbered)
