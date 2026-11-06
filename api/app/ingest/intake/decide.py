"""분류 결정 규칙 — 점주 칩 가산(B-D3a), 다중 라벨(B-D3b), 가장 가까운 로직(B-D4). 순수 함수."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.ingest.intake.ir import Candidate
from app.ingest.intake.registry import CARD_LOGICS, LOGICS


class IntakeClassificationError(Exception):
    """분류를 믿을 수 없다. 조용히 다른 로직으로 보내지 않고 작업을 실패시킨다."""


@dataclass(frozen=True)
class Ranked:
    logic: str
    score: float


@dataclass(frozen=True)
class Thresholds:
    boost: float
    multi_label_min: float
    ambiguous_top_min: float
    ambiguous_gap_min: float

    @classmethod
    def from_settings(cls, s) -> "Thresholds":
        return cls(s.intake_owner_hint_boost, s.intake_multi_label_min,
                   s.intake_ambiguous_top_min, s.intake_ambiguous_gap_min)


@dataclass(frozen=True)
class SectionDecision:
    candidate_id: str
    logic: str
    extractors: tuple[str, ...]
    ambiguous: bool
    fallback_unregistered: bool
    hint_changed_decision: bool
    inherited_from: str | None
    model_ranking: tuple[Ranked, ...]
    boosted_ranking: tuple[Ranked, ...]

    def as_dict(self) -> dict:
        return {"candidate_id": self.candidate_id, "logic": self.logic,
                "extractors": list(self.extractors), "ambiguous": self.ambiguous,
                "fallback_unregistered": self.fallback_unregistered,
                "hint_changed_decision": self.hint_changed_decision,
                "inherited_from": self.inherited_from,
                "model_ranking": [[r.logic, r.score] for r in self.model_ranking],
                "boosted_ranking": [[r.logic, r.score] for r in self.boosted_ranking]}

    @classmethod
    def from_dict(cls, d: dict) -> "SectionDecision":
        return cls(d["candidate_id"], d["logic"], tuple(d["extractors"]), d["ambiguous"],
                   d["fallback_unregistered"], d["hint_changed_decision"], d["inherited_from"],
                   tuple(Ranked(l, s) for l, s in d["model_ranking"]),
                   tuple(Ranked(l, s) for l, s in d["boosted_ranking"]))


def _sort(ranking: Sequence[Ranked]) -> tuple[Ranked, ...]:
    return tuple(sorted(ranking, key=lambda r: (-r.score, LOGICS.index(r.logic))))


def _boost(ranking: Sequence[Ranked], hints: Sequence[str], amount: float) -> tuple[Ranked, ...]:
    chosen = set(hints)
    return _sort([Ranked(r.logic, min(1.0, r.score + amount)) if r.logic in chosen else r
                  for r in ranking])


def _resolve(logic: str, ranking: Sequence[Ranked], registered: Sequence[str]) -> tuple[str, bool]:
    if logic in registered:
        return logic, False
    for r in ranking:
        if r.logic in registered:
            return r.logic, True
    return registered[0], True


def _decide(cid: str, model: Sequence[Ranked], *, hints, th: Thresholds,
            registered: Sequence[str]) -> SectionDecision:
    model_sorted = _sort(model)
    boosted = _boost(model_sorted, hints, th.boost)
    if not boosted:
        raise IntakeClassificationError(f"구간 {cid} 의 순위가 비었다")
    top = boosted[0]
    second = boosted[1] if len(boosted) > 1 else None
    ambiguous = top.score < th.ambiguous_top_min or (
        second is not None and top.score - second.score < th.ambiguous_gap_min)
    fallback = False
    if top.logic == "NONE":
        extractors: tuple[str, ...] = ()
    else:
        first, fallback = _resolve(top.logic, boosted, registered)
        extractors = (first,)
        if (top.logic in CARD_LOGICS and second is not None and second.logic in CARD_LOGICS
                and second.score >= th.multi_label_min):
            extra, extra_fallback = _resolve(second.logic, boosted, registered)
            if extra not in extractors:
                extractors += (extra,)
                fallback = fallback or extra_fallback
    return SectionDecision(cid, top.logic, extractors, ambiguous, fallback,
                           model_sorted[0].logic != top.logic, None, model_sorted, boosted)


def decide_all(candidates: Sequence[Candidate], model: Mapping[str, Sequence[Ranked]], *,
               hints: Sequence[str], th: Thresholds,
               registered: Sequence[str]) -> list[SectionDecision]:
    own: dict[str, SectionDecision] = {}
    for c in candidates:
        if not c.sampled:
            continue
        if c.candidate_id not in model:
            raise IntakeClassificationError(f"분류 결과에 구간 {c.candidate_id} 이 없다")
        own[c.candidate_id] = _decide(c.candidate_id, model[c.candidate_id], hints=hints, th=th,
                                      registered=registered)
    if not own:
        raise IntakeClassificationError("표본 구간이 없다")
    sampled_pos = [i for i, c in enumerate(candidates) if c.sampled]
    out = []
    for i, c in enumerate(candidates):
        if c.sampled:
            out.append(own[c.candidate_id])
            continue
        nearest = min(sampled_pos, key=lambda j: (abs(j - i), j))
        src = own[candidates[nearest].candidate_id]
        out.append(SectionDecision(c.candidate_id, src.logic, src.extractors, src.ambiguous,
                                   src.fallback_unregistered, src.hint_changed_decision,
                                   src.candidate_id, src.model_ranking, src.boosted_ranking))
    return out


def source_decision(decisions: Sequence[SectionDecision], *, hints: Sequence[str],
                    th: Thresholds, registered: Sequence[str]) -> SectionDecision:
    """자료 전체를 한 로직으로 다루는 정규화기용(2026-10-11 결정). 모델 점수 평균에 같은 규칙."""
    own = [d for d in decisions if d.inherited_from is None]
    if own and all(d.logic == "NONE" for d in own):
        avg = [Ranked("NONE", 1.0)]
    else:
        totals = {l: 0.0 for l in LOGICS}
        for d in own:
            for r in d.model_ranking:
                totals[r.logic] += r.score
        avg = [Ranked(l, round(v / max(1, len(own)), 4)) for l, v in totals.items() if v > 0]
    return _decide("source", avg, hints=hints, th=th, registered=registered)


# 점주 "그래도 추출하기"의 덮는 로직을 고른 근거(후속 1 사용자 결정 2026-10-11)
OVERRIDE_BASES = ("OWNER_HINT", "NEXT_RANKED", "REGISTERED_DEFAULT")


def _without_none(ranking: Sequence[Ranked]) -> tuple[Ranked, ...]:
    return _sort([r for r in ranking if r.logic != "NONE" and r.score > 0])


def override_logic(decisions: Sequence[SectionDecision], source: SectionDecision, *,
                   hints: Sequence[str], registered: Sequence[str]) -> tuple[str, str]:
    """NONE 판정 자료를 점주가 그래도 추출할 때 덮을 로직과 근거. 모델을 부르지 않는다.

    1. 점주 칩이 있으면 칩 첫째(OWNER_HINT).
    2. 없으면 저장된 자료 단위 판정의 가산 전 모델 순위에서 NONE 을 뺀 1위(NEXT_RANKED).
       구간이 모두 NONE 이면 source_decision 이 순위를 NONE 1.0 하나로 접으므로, 그때는 같은
       평균 규칙으로 구간(상속 제외)의 가산 전 모델 점수를 다시 모아 고른다. 동점은 LOGICS 순서.
    3. 순위에 NONE 말고 아무것도 없을 때만 등록 추출기 첫째(REGISTERED_DEFAULT).
    """
    if hints:
        return hints[0], "OWNER_HINT"
    ranked = _without_none(source.model_ranking)
    if not ranked:
        own = [d for d in decisions if d.inherited_from is None]
        totals = {l: 0.0 for l in LOGICS}
        for d in own:
            for r in d.model_ranking:
                totals[r.logic] += r.score
        ranked = _without_none([Ranked(l, round(v / max(1, len(own)), 4))
                                for l, v in totals.items()])
    if ranked:
        return ranked[0].logic, "NEXT_RANKED"
    return registered[0], "REGISTERED_DEFAULT"


def owner_override(decisions: Sequence[SectionDecision], source: SectionDecision, *,
                   logic: str, registered: Sequence[str]
                   ) -> tuple[list[SectionDecision], SectionDecision]:
    """NONE 판정을 점주 선택 로직으로 덮은 판정(구간 구성은 그대로). 모델을 부르지 않는다.

    구간 id·상속 관계는 지난 판정과 같아 재시도의 구간 번호가 흔들리지 않는다. 지난 모델 순위는
    기록으로 남기고, 덮은 순위(boosted)는 그 로직 하나다. hint_changed_decision 은 참이다.
    """
    if logic not in LOGICS or logic == "NONE":
        raise ValueError(f"덮을 수 없는 로직이다: {logic}")
    first, fallback = _resolve(logic, (), registered)
    forced = (Ranked(logic, 1.0),)

    def over(d: SectionDecision) -> SectionDecision:
        return SectionDecision(d.candidate_id, logic, (first,), False, fallback, True,
                               d.inherited_from, d.model_ranking, forced)

    return [over(d) for d in decisions], over(source)
