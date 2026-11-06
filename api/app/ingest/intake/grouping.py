"""글 자료 경계 후보 — 코드가 먼저 만든다(B-D3b-1). probe 와 본 추출이 같은 묶음을 쓴다."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from app.ingest.intake.ir import Locator
from app.ingest.preprocess.docx import DocxRead, block_line

_CHAT_HEAD = re.compile(r"^(?:\[#\d+\] )?\[(\d{2}-\d{2}) \d{2}:\d{2}\]")


@dataclass(frozen=True)
class Group:
    candidate_id: str
    locator: Locator
    units: tuple[str, ...]


def even_indices(n: int, k: int) -> list[int]:
    if k >= n:
        return list(range(n))
    if k == 1:
        return [0]
    return sorted({int((n - 1) * i / (k - 1)) for i in range(k)})


def _merge(parts: list[tuple[str, str, tuple[str, ...]]], max_sections: int, kind: str
           ) -> list[Group]:
    """(시작, 끝, 단위들) 목록을 max_sections 개 이하로 고르게 합친다."""
    n = len(parts)
    size, extra = divmod(n, max_sections) if n > max_sections else (1, 0)
    out, i = [], 0
    while i < n:
        take = size + (1 if len(out) < extra else 0)
        chunk = parts[i:i + take]
        out.append(Group(f"c{len(out) + 1}", Locator(kind, chunk[0][0], chunk[-1][1]),
                         tuple(u for _, _, units in chunk for u in units)))
        i += take
    return out


def group_pdf_pages(blocks: Sequence[tuple[int, str]], *, max_sections: int) -> list[Group]:
    return _merge([(str(n), str(n), (b,)) for n, b in blocks], max_sections, "PAGE")


def group_docx(read: DocxRead, *, max_sections: int, min_chars: int) -> list[Group]:
    runs: list[list] = []
    for b in read.blocks:
        new = (not runs or b.kind == "HEADING"
               or (b.kind != "TABLE_ROW" and runs[-1][-1].kind == "TABLE_ROW"))
        if new:
            runs.append([b])
        else:
            runs[-1].append(b)

    def chars(blocks) -> int:
        return sum(len(x.text) for x in blocks)

    # 짧은 구간은 앞 구간에 합친다. 첫 구간이 짧으면 다음 구간 앞에 붙인다
    merged: list[list] = []
    for run in runs:
        if merged and chars(run) < min_chars:
            merged[-1].extend(run)
        else:
            merged.append(list(run))
    if len(merged) > 1 and chars(merged[0]) < min_chars:
        first = merged.pop(0)
        merged[0][:0] = first
    return _merge([(str(r[0].index), str(r[-1].index), tuple(block_line(b) for b in r))
                   for r in merged], max_sections, "LINE")


def group_chat(parsed_text: str, *, max_sections: int) -> list[Group]:
    days: list[tuple[str, list[str]]] = []
    for line in parsed_text.split("\n"):
        m = _CHAT_HEAD.match(line)
        if m and (not days or days[-1][0] != m.group(1)):
            days.append((m.group(1), [line]))
        elif days:
            days[-1][1].append(line)
        else:
            days.append(("", [line]))
    return _merge([(d, d, ("\n".join(lines),)) for d, lines in days], max_sections, "DATE")


def sections_text(groups: Sequence[Group], joiner: str) -> dict[str, str]:
    return {g.candidate_id: joiner.join(g.units) for g in groups}
