"""사장님 수정 지표 (2026-11-07, W_SINGLE_CALL_EXTRACT_DESIGN §4-6) — 순수 집계·서식.

실제 매장 자료의 추출 품질을 정답지 없이 잰다: 사장님이 승인 화면에서 **고친** 사실(OWNER_CORRECTION)은
잘못 뽑힌 신호, 그 자료의 카드에 **새로 더한** 사실(OWNER_ADD)은 놓친 신호다. 원본 내용은 다루지 않고
수만 센다. DB 조회는 `scripts/owner_correction_report.py` 가 한다. 여기서는 DB 를 치지 않는다.

자료별 행: {source_id, source_type, ext, logic, extracted, corrected, added}.
비율의 분모가 0 이면 None 이다 — 못 잰 것을 0% 로 적지 않는다.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal


def format_of(source_type: str, ext: str) -> str:
    """보고용 형식 이름. 같은 정규화 경로끼리 묶는다."""
    ext = (ext or "").lower()
    if source_type == "SCAN":
        return {"pdf": "PDF", "docx": "DOCX", "jpg": "사진", "jpeg": "사진", "png": "사진"}.get(ext, f"SCAN.{ext}")
    if source_type == "KAKAO":
        return "카톡 캡처" if ext in ("jpg", "jpeg", "png") else "카톡 글"
    if source_type == "VOICE":
        return "음성"
    if source_type == "VIDEO":
        return "영상"
    return source_type


def _ratio(part: int, whole: int) -> Decimal | None:
    return (Decimal(part) / Decimal(whole)).quantize(Decimal("0.0001")) if whole else None


def summarize(rows: list[dict]) -> dict:
    """형식별·로직별·전체 — 자료 수, 뽑은 사실, 고친 사실, 더한 사실, 고친 비율, 더한 비율."""
    def empty():
        return {"sources": 0, "extracted": 0, "corrected": 0, "added": 0}

    by_format: dict[str, dict] = defaultdict(empty)
    by_logic: dict[str, dict] = defaultdict(empty)
    total = empty()
    for row in rows:
        keys = (by_format[format_of(row["source_type"], row.get("ext") or "")],
                by_logic[row.get("logic") or "미판정"], total)
        for bucket in keys:
            bucket["sources"] += 1
            for k in ("extracted", "corrected", "added"):
                bucket[k] += int(row.get(k) or 0)

    def finish(bucket: dict) -> dict:
        return {**bucket,
                "corrected_rate": _ratio(bucket["corrected"], bucket["extracted"]),
                # 더한 사실은 뽑은 사실 + 더한 사실(사장님이 본 전체) 대비로 본다 — 놓친 비율의 근사
                "added_rate": _ratio(bucket["added"], bucket["extracted"] + bucket["added"])}

    return {"total": finish(total),
            "by_format": {k: finish(v) for k, v in sorted(by_format.items())},
            "by_logic": {k: finish(v) for k, v in sorted(by_logic.items())}}


def render(summary: dict) -> str:
    def pct(x):
        return "—" if x is None else f"{x * 100:.1f}%"

    def line(name, b):
        return (f"| {name} | {b['sources']} | {b['extracted']} | {b['corrected']} ({pct(b['corrected_rate'])}) "
                f"| {b['added']} ({pct(b['added_rate'])}) |")

    head = "| 묶음 | 자료 | 뽑은 사실 | 사장님이 고침 | 사장님이 더함(놓침 근사) |\n|---|---|---|---|---|"
    out = ["## 전체", head, line("전체", summary["total"]), "", "## 형식별", head]
    out += [line(k, v) for k, v in summary["by_format"].items()]
    out += ["", "## 로직별", head]
    out += [line(k, v) for k, v in summary["by_logic"].items()]
    return "\n".join(out) + "\n"
