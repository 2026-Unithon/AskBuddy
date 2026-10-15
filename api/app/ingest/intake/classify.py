"""입구 분류 호출(B-D3) — 자료(또는 답변 묶음)당 1회, 온도 0, JSON. 원장 stage=CLASSIFY.

원래 응답은 판정 기록(intake_route_decisions.model_sections)에 남긴다(계획 P9).
실패는 IntakeClassificationError 로 올린다 — 호출부가 작업을 FAILED 로 멈춘다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, Field

from app.config import get_settings
from app.ingest.intake.decide import IntakeClassificationError, Ranked
from app.ingest.intake.ir import ProbeResult
from app.ingest.providers import measured_generate, parse_model_spec

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "classify_intake.ko.txt"

Logic = Literal["RECIPE", "PROCEDURE", "POLICY", "REFERENCE", "NOTICE", "NONE"]


class RankedLogic(BaseModel):
    logic: Logic
    score: float = Field(ge=0, le=1)


class ClassifiedSection(BaseModel):
    candidate_id: str
    ranking: list[RankedLogic]
    reason: str = ""


class IntakeClassification(BaseModel):
    sections: list[ClassifiedSection] = []


@dataclass(frozen=True)
class ClassifyOutcome:
    model_sections: dict[str, list[Ranked]]
    raw: dict
    model: str
    prompt_digest: str


def render_prompt(probes: Sequence[ProbeResult], *, hints: Sequence[str],
                  context: str | None,
                  candidate_hints: Mapping[str, Sequence[str]] | None = None
                  ) -> tuple[str, list[Path]]:
    """candidate_hints: (접두어 포함) 후보 id → 그 자료의 점주 칩. 후보 머리줄에 표시한다."""
    lines, images = [], []
    for probe in probes:
        for c in probe.sampled():
            loc = c.locator
            mark = ""
            if candidate_hints and candidate_hints.get(c.candidate_id):
                mark = f" [점주 선택: {', '.join(candidate_hints[c.candidate_id])}]"
            lines.append(f"### {c.candidate_id} ({probe.normalizer} {loc.kind} {loc.start}~{loc.end}){mark}")
            for img in c.images:
                images.append(img)
                lines.append(f"[그림 {len(images)}]")
            lines.append(c.text or "(글 없음)")
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (template.replace("{hints}", ", ".join(hints) if hints else "(고르지 않음)")
              .replace("{context}", context or "(없음)")
              .replace("{sections}", "\n".join(lines)))
    return prompt, images


def mock_sections(probes: Sequence[ProbeResult], *, hints: Sequence[str]) -> dict:
    """mock 모드 합성 결과 — 칩이 있으면 첫 칩, 없으면 RECIPE. 지금 mock 추출 흐름을 바꾸지 않는다."""
    logic = hints[0] if hints else "RECIPE"
    return {"sections": [{"candidate_id": c.candidate_id,
                          "ranking": [{"logic": logic, "score": 0.9}], "reason": "mock"}
                         for p in probes for c in p.sampled()]}


async def classify(probes: Sequence[ProbeResult], *, hints: Sequence[str], context: str | None,
                   usage_sink, usage_context,
                   candidate_hints: Mapping[str, Sequence[str]] | None = None) -> ClassifyOutcome:
    s = get_settings()
    spec = parse_model_spec(s.intake_classifier_model)
    prompt, images = render_prompt(probes, hints=hints, context=context,
                                  candidate_hints=candidate_hints)
    try:
        result = await measured_generate(
            spec, prompt, images, IntakeClassification, usage_sink=usage_sink,
            usage_context=usage_context, raw_sink=None,
            max_output_tokens=s.intake_classifier_max_output_tokens, what="입구 분류",
            mock_build=lambda: IntakeClassification.model_validate(
                mock_sections(probes, hints=hints)))
    except Exception as exc:
        raise IntakeClassificationError(f"분류 호출 실패: {type(exc).__name__}: {exc}") from exc
    wanted = {c.candidate_id for p in probes for c in p.sampled()}
    got = {sec.candidate_id for sec in result.sections}
    if got - wanted:
        raise IntakeClassificationError(f"입력에 없는 구간을 냈다: {sorted(got - wanted)}")
    return ClassifyOutcome(
        {sec.candidate_id: [Ranked(r.logic, r.score) for r in sec.ranking]
         for sec in result.sections},
        result.model_dump(mode="json"), spec.model,
        hashlib.sha256(prompt.encode()).hexdigest()[:16])
