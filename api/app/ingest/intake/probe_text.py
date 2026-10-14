"""글 자료 훑기(B-D2 ①) — 무료. 후보마다 앞부분만 상한 안에서."""
from __future__ import annotations

from typing import Sequence

from app.ingest.intake.grouping import Group
from app.ingest.intake.ir import Candidate, Locator, ProbeResult


def probe_groups(normalizer: str, groups: Sequence[Group], *, budget_chars: int) -> ProbeResult:
    per = max(1, budget_chars // max(1, len(groups)))
    return ProbeResult(normalizer, tuple(
        Candidate(g.candidate_id, g.locator, "\n".join(g.units)[:per]) for g in groups))


def probe_owner_text(question: str, answer: str) -> ProbeResult:
    from app.ingest.owner_text import compose_text
    return ProbeResult("OWNER_TEXT", (
        Candidate("c1", Locator("WHOLE", "", ""), compose_text(question, answer)),))
