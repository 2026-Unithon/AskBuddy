"""실제 DB 검증용 입구 분류(Phase B) 대역. 유료 호출 없음.

Phase B 부터 process_source 는 `_preprocess` 앞에서 자료를 훑고 분류한다(원본 다운로드 포함).
`_preprocess` 를 대역으로 바꾼 기존 검증은 원본이 없으므로, 훑기는 자료 전체 후보 하나로,
분류는 정해 둔 로직(기본 RECIPE)으로 둔다. 판정 저장·재사용은 진짜 코드가 돈다.
"""
from __future__ import annotations

import re

from app.ingest.intake import classify as intake_classify
from app.ingest.intake import route as intake_route
from app.ingest.intake.ir import Candidate, Locator, ProbeResult

_NORMALIZER = {"SCAN": "DOC_TEXT", "KAKAO": "CHAT", "VOICE": "AUDIO", "VIDEO": "VIDEO",
               "OWNER_TEXT": "OWNER_TEXT"}


def intake_patches(counts: dict | None = None, *, logic: str = "RECIPE") -> list[tuple]:
    """(대상, 이름, 대역) 목록. counts 를 주면 counts['classify'] 에 분류 호출 수를 센다."""

    async def probe(pool, store_id, src, **kw):
        return ProbeResult(_NORMALIZER.get(src["source_type"], "DOC_TEXT"),
                           (Candidate("c1", Locator("WHOLE", "", ""), "합성"),))

    async def classify(spec, prompt, images, schema, **kw):
        if counts is not None:
            counts["classify"] = counts.get("classify", 0) + 1
        # 후보 id 는 프롬프트의 `### <id> (` 머리에서 읽는다(답변 묶음은 `s{자료}:c1`)
        ids = re.findall(r"^### (\S+) \(", prompt, flags=re.M)
        return schema.model_validate({"sections": [
            {"candidate_id": cid, "ranking": [{"logic": logic, "score": 0.9}]} for cid in ids]})

    return [(intake_route, "probe_source", probe),
            (intake_classify, "measured_generate", classify)]


def intake_context(counts: dict | None = None, *, logic: str = "RECIPE"):
    """intake_patches 를 한 번에 여는 context manager."""
    from contextlib import ExitStack
    from unittest.mock import patch

    stack = ExitStack()
    for obj, name, replacement in intake_patches(counts, logic=logic):
        stack.enter_context(patch.object(obj, name, replacement))
    return stack
