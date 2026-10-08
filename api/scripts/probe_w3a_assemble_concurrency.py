"""W3a 사실 조립 배치 동시성 측정 (W3-1b). DB 없음, 모델은 합성 지연 대역 — 비용 0.

합성 대상 8개 × 사실 5개, assemble_batch_facts=5 → 배치 8. assemble_concurrency c ∈ {1, 2, 4} 의
벽시계 시간을 재고 다음을 확인한다.
  ① 세 c 의 PlanningOutcome.proposals 가 같다
  ② c 가 클수록 짧다(기록만 — 합격선 없음)
  ③ c=4·non-strict 에서 배치 3 에만 예외 → failed_entity_ids 가 그 배치 대상, 나머지 제안은 ①과 같다
  ④ 같은 실패에서 strict 면 RuntimeError
  ⑤ 원가 시도 기록 수 = 배치 수, segment_id 집합 plan0..plan7 이 c 와 무관
실제 모델 지연·공급자 rate limit 은 재지 않는다.

    cd api && PYTHONPATH=. .venv/bin/python -B scripts/probe_w3a_assemble_concurrency.py \
        --model-delay-ms 1500 --out /tmp/w3a_concurrency.json
"""
import argparse
import asyncio
import json
import logging
import os
import platform
import statistics
import time
from contextlib import ExitStack
from decimal import Decimal
from unittest.mock import patch

import app.config
from app.config import Settings
from app.ingest import extract, fact_assembly, pipeline, resilience
from app.ingest.card_plan import EntityGroup, PlanFact, fact_sort_key
from app.ingest.extract import gemini, mock

ENTITIES, FACTS, BATCH_FACTS = 8, 5, 5
FAIL_BATCH = 3
SOURCE_ID = 1
STORE_ID = 1


class ListSink:
    """원가 시도를 메모리에 모은다(app.usage.recorder.UsageSink 모양)."""

    def __init__(self):
        self.attempts = []

    async def start(self, attempt) -> int:
        self.attempts.append(attempt)
        return len(self.attempts)

    async def finalize(self, attempt_id, attempt, known_cost, cost, price_status) -> None:
        self.attempts[attempt_id - 1] = attempt


def _groups() -> list[EntityGroup]:
    """합성 대상 8개. 대상마다 ICE 수치 2·ICE 단계 2·규격 없는 금지 1."""
    groups = []
    for e in range(1, ENTITIES + 1):
        base = e * 100
        facts = [
            PlanFact(fact_revision_id=base + i, fact_id=base + i, entity_id=e,
                     subject=f"합성음료{e}", predicate=f"속성{i}",
                     variant_temperature="ICE" if i < 4 else None, variant_size=None,
                     quantity_value=Decimal(10 * i) if i < 2 else None,
                     quantity_unit="ml" if i < 2 else None,
                     value_text=None if i < 2 else f"합성 값 {i}",
                     polarity="NEGATE" if i == 4 else "AFFIRM",
                     step_order=(i - 1) if i in (2, 3) else None,
                     conditions=(), exceptions=(),
                     original_assertion=f"합성음료{e} 사실 {i}", assertion=f"합성음료{e} 사실 {i}",
                     requires_fact_ids=((base + 2,) if i == 3 else ()))
            for i in range(FACTS)
        ]
        groups.append(EntityGroup(e, f"합성음료{e}", tuple(sorted(facts, key=fact_sort_key))))
    return groups


def _settings(c: int) -> Settings:
    return Settings(_env_file=None, ingest_mode="real", gemini_api_key="synthetic",
                    assemble_batch_facts=BATCH_FACTS, assemble_concurrency=c,
                    w_entity_revision_enabled=True, w_fact_assembly_enabled=True)


async def _run(c: int, *, delay: float, fail_names: set[str] = frozenset(), strict: bool = True):
    settings = _settings(c)
    sink = ListSink()

    async def fake_call(prompt, media, schema=None, max_output_tokens=None):
        entities = json.loads(prompt.split(fact_assembly.PLAN_INPUT_MARKER, 1)[1])
        await asyncio.sleep(delay)
        if {e["이름"] for e in entities} & fail_names:
            raise ValueError("합성 배치 실패")
        body = mock._planned(entities, ["레시피"])
        return gemini.CallResult(body.model_dump_json(), {}, "STOP")

    with ExitStack() as stack:
        for obj, name, replacement in [
            (app.config, "get_settings", lambda: settings),
            (gemini, "get_settings", lambda: settings),
            (extract, "get_settings", lambda: settings),
            (resilience, "get_settings", lambda: settings),
            (gemini, "_call", fake_call),
        ]:
            stack.enter_context(patch.object(obj, name, replacement))
        started = time.perf_counter()
        outcome = await fact_assembly.plan_entities(
            source_id=SOURCE_ID, groups=_groups(), categories=["레시피"], glossary=[],
            usage_sink=sink,
            context_for=lambda i: pipeline._ctx_for(
                (STORE_ID, None, "REGISTRATION", "PRODUCT", None, None), SOURCE_ID,
                "ASSEMBLE", segment_id=f"plan{i}"),
            strict=strict)
        elapsed = time.perf_counter() - started
    return outcome, elapsed, sink


def _machine() -> str:
    return f"{platform.platform()} · {platform.machine()} · CPU {os.cpu_count()} · Python {platform.python_version()}"


async def main(delay_ms: int, repeats: int) -> dict:
    delay = delay_ms / 1000
    batches = fact_assembly.build_plan_batches(_groups(), limit=BATCH_FACTS)
    fail_names = {g.canonical_name for g in batches[FAIL_BATCH].groups}
    fail_ids = sorted(g.entity_id for g in batches[FAIL_BATCH].groups)

    timings: dict[int, list[float]] = {}
    proposals: dict[int, dict] = {}
    segments: dict[int, list[str]] = {}
    attempt_counts: dict[int, int] = {}
    for c in (1, 2, 4):
        timings[c] = []
        for _ in range(repeats):
            outcome, elapsed, sink = await _run(c, delay=delay)
            timings[c].append(round(elapsed, 3))
            proposals.setdefault(c, outcome.proposals)
            assert outcome.proposals == proposals[c], "같은 c 안에서 제안이 달라졌다"
            segments[c] = sorted({a.context.segment_id for a in sink.attempts})
            attempt_counts[c] = len(sink.attempts)

    same = proposals[1] == proposals[2] == proposals[4]
    medians = {c: statistics.median(v) for c, v in timings.items()}
    faster = medians[1] > medians[2] > medians[4]

    partial, _, _ = await _run(4, delay=delay, fail_names=fail_names, strict=False)
    rest_same = (list(partial.failed_entity_ids) == fail_ids
                 and partial.proposals == {k: v for k, v in proposals[1].items()
                                           if k not in fail_ids})
    try:
        await _run(4, delay=delay, fail_names=fail_names, strict=True)
        strict_raised = False
    except RuntimeError as exc:
        strict_raised = "카드 조립 실패" in str(exc) and isinstance(exc.__cause__, ValueError)

    expected_segments = [f"plan{i}" for i in range(len(batches))]
    segments_ok = all(segments[c] == sorted(expected_segments)
                      and attempt_counts[c] == len(batches) for c in (1, 2, 4))

    return {
        "conditions": {
            "entities": ENTITIES, "facts_per_entity": FACTS,
            "assemble_batch_facts": BATCH_FACTS, "batches": len(batches),
            "model_delay_ms": delay_ms, "repeats": repeats,
            "ingest_model_concurrency": _settings(1).ingest_model_concurrency,
            "machine": _machine(),
        },
        "timings_sec": {str(c): v for c, v in timings.items()},
        "median_sec": {str(c): round(m, 3) for c, m in medians.items()},
        "checks": {
            "1_same_proposals": same,
            "2_faster_with_c (기록만)": faster,
            "3_partial_failure": {"failed_entity_ids": list(partial.failed_entity_ids),
                                  "expected": fail_ids, "errors": list(partial.errors),
                                  "rest_same": rest_same},
            "4_strict_raises": strict_raised,
            "5_segments": {"by_c": {str(c): segments[c] for c in segments},
                           "attempts_by_c": {str(c): attempt_counts[c] for c in attempt_counts},
                           "ok": segments_ok},
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-delay-ms", type=int, default=1500)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    result = asyncio.run(main(args.model_delay_ms, args.repeats))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    print()
    print("| c | 반복별 벽시계(초) | 중앙값(초) |")
    print("|---|---|---|")
    for c, values in result["timings_sec"].items():
        print(f"| {c} | {', '.join(f'{v:.3f}' for v in values)} | {result['median_sec'][c]:.3f} |")
