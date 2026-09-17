"""M3 서버 문맥 저장. 호출자는 답변/멱등 receipt와 같은 transaction에서 호출한다.

공개 HTTP/모델 입력에 이 내부 함수를 그대로 노출하지 않는다. confirmed_slots는
사용자 명시 선택을 해석한 서버 결과이고 proposed_slots는 검색용 추정이다.
DB 연결이나 잠금을 보유한 상태로 외부 모델을 호출하지 않는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.contracts.chat import QuestionContext
from app.errors import ApiError


class ClarificationLimit(ValueError):
    """호출자가 UNRESOLVED_CONTEXT ESCALATE를 원자 저장해야 한다."""


@dataclass(frozen=True)
class StoredContext:
    context: QuestionContext
    state_revision: int
    knowledge_revision: int
    offered_slot: str | None
    offered_options: tuple[str, ...]


def _transaction(conn):
    if not conn.is_in_transaction():
        raise RuntimeError("question context requires caller transaction")


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _decode(row) -> StoredContext:
    return StoredContext(
        QuestionContext(context_id=row["context_id"], store_id=str(row["store_id"]),
            member_id=str(row["member_id"]), chat_session_id=str(row["chat_session_id"]),
            contract_version=row["contract_version"], expires_at=row["expires_at"],
            original_question=row["original_question"], clarify_turns=row["clarify_turns"],
            confirmed_slots=_json(row["confirmed_slots"]), proposed_slots=_json(row["proposed_slots"])),
        row["state_revision"], row["knowledge_revision"], row["offered_slot"],
        tuple(_json(row["offered_options"])))


def _offer(slot: str, options: tuple[str, ...]):
    if (not isinstance(slot, str) or not 1 <= len(slot) <= 60 or not slot.strip()
            or not 1 <= len(options) <= 10
            or any(not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in options)
            or len(set(options)) != len(options)):
        raise ApiError(422, "INVALID_CONTRACT", "되묻기 슬롯과 선택지를 확인해 주세요.")


def _revision(value: int):
    if type(value) is not int or not 0 <= value <= 9223372036854775807:
        raise ApiError(422, "INVALID_CONTRACT", "올바른 공개 판 번호가 필요합니다.")


async def _lock_session(conn, *, store_id: int, member_id: int, session_id: int):
    # 회원 삭제와 session 전환을 막는다. 매장/회원/session은 trusted scope에서 온다.
    row = await conn.fetchrow("""
        select s.session_id from chat_sessions s
        join store_members m on m.member_id=s.member_id and m.store_id=s.store_id
        where s.store_id=$1 and s.member_id=$2 and s.session_id=$3
          and s.contract_version='v2'
        for no key update of s for share of m
        """, store_id, member_id, session_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "대화를 찾을 수 없습니다.")


async def create_context(conn, *, store_id: int, member_id: int, session_id: int,
                         original_question: str, confirmed_slots: dict[str, str],
                         proposed_slots: dict[str, str], knowledge_revision: int,
                         slot: str, options: tuple[str, ...], issued_context_id: UUID | None = None) -> StoredContext:
    _transaction(conn)
    _offer(slot, options)
    _revision(knowledge_revision)
    if slot in confirmed_slots:
        raise ApiError(422, "INVALID_CONTRACT", "이미 확정한 슬롯을 다시 묻지 않습니다.")
    await _lock_session(conn, store_id=store_id, member_id=member_id, session_id=session_id)
    now = await conn.fetchval("select clock_timestamp()")
    # issued_context_id는 서버 planner가 미리 발급한 ID다. HTTP/모델에서 가져오지 않는다.
    context = QuestionContext(context_id=issued_context_id or uuid4(), store_id=str(store_id), member_id=str(member_id),
        chat_session_id=str(session_id), contract_version="v2", expires_at=now+timedelta(minutes=10),
        original_question=original_question, confirmed_slots=confirmed_slots,
        proposed_slots=proposed_slots, clarify_turns=1)
    row = await conn.fetchrow("""
        insert into r_question_contexts(context_id,store_id,member_id,chat_session_id,
          original_question,confirmed_slots,proposed_slots,knowledge_revision,
          clarify_turns,offered_slot,offered_options,expires_at)
        values($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,1,$9,$10::jsonb,$11) returning *
        """, context.context_id, store_id, member_id, session_id, context.original_question,
        json.dumps(context.confirmed_slots), json.dumps(context.proposed_slots), knowledge_revision,
        slot, json.dumps(options), context.expires_at)
    return _decode(row)


async def load_context(conn, *, store_id: int, member_id: int, session_id: int,
                       context_id: UUID) -> StoredContext:
    """소유권→만료 순서. GET/실패/재시도로 TTL을 연장하지 않는다."""
    _transaction(conn)
    await _lock_session(conn, store_id=store_id, member_id=member_id, session_id=session_id)
    row = await conn.fetchrow("""
        select * from r_question_contexts where store_id=$1 and member_id=$2
          and chat_session_id=$3 and context_id=$4 for update
        """, store_id, member_id, session_id, context_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "문맥을 찾을 수 없습니다.")
    now = await conn.fetchval("select clock_timestamp()")
    if row["expires_at"] <= now:
        raise ApiError(410, "CONTEXT_EXPIRED", "문맥이 만료됐습니다. 원래 질문을 다시 입력해 주세요.")
    return _decode(row)


def accept_selection(stored: StoredContext, *, option: str, expected_state_revision: int,
                     knowledge_revision: int, now: datetime) -> StoredContext:
    """사용자 선택만 확정한다. 같은 offer를 두 번 소비하거나 임의 값을 넣지 못한다."""
    _revision(knowledge_revision)
    if stored.context.expires_at <= now:
        raise ApiError(410, "CONTEXT_EXPIRED", "문맥이 만료됐습니다. 원래 질문을 다시 입력해 주세요.")
    if knowledge_revision < stored.knowledge_revision:
        raise ApiError(409, "STALE_KNOWLEDGE", "공개 내용이 변경됐습니다. 다시 확인해 주세요.", retryable=True)
    if stored.state_revision != expected_state_revision:
        raise ApiError(422, "INVALID_CONTRACT", "문맥이 변경됐습니다. 현재 선택지를 확인해 주세요.")
    if stored.offered_slot is None or option not in stored.offered_options:
        raise ApiError(422, "INVALID_CONTRACT", "현재 제시된 선택지에서 골라 주세요.")
    confirmed = dict(stored.context.confirmed_slots)
    confirmed[stored.offered_slot] = option
    proposed = (dict(stored.context.proposed_slots)
                if knowledge_revision == stored.knowledge_revision else {})
    proposed.pop(stored.offered_slot, None)
    values = stored.context.model_dump()
    values.update(confirmed_slots=confirmed, proposed_slots=proposed,
                  expires_at=now+timedelta(minutes=10))
    return StoredContext(QuestionContext(**values), stored.state_revision+1,
                         knowledge_revision, None, ())


async def accept_context(conn, *, store_id: int, member_id: int, session_id: int,
                         context_id: UUID, expected_state_revision: int,
                         option: str, knowledge_revision: int) -> StoredContext:
    stored = await load_context(conn, store_id=store_id, member_id=member_id,
                                session_id=session_id, context_id=context_id)
    accepted = accept_selection(stored, option=option, expected_state_revision=expected_state_revision,
        knowledge_revision=knowledge_revision, now=await conn.fetchval("select clock_timestamp()"))
    await conn.execute("""
        update r_question_contexts set confirmed_slots=$5::jsonb, proposed_slots=$6::jsonb,
          knowledge_revision=$7, state_revision=$8, offered_slot=null,
          offered_options='[]', expires_at=$9
        where store_id=$1 and member_id=$2 and chat_session_id=$3 and context_id=$4
        """, store_id, member_id, session_id, context_id,
        json.dumps(accepted.context.confirmed_slots), json.dumps(accepted.context.proposed_slots),
        knowledge_revision, accepted.state_revision, accepted.context.expires_at)
    return accepted


async def offer_next_context(conn, *, store_id: int, member_id: int, session_id: int,
                             context_id: UUID, slot: str, options: tuple[str, ...]) -> StoredContext:
    _offer(slot, options)
    stored = await load_context(conn, store_id=store_id, member_id=member_id,
                                session_id=session_id, context_id=context_id)
    if stored.offered_slot is not None or slot in stored.context.confirmed_slots:
        raise ApiError(422, "INVALID_CONTRACT", "수락하지 않은 선택지 또는 이미 확정된 슬롯입니다.")
    if stored.context.clarify_turns >= 2:
        raise ClarificationLimit("UNRESOLVED_CONTEXT")
    row = await conn.fetchrow("""
        update r_question_contexts set offered_slot=$5, offered_options=$6::jsonb,
          clarify_turns=clarify_turns+1, state_revision=state_revision+1
        where store_id=$1 and member_id=$2 and chat_session_id=$3 and context_id=$4 returning *
        """, store_id, member_id, session_id, context_id, slot, json.dumps(options))
    return _decode(row)
