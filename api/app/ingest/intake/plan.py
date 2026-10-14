"""판정 → 추출 계획(P2). 글 자료만 구간별로 거르고 묶으며, 나머지는 자료 단위다. 순수 함수."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.ingest.intake.decide import SectionDecision
from app.ingest.intake.registry import JOINER, SECTIONED_NORMALIZERS


@dataclass(frozen=True)
class ExtractionPlan:
    skip: bool
    text: str | None
    segments: list[tuple[str, list]] | None
    notice_segment_ids: frozenset[str]
    hold_all_notice: bool
    # 기록·로그용: {"segment_id": "seg1"|None, "key": "RECIPE"|"NOTICE", "candidates": [...]}
    groups: tuple[dict, ...]


def plan_extraction(*, normalizer: str, decisions: Sequence[SectionDecision],
                    source: SectionDecision,
                    sections: Mapping[str, str] | None) -> ExtractionPlan:
    if not (normalizer in SECTIONED_NORMALIZERS and sections is not None):
        if source.logic == "NONE":
            return ExtractionPlan(True, None, None, frozenset(), False, ())
        return ExtractionPlan(False, None, None, frozenset(), source.logic == "NOTICE", ())
    kept = [d for d in decisions if d.logic != "NONE"]
    if not kept:
        return ExtractionPlan(True, None, None, frozenset(), False, ())
    missing = [d.candidate_id for d in kept if d.candidate_id not in sections]
    if missing:  # 글을 조용히 빼지 않는다
        raise KeyError(f"전처리 구간에 없는 후보: {missing}")
    joiner = JOINER[normalizer]
    by_key: dict[str, list[str]] = {}
    for d in kept:
        keys = ["NOTICE"] if d.logic == "NOTICE" else list(d.extractors)
        for key in keys:
            by_key.setdefault(key, []).append(d.candidate_id)
    text = joiner.join(sections[d.candidate_id] for d in kept)
    if len(by_key) == 1:
        (key, cands), = by_key.items()
        return ExtractionPlan(False, text, None, frozenset(), key == "NOTICE",
                              ({"segment_id": None, "key": key, "candidates": cands},))
    segments, groups, notice_ids = [], [], set()
    for i, (key, cands) in enumerate(by_key.items(), 1):
        segments.append((joiner.join(sections[c] for c in cands), []))
        groups.append({"segment_id": f"seg{i}", "key": key, "candidates": cands})
        if key == "NOTICE":
            notice_ids.add(f"seg{i}")
    return ExtractionPlan(False, text, segments, frozenset(notice_ids), False, tuple(groups))
