"""외부 앱 추출 실행 여러 개를 칸 단위 키로 투표해 다수결 참조(reference)를 만든다.

입력: 저장소 루트 `추출결과/` (Git 제외) — 실행별 결과 JSON 과 Gemini 결과 텍스트.
출력: `api/eval/data/store-a/reference/<source_key>__consensus<N>__<날짜>.json` (Git 제외).
참조는 정답지가 아니다. 승격 절차는 docs/dev/plan/W_REFERENCE_EXTRACTION_20260920.md.

키는 표현 차이(속성 이름·단위 철자·재료명 위치)를 지우고 '같은 칸의 같은 값'만 남긴다.
대표 레코드는 우선순위가 높은 실행에서 고른다. 다수에 못 미친 키는 결과에 넣지 않고
contested 로 따로 둔다 (참조 문서: 불확실한 것은 추정으로 채우지 않는다).

    python api/scripts/build_consensus_reference.py [--date YYYYMMDD]
"""
import argparse
import collections
import datetime
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "추출결과"
BASE = ROOT / "api" / "eval" / "data" / "store-a"
TODAY = datetime.date.today().strftime("%Y%m%d")
# 대표 레코드 우선순위: PDF 원본 + 4배 재확인 → 전 쪽 확대 → 확대 → 확대 → 확대 → 확대 없음
PRIORITY = ["C2 opus", "C1 opus", "C4 sonnet", "G3 sol", "G4 sol", "C3 sonnet"]
RUN_LABEL = {
    "C1 opus": "claude-opus-5.5 #1 (PNG 4장+basestock)",
    "C2 opus": "claude-opus-5.5 #2 (recipebook.pdf)",
    "C3 sonnet": "claude-sonnet-5.5 #3 (PNG 4장+basestock, 확대 없음)",
    "C4 sonnet": "claude-sonnet-5.5 #4 (recipebook.pdf)",
    "G3 sol": "gpt-6 sol #3 (recipebook.pdf)",
    "G4 sol": "gpt-6 sol #4 (PNG 4장+basestock)",
}
# 실행 ID → 결과 폴더 (추출결과/ 기준). 폴더 안의 결과 JSON 하나를 읽는다.
# 외부 앱이 붙인 파일명에 자료 고유명이 섞일 수 있어 파일명은 코드에 적지 않는다
RUN_DIRS = {
    "C1 opus": "claude 추출결과/1. opus 5.5 높음",
    "C2 opus": "claude 추출결과/2. opus 5.5 높음",
    "C3 sonnet": "claude 추출결과/3. sonnet 5.5 중간",
    "C4 sonnet": "claude 추출결과/4. sonnet 5.5 중간",
    "G3 sol": "gpt 추출결과/3. 6 sol 중간/outputs",
    "G4 sol": "gpt 추출결과/4. 6 sol 중간/outputs",
}


def load_all():
    """다수결에 쓰는 실행만 읽는다. Gemini 실행은 사실 수가 2% 수준이라 투표에서 뺐다."""
    out = {}
    for k, d in RUN_DIRS.items():
        found = sorted((RUNS_DIR / d).glob("*.json"))
        if len(found) != 1:
            raise SystemExit(f"{d}: 결과 JSON 이 하나가 아니다 ({[f.name for f in found]})")
        out[k] = json.loads(found[0].read_text())
    return out


UNIT = {"펌프": "p", "레들": "래들", "°c": "℃", "g)": "g", "shot": "샷", "개": "ea"}


def n(s):
    return re.sub(r"[\s/·]", "", str(s or ""))


def unit(u):
    u = n(u).lower()
    return UNIT.get(u, u)


def value(v):
    v = n(v).replace(",", "")
    if re.fullmatch(r"\d+\.\d+", v):
        v = v.rstrip("0").rstrip(".")
    return v


def column(attr):
    a = n(attr)
    if "블렌더" in a or "블랜더" in a:
        return "블렌더"
    for c in ("판매가", "분류", "제조순서", "컵", "샷수", "얼음", "토핑", "재료"):
        if a.startswith(c):
            return c
    return "액상기타"


def names(x):
    """재료명이 어디에 있든 꺼낸다 (item 필드 · conditions '재료명=' · 이름 사실)."""
    out = []
    if x.get("item"):
        out.append(x["item"])
    for c in x.get("conditions") or []:
        m = re.match(r"^(재료명|대상)\s*[=:]\s*(.+)$", str(c))
        if m:
            out.append(m.group(2))
    return [n(v) for v in out]


def key(x):
    """이 사실의 투표 키 하나. 메뉴번호처럼 표에 없는 보조 사실은 None."""
    a = n(x.get("attribute"))
    if a in ("메뉴번호",):
        return None
    col = column(a)
    if x.get("polarity") == "NEGATE":
        return ("NEG", col)
    if col == "판매가":
        return ("PRICE", value(x.get("value")))
    if col == "분류":
        return ("TXT", re.sub(r"(HOT|ICE)", "", n(x.get("value"))), "")
    if col == "제조순서":
        return ("STEP", x.get("step_order"), n(x.get("value")))
    v, u = value(x.get("value")), unit(x.get("unit"))
    m = re.fullmatch(r"([\d.]+)(\D+)", v)
    if m and not u:
        v, u = m.group(1), unit(m.group(2))
    if re.fullmatch(r"[\d.~]+", v):
        return ("NUM", v, u)
    return ("TXT", v, u) if v else None


def t(s):
    """비교 전용 정규화. 레코드 값은 바꾸지 않는다."""
    s = n(s).replace("블랜더", "블렌더").replace("쥬스", "주스")
    return re.sub(r"[\[\]()（）]", "", s)


def blob(x):
    """텍스트 지지 판정용. 값·단위·재료명·조건·원문을 모두 합친다."""
    parts = [x.get("value"), x.get("unit"), x.get("item"), x.get("original_assertion"),
             *(x.get("conditions") or []), *(x.get("exceptions") or [])]
    return t("".join(str(p) for p in parts if p))


def clean(x):
    x = dict(x)
    x["conditions"] = [c for c in x.get("conditions") or [] if not str(c).startswith("근거 파일")]
    x.pop("confidence", None)
    x.pop("fact_id", None)
    return x


def row_maps(D, runs):
    """실행마다 (subject, variant) → 메뉴 번호. 판매가 순서가 메뉴 번호 순서다."""
    out = {}
    for k in runs:
        price = [x for x in D[k]["results"] if x.get("attribute") == "판매가"][:101]
        m = {}
        for i, x in enumerate(price, 1):
            m.setdefault((n(x["subject"]), x.get("variant")), i)
        assert len(m) == 101, (k, len(m))
        out[k] = m
    return out


def vote(groups, runs, quorum):
    """groups[run] = [(row, fact)].

    지지 판정:
    - 가격·부정: 키가 같아야 한다.
    - 숫자·제조 단계: 키가 같거나, 같은 행의 다른 실행 글에 같은 글자(값+단위, 단계 글)가 있으면.
    - 글 값: 같은 행의 다른 실행 글에 그 글자가 있으면. 재료명 위치·'가득' 붙임 같은 표현 차이를 흡수한다.
    대표 실행(우선순위 첫째)의 사실을 먼저 받고, 다른 실행의 사실은 이미 받은 글에
    담기지 않은 것만 더한다 — 같은 값을 표현만 바꿔 두 번 싣지 않는다.
    """
    exact = collections.defaultdict(set)
    text = collections.defaultdict(dict)
    for k in runs:
        for row, x in groups[k]:
            kk = key(x)
            if kk:
                exact[(row, kk)].add(k)
            text[row][k] = text[row].get(k, "") + "|" + blob(x)

    def needle(kk):
        if kk[0] == "NUM":
            return t(kk[1] + kk[2].replace("회", "번"))
        if kk[0] == "STEP":
            return t(kk[2])
        if kk[0] == "TXT":
            return t(kk[1])
        return None

    def support(row, kk):
        who = set(exact[(row, kk)])
        nd = needle(kk)
        if nd:
            who |= {k for k, t in text[row].items() if nd in t}
        return who

    agreed, contested = {}, {}
    accepted_text = collections.defaultdict(str)
    present = set()
    for k in PRIORITY:
        if k not in runs:
            continue
        rep_pass = not agreed  # 첫 실행이 대표
        for row, x in groups[k]:
            kk = key(x)
            if not kk:
                continue
            who = support(row, kk)
            if len(who) < quorum:
                c = contested.setdefault((row, kk), {
                    "row": row, "key": [str(p) for p in kk], "votes": len(who), "of": len(runs),
                    "runs": sorted(who, key=PRIORITY.index), "assertions": {}})
                c["assertions"].setdefault(k, x.get("original_assertion"))
                continue
            # 대표 실행 안에서는 같은 키가 여러 번 나와도 모두 받는다 (예: 시럽 두 종류가 각각 3P)
            if (row, kk) in present and not rep_pass:
                continue
            present.add((row, kk))
            ident = (row, kk, len(agreed))
            nd = needle(kk)
            if not rep_pass and nd and nd in accepted_text[row]:
                continue  # 대표 실행이 이미 같은 글을 담았다
            agreed[ident] = (sorted(who, key=PRIORITY.index), k, x)
        for (row, _, _), (_, rk, x) in agreed.items():
            if rk == k:
                accepted_text[row] += "|" + blob(x)
    # 대표가 같은 키로 여러 사실(예: 단계 순서가 다른 같은 낱말)을 가진 경우를 살린다
    return agreed, list(contested.values())


def build_facts(agreed, prefix, source_key, runs):
    """키 하나가 여러 사실(이름+값)을 가리킬 수 있어 대표 레코드로 중복을 지운다."""
    seen, out = {}, []
    for (row, _k, _i), (who, rep_run, rep) in agreed.items():
        ident = id(rep)
        if ident in seen:
            # 같은 레코드를 다른 키도 지지했다 — 가장 약한 지지를 남긴다
            f = seen[ident]
            f["consensus"]["votes"] = min(f["consensus"]["votes"], len(who))
            continue
        f = clean(rep)
        f["source_key"] = source_key
        f["source_type"] = "SCAN"
        f["consensus"] = {"votes": len(who), "of": len(runs), "row": row,
                          "representative": rep_run, "runs": who}
        seen[ident] = f
        out.append(f)
    out.sort(key=lambda f: (str(f["consensus"]["row"]).zfill(4), f.get("page") or 0))
    for i, f in enumerate(out, 1):
        f["fact_id"] = f"{prefix}-{i:04d}"
    return out


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    D = load_all()
    runs6 = list(RUN_LABEL)

    # ── 레시피북 1~3쪽: 6개 실행, 다수결 4/6
    rmap = row_maps(D, runs6)
    groups = {}
    for k in runs6:
        g = []
        for x in D[k]["results"]:
            if x.get("page") == 4:
                continue
            if any("basestock" in str(c) or "p4.png" in str(c) for c in x.get("conditions") or []):
                continue
            row = rmap[k].get((n(x["subject"]), x.get("variant")))
            # 각주는 실행마다 묶는 단위(펌프 종류별/시럽별)가 달라 한 행으로 모은다
            g.append((row if row else "각주", x))
        groups[k] = g
    agreed, contested = vote(groups, runs6, quorum=4)
    facts = build_facts(agreed, "rb", "a-scan-recipebook", runs6)
    write("a-scan-recipebook", "recipebook.pdf", "rb", facts, contested, runs6, 4,
          {k: len(groups[k]) for k in runs6})

    # ── basestock: PNG 4쪽·basestock 을 받은 3개 실행, 다수결 2/3
    runs3 = ["C1 opus", "G4 sol", "C3 sonnet"]
    groups = {}
    for k in runs3:
        g = []
        for x in D[k]["results"]:
            is4 = x.get("page") == 4 or any(
                "basestock" in str(c) or "p4.png" in str(c) for c in x.get("conditions") or [])
            if is4:
                g.append(("행:" + n(x["subject"]), x))
        groups[k] = g
    agreed, contested = vote(groups, runs3, quorum=2)
    facts = build_facts(agreed, "bs", "a-scan-basestock", runs3)
    for f in facts:
        f["page"] = 1
    write("a-scan-basestock", "basestock.pdf", "bs", facts, contested, runs3, 2,
          {k: len(groups[k]) for k in runs3})


def mark_splits(facts, contested):
    """다수에 못 미쳤지만 2표 이상 받은 판독(예: 3:3)이 있는 행은, 채택 사실 중 같은 글을
    담은 것에 split 표시를 단다. 두 판독이 모두 결과에 남을 수 있으므로 사람이 먼저 본다.
    단어 안 한 글자만 다른 경우(밀선/밑선)를 잡으려고 그 판독의 핵심 글자를 비교한다."""
    flagged = 0
    for c in contested:
        if c["votes"] < 2:
            continue
        needle = t(c["key"][-1] if c["key"][0] == "STEP" else c["key"][1])
        for f in facts:
            if f["consensus"]["row"] != c["row"]:
                continue
            b = blob(f)
            # 같은 판독이거나, 같은 길이의 1글자 차이 변형을 담고 있으면 표시
            hit = needle in b or any(
                len(w) == len(needle) and sum(a != z for a, z in zip(w, needle)) == 1
                for w in (b[i:i + len(needle)] for i in range(max(0, len(b) - len(needle) + 1))))
            if hit:
                f["consensus"].setdefault("split", []).append(
                    {"reading": c["key"], "votes": c["votes"], "runs": c["runs"]})
                flagged += 1
    return flagged


# 문서 전체 낱말 다수결로 대표 실행의 소수 판독을 고친다.
# 근거: 원문 낱말 빈도 — 밑선 C1·C4·G3·G4 (4/6), 밀선 C2·C3 (2/6). 대표 실행 C2 가 소수 쪽이다
TOKEN_FIX = {"밀선": "밑선"}


def fix_tokens(facts):
    fixed = 0
    for f in facts:
        before = json.dumps(f, ensure_ascii=False)
        for k in ("value", "original_assertion", "item"):
            if isinstance(f.get(k), str):
                for a, b in TOKEN_FIX.items():
                    f[k] = f[k].replace(a, b)
        for k in ("conditions", "exceptions"):
            vals = [str(c) for c in f.get(k) or []]
            for a, b in TOKEN_FIX.items():
                vals = [v.replace(a, b) for v in vals]
            f[k] = vals
        if json.dumps(f, ensure_ascii=False) != before:
            f["consensus"]["corrected"] = [f"{a}→{b} (문서 전체 낱말 다수결 4/6)" for a, b in TOKEN_FIX.items()]
            fixed += 1
    return fixed


def write(source_key, fname, prefix, facts, contested, runs, quorum, sizes):
    split = mark_splits(facts, contested)
    fixed = fix_tokens(facts) if source_key == "a-scan-recipebook" else 0
    src = BASE / "sources" / "scan" / fname
    contested.sort(key=lambda c: (str(c["row"]).zfill(4), -c["votes"]))
    doc = {
        "meta": {
            "source_key": source_key,
            "source_sha256": sha(src),
            "model": "consensus of " + ", ".join(RUN_LABEL[r] for r in runs),
            "extracted_at": f"{TODAY[:4]}-{TODAY[4:6]}-{TODAY[6:]}",
            "method": (f"외부 앱 실행 {len(runs)}개의 결과를 칸 단위 키(메뉴 번호·칸·정규화 값/단위)로 투표, "
                       f"{quorum}/{len(runs)} 이상만 채택. 대표 레코드 우선순위 {PRIORITY}"),
            "status": "REFERENCE — 사람 검토 전. 정답지가 아니다",
            "quorum": f"{quorum}/{len(runs)}",
            "facts_per_run": sizes,
            "agreed": len(facts),
            "contested": len(contested),
            "split_flagged": split,
            "token_corrections": {"rules": TOKEN_FIX, "facts": fixed} if fixed else None,
            "notes": [
                "일치는 정답 보장이 아니다 — 모든 실행이 같은 칸을 같게 잘못 읽을 수 있다",
                "같은 생성 계열(외부 강한 모델)끼리의 일치다. 독립 판정이 아니다",
                "단위 철자(P/펌프, 래들/레들, ℃/°C)는 투표 키에서만 맞췄고 레코드 값은 대표 실행 원문이다",
                "consensus.split 이 있는 사실은 다른 판독이 2표 이상 있었다 — 정답지 승격 전 사람이 원본과 대조",
                "consensus.row 는 판매가 순서로 매긴 메뉴 번호(1~101) , '각주'(표 밖 각주 전체), 또는 '행:' + 대상명(basestock)",
            ],
        },
        "results": facts,
        "contested": contested,
    }
    out = BASE / "reference" / f"{source_key}__consensus{len(runs)}__{TODAY}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    print(out.name, "agreed", len(facts), "contested", len(contested), "split", split, sizes)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="출력 파일명 날짜 YYYYMMDD (기본 오늘)")
    a = ap.parse_args()
    if a.date:
        TODAY = a.date
    main()
