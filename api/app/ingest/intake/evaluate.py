"""분류기 평가 지표 — 순수 계산. DB·모델·파일을 만지지 않는다(B-D7)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class EvalReport:
    source_accuracy: float
    section_accuracy: float
    # confusion[정답][예측] = 구간 수
    confusion: dict[str, dict[str, int]]
    ambiguous_ratio: float
    per_logic_recall: dict[str, float]
    section_count: int = 0
    source_count: int = 0


def source_truth(candidates: Sequence[Mapping]) -> str:
    """자료 정답 = 구간 정답의 다수결. 같으면 앞 구간의 정답."""
    labels = [c["expected"] for c in candidates]
    counts = Counter(labels)
    best = max(counts.values())
    return next(l for l in labels if counts[l] == best)


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


def score(cases: Sequence[Mapping], decisions_by_case: Mapping[str, Mapping]) -> EvalReport:
    confusion: dict[str, dict[str, int]] = {}
    sec_ok = sec_n = amb = src_ok = src_n = 0
    for case in cases:
        got = decisions_by_case[case["case_id"]]
        by_id = {d.candidate_id: d for d in got["sections"]}
        for cand in case["candidates"]:
            d = by_id[cand["candidate_id"]]
            row = confusion.setdefault(cand["expected"], {})
            row[d.logic] = row.get(d.logic, 0) + 1
            sec_n += 1
            sec_ok += d.logic == cand["expected"]
            amb += bool(d.ambiguous)
        src_n += 1
        src_ok += got["source"].logic == source_truth(case["candidates"])
    recall = {label: _ratio(row.get(label, 0), sum(row.values()))
              for label, row in sorted(confusion.items())}
    return EvalReport(_ratio(src_ok, src_n), _ratio(sec_ok, sec_n), confusion,
                      _ratio(amb, sec_n), recall, sec_n, src_n)
