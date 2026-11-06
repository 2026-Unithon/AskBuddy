"""입구 분류 판정 기록·점주 답변 첨부 (Phase B).

모든 함수는 store_id 를 두 번째 위치 인자로 받고, SQL 은 store_id 로 좁힌다(D1).
표본 원문은 저장하지 않는다 — 요약과 hash 만 남긴다(B-D6).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Sequence

from app.ingest.intake.classify import ClassifyOutcome
from app.ingest.intake.decide import OVERRIDE_BASES, SectionDecision
from app.ingest.intake.ir import ProbeResult


@dataclass(frozen=True)
class StoredRoute:
    decision_id: int
    normalizer: str
    decisions: list[SectionDecision]
    # decisions 와 함께 저장한 자료 단위 판정(source_decision 열)
    source: SectionDecision


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value):
    # asyncpg 는 jsonb 를 문자열로 돌려준다. 이미 파싱돼 있으면 그대로 쓴다
    return json.loads(value) if isinstance(value, (str, bytes)) else value


async def save_decision(
    conn, store_id: int, *, source_id: int, entry: Literal["UPLOAD", "OWNER_ANSWER"],
    owner_answer_id: int | None, probe: ProbeResult, owner_hints: Sequence[str],
    outcome: ClassifyOutcome | None, decisions: Sequence[SectionDecision],
    source: SectionDecision, logical_call_id: str | None,
) -> int:
    """판정 한 건을 남기고 decision_id 를 돌려준다. outcome=None 은 분류를 부르지 않은 경우."""
    return await conn.fetchval(
        """
        insert into intake_route_decisions (
          store_id, source_id, entry, owner_answer_id, normalizer,
          sample_summary, sample_hash, owner_hints, model, prompt_digest,
          model_sections, decisions, source_decision, source_logic, logical_call_id
        )
        values ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11::jsonb,$12::jsonb,$13::jsonb,$14,$15)
        returning decision_id
        """,
        store_id, source_id, entry, owner_answer_id, probe.normalizer,
        _dumps(probe.summary()), probe.sample_hash(), list(owner_hints) or None,
        outcome.model if outcome else None,
        outcome.prompt_digest if outcome else None,
        _dumps(outcome.raw if outcome else {}),
        _dumps([d.as_dict() for d in decisions]),
        _dumps(source.as_dict()), source.logic, logical_call_id,
    )


# 점주 덮어쓰기 판정의 model 표지 — 개발 기록에서 분류 모델 판정과 가른다(F-I3·후속 1)
OWNER_OVERRIDE_MODEL = "owner-override"


async def save_owner_override(
    conn, store_id: int, *, source_id: int, base: StoredRoute, owner_hints: Sequence[str],
    decisions: Sequence[SectionDecision], source: SectionDecision, basis: str,
) -> int:
    """NONE 판정을 점주 "그래도 추출하기"로 덮은 판정을 새 행으로 남긴다. 분류는 부르지 않는다.

    정규화기·표본 요약·hash 는 덮는 판정(base)에서 그대로 옮긴다 — 다시 훑지 않는다.
    entry 는 UPLOAD, model 은 `owner-override`, model_sections 에 덮은 로직을 고른 근거
    (basis: OWNER_HINT | NEXT_RANKED | REGISTERED_DEFAULT)를 남긴다.
    """
    if basis not in OVERRIDE_BASES:
        raise ValueError(f"덮어쓰기 근거가 아니다: {basis}")
    decision_id = await conn.fetchval(
        """
        insert into intake_route_decisions (
          store_id, source_id, entry, owner_answer_id, normalizer,
          sample_summary, sample_hash, owner_hints, model, prompt_digest,
          model_sections, decisions, source_decision, source_logic, logical_call_id
        )
        select store_id, source_id, 'UPLOAD', null, normalizer,
               sample_summary, sample_hash, $4, $5, null,
               $6::jsonb, $7::jsonb, $8::jsonb, $9, null
          from intake_route_decisions
         where store_id = $1 and source_id = $2 and decision_id = $3
        returning decision_id
        """,
        store_id, source_id, base.decision_id, list(owner_hints) or None,
        OWNER_OVERRIDE_MODEL,
        _dumps({"override": "OWNER_EXTRACT_ANYWAY", "basis": basis,
                "base_decision_id": base.decision_id,
                "base_source_logic": base.source.logic, "logic": source.logic}),
        _dumps([d.as_dict() for d in decisions]), _dumps(source.as_dict()), source.logic,
    )
    if decision_id is None:
        raise LookupError(f"덮을 판정이 없다 (store={store_id}, decision={base.decision_id})")
    return decision_id


async def latest_decision(conn, store_id: int, source_id: int) -> StoredRoute | None:
    """자료의 가장 최근 판정. 없으면 None."""
    row = await conn.fetchrow(
        """
        select decision_id, normalizer, decisions, source_decision
          from intake_route_decisions
         where store_id = $1 and source_id = $2
         order by decision_id desc
         limit 1
        """,
        store_id, source_id,
    )
    if row is None:
        return None
    return StoredRoute(
        row["decision_id"], row["normalizer"],
        [SectionDecision.from_dict(d) for d in _loads(row["decisions"])],
        SectionDecision.from_dict(_loads(row["source_decision"])),
    )


async def source_owner_hints(conn, store_id: int, source_id: int) -> tuple[str, ...]:
    """점주가 고른 로직 칩. 없으면 빈 튜플."""
    value = await conn.fetchval(
        "select owner_hints from sources where store_id = $1 and source_id = $2",
        store_id, source_id,
    )
    return tuple(value or ())


async def attach(conn, store_id: int, *, pending_question_id: int, source_id: int) -> bool:
    """자료를 대기 질문에 붙인다. 새로 붙였으면 True, 이미 붙어 있으면 False."""
    got = await conn.fetchval(
        """
        insert into owner_answer_attachments (store_id, pending_question_id, source_id)
        values ($1, $2, $3)
        on conflict (store_id, source_id) do nothing
        returning source_id
        """,
        store_id, pending_question_id, source_id,
    )
    return got is not None


async def attachments_for_question(conn, store_id: int, pending_question_id: int) -> list[int]:
    rows = await conn.fetch(
        """
        select source_id from owner_answer_attachments
         where store_id = $1 and pending_question_id = $2
         order by source_id
        """,
        store_id, pending_question_id,
    )
    return [r["source_id"] for r in rows]
