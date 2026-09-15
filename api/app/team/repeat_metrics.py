"""W 반복: 전체 고정 분모 성능, 만장일치 안정성, 모든 짝의 안전성."""
from statistics import median
from app.team.extraction import VERDICT_RANK


def compare_repeats(baseline, candidate, truth):
    ids = {f["fact_id"] for f in truth}
    if not ids or len(ids) != len(truth):
        raise ValueError("빈/중복 정답 분모")
    if len(baseline) != len(candidate) or len(baseline) < 3:
        raise ValueError("동일 횟수 최소 3회 짝비교 필요")
    if any(set(run) - ids for run in [*baseline, *candidate]):
        raise ValueError("정답지 밖 판정 ID")
    must = {f["fact_id"] for f in truth if f.get("must_have")}
    def values(runs, fid):
        return [r.get(fid, "UNDETERMINED") for r in runs]
    def stability(vs):
        if all(v == "COVERED" for v in vs):
            return "SUCCESS"
        if len(set(vs)) == 1 and vs[0] != "UNDETERMINED":
            return "FAILURE"
        return "VARIABLE"
    counts_a = [sum(v == "COVERED" for v in r.values()) for r in baseline]
    counts_b = [sum(v == "COVERED" for v in r.values()) for r in candidate]
    deltas = [b-a for a,b in zip(counts_a, counts_b)]
    transitions, regressions, unjudged = {}, [], []
    for fid in sorted(ids):
        va, vb = values(baseline, fid), values(candidate, fid)
        if any(v not in VERDICT_RANK for v in [*va, *vb]):
            raise ValueError("지원하지 않는 판정")
        transitions[fid] = (stability(va), stability(vb))
        if fid in must:
            if "UNDETERMINED" in [*va, *vb]:
                unjudged.append(fid)
            if any(VERDICT_RANK[b] < VERDICT_RANK[a] for a,b in zip(va,vb)):
                regressions.append(fid)
    degraded = [fid for fid in must if transitions[fid] == ("SUCCESS", "VARIABLE")]
    return dict(denominator=len(ids), counts_a=counts_a, counts_b=counts_b,
                deltas=deltas, median_delta=median(deltas), transitions=transitions,
                must_have_regressions=sorted(regressions), must_have_unjudged=sorted(unjudged),
                stability_degraded=sorted(degraded), safety_passed=not (regressions or unjudged or degraded),
                control_width=max([*counts_a,*counts_b])-min([*counts_a,*counts_b]))
