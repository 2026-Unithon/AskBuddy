"""회원·세션에 귀속된 사용자 원문만 문맥으로 사용한다. 과거 답은 지식이 아니다."""
from dataclasses import dataclass
from app.errors import ApiError
from app.learn.question_contexts import _lock_session


@dataclass(frozen=True)
class DialogueHistory:
    receipt_ids: tuple[int, ...] = ()
    user_turns: tuple[str, ...] = ()
    failed_turn_ids: tuple[int,...] = ()
    failed_head: int = 0

    @property
    def head(self) -> int:
        return self.receipt_ids[-1] if self.receipt_ids else 0


async def load_history(conn, *, store_id: int, member_id: int, session_id: int,
                       include_failed:bool=False,exclude_request_id:str|None=None) -> DialogueHistory:
    # 호출자는 짧은 트랜잭션에서 읽고 모델 호출 전에 잠금을 해제한다.
    await _lock_session(conn, store_id=store_id, member_id=member_id, session_id=session_id)
    rows = await conn.fetch("""select receipt_id, original_question, created_at from r_answer_receipts
        where store_id=$1 and member_id=$2 and session_id=$3
        order by receipt_id desc limit 10""", store_id, member_id, session_id)
    rows = tuple(reversed(rows))
    if include_failed:
        from app.learn.failed_user_turns import failed_turns
        failures=await failed_turns(conn,store_id=store_id,member_id=member_id,session_id=session_id,exclude_request_id=exclude_request_id)
        merged=[(r['created_at'],0,r['receipt_id'],r['original_question']) for r in rows]
        merged.extend((r['created_at'],1,r['failed_turn_id'],r['question']) for r in failures)
        merged=sorted(merged)[-10:]
        return DialogueHistory(tuple(r['receipt_id'] for r in rows),tuple(r[3] for r in merged),
            tuple(r[2] for r in merged if r[1]==1),failures[0]['failed_turn_id'] if failures else 0)
    return DialogueHistory(tuple(row['receipt_id'] for row in rows),
                           tuple(row['original_question'] for row in rows))


async def validate_history_head(conn, *, store_id: int, member_id: int, session_id: int,
                                expected_head: int):
    """save_answer의 세션 잠금 안에서 재확인한다. 재전송 receipt는 이 검사보다 먼저 반환한다."""
    head = await conn.fetchval("""select coalesce(max(receipt_id),0) from r_answer_receipts
        where store_id=$1 and member_id=$2 and session_id=$3""", store_id, member_id, session_id)
    if type(expected_head) is not int or expected_head < 0 or head != expected_head:
        raise ApiError(409, 'STALE_DIALOGUE', '대화가 변경됐습니다. 최신 대화를 확인한 뒤 다시 질문해 주세요.', retryable=True)


def retrieval_question(question: str, history: DialogueHistory) -> str:
    """최신 질문 우선. 검색 힌트에만 원문을 더하고 현재 질문·확정 슬롯은 덮어쓰지 않는다."""
    if not history.user_turns:
        return question
    return question + '\n이전 사용자 질문:\n' + '\n'.join(history.user_turns[-3:])
