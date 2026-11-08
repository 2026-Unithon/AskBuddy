"""같은 직원 세션의 대화 순서. 과거 응답은 현재 승인 지식이 아니다."""
from dataclasses import dataclass
import json
import re
from app.errors import ApiError
from app.learn.question_contexts import _lock_session


@dataclass(frozen=True)
class ReplyFrame:
    """A previous question/offer or cited subject, never past factual answer text."""
    turn_id: int
    action: str
    prompt: str = ''
    slot: str = ''
    options: tuple[str, ...] = ()
    cited_versions: tuple[tuple[str,str], ...] = ()


@dataclass(frozen=True)
class DialogueHistory:
    receipt_ids: tuple[int, ...] = ()
    user_turns: tuple[str, ...] = ()
    failed_turn_ids: tuple[int,...] = ()
    failed_head: int = 0
    replies: tuple[ReplyFrame, ...] = ()

    @property
    def head(self) -> int:
        return self.receipt_ids[-1] if self.receipt_ids else 0


async def load_history(conn, *, store_id: int, member_id: int, session_id: int,
                       include_failed:bool=False,exclude_request_id:str|None=None) -> DialogueHistory:
    # 호출자는 짧은 트랜잭션에서 읽고 모델 호출 전에 잠금을 해제한다.
    await _lock_session(conn, store_id=store_id, member_id=member_id, session_id=session_id)
    rows = await conn.fetch("""select receipt_id, original_question, created_at,
        response->>'action' as action,
        case when response->>'action'='CLARIFY' then response->>'message' end as prompt,
        response->>'clarification_slot' as slot, response->'allowed_options' as options,
        (select jsonb_agg(jsonb_build_array(c->>'card_id',c->>'card_version_id') order by n)
         from jsonb_array_elements(response->'citations') with ordinality as refs(c,n)) as cited
        from r_answer_receipts
        where store_id=$1 and member_id=$2 and session_id=$3
        order by receipt_id desc limit 10""", store_id, member_id, session_id)
    rows = tuple(reversed(rows))
    failures=()
    if include_failed:
        from app.learn.failed_user_turns import failed_turns
        failures=await failed_turns(conn,store_id=store_id,member_id=member_id,session_id=session_id,exclude_request_id=exclude_request_id)
    merged=[(r['created_at'],0,r['receipt_id'],r['original_question'],r) for r in rows]
    merged.extend((r['created_at'],1,r['failed_turn_id'],r['question'],{}) for r in failures)
    merged=sorted(merged,key=lambda item:item[:3])[-10:]
    def array(value):
        return json.loads(value) if isinstance(value,str) else value or ()
    frames=tuple(ReplyFrame(i,r['action'],r.get('prompt') or '',r.get('slot') or '',
            tuple(array(r.get('options'))),tuple(dict.fromkeys(tuple(pair) for pair in array(r.get('cited')))))
        for i,(*_,r) in enumerate(merged) if r.get('action'))
    return DialogueHistory(tuple(r['receipt_id'] for r in rows),tuple(item[3] for item in merged),
        tuple(item[2] for item in merged if item[1]),failures[0]['failed_turn_id'] if failures else 0,frames)


def reply_context(history, snapshot):
    current={(c.card_id,c.card_version_id):c.title for c in snapshot.cards}
    return [dict(after_user_turn=r.turn_id,action=r.action,
        **(dict(prompt=r.prompt,asked_for=r.slot,displayed_options=list(r.options)) if r.slot else {}),
        **(dict(cited_subjects=list(dict.fromkeys(current[p] for p in r.cited_versions if p in current))) if r.cited_versions else {}))
        for r in history.replies]


def _mentions(text, titles):
    found=[]
    for title in titles:
        match=re.search(r'(?<!\w)'+re.escape(title)+r'(?:랑|하고|만|와|과|을|를|의|에|은|는|이|가)?(?!\w)',text,re.I)
        if match:found.append((match.start(),-len(title),title))
    return [t for _,_,t in sorted(found)]


def followup_subjects(question,history,snapshot):
    """Narrow an otherwise unrelated fallback only for explicit user references."""
    titles=tuple(dict.fromkeys(c.title.strip() for c in snapshot.cards if c.title.strip()))
    if not history.user_turns or _mentions(question,titles):return ()
    ordinal=re.search(r'(첫|두|세)\s*번째\s*(?:음료|메뉴|상품|장비|제품|도구|대상|것)',question)
    relative=re.match(r'\s*(?:그거|그건|그걸|그것|둘\s*중|그중|어디에?\s*보관)',question)
    if not ordinal and not relative:return ()
    # Do not skip intervening unrelated turns to resurrect an old subject.
    prior=history.user_turns[-1]
    names=_mentions(prior,titles)
    if not names:return ()
    if ordinal:
        # Only resolve an explicitly enumerated list of approved subjects. A
        # missing/unknown item would shift every ordinal that follows it.
        if len(names)<2 or len(names)!=len(set(names)):return ()
        join=r'\s*(?:랑|이랑|하고|와|과|,|및)\s*'
        sequence=join.join(re.escape(n) for n in names)
        if not re.fullmatch(r'\s*'+sequence+r'(?:(?:을|를|은|는|이|가)\s+.*|[.!? ]*)',prior,re.I):return ()
        idx={'첫':0,'두':1,'세':2}[ordinal[1]]
        return (names[idx],) if len(names)>idx else ()
    return tuple(names)


def scoped_fallback(decision,question,history,snapshot):
    """Preserve the referent on a miss; grounding still requires current knowledge."""
    from dataclasses import replace
    from app.contracts.answer import AnswerPlan
    from uuid import uuid4
    if decision.plan.action!='ESCALATE' and not (
            decision.plan.action=='CLARIFY' and decision.plan.clarification_slot=='entity'):return decision
    names=followup_subjects(question,history,snapshot)
    if not names:return decision
    base=dict(snapshot_id=snapshot.snapshot_id,knowledge_revision=snapshot.knowledge_revision)
    if len(names)==1:
        ids={c.entity_id for c in snapshot.cards if c.title==names[0]}
        if len(ids)!=1:return decision
        return replace(decision,plan=AnswerPlan(**base,action='ESCALATE',escalation_reason='DIALOGUE_SUBJECT_UNRESOLVED'),
            resolved=replace(decision.resolved,entity_id=ids.pop()),semantic_context=None)
    if len(names)<=10:
        return replace(decision,plan=AnswerPlan(**base,action='CLARIFY',clarification_slot='entity',
            context_id=uuid4(),allowed_options=names),semantic_context=None)
    return decision


async def validate_history_head(conn, *, store_id: int, member_id: int, session_id: int,
                                expected_head: int):
    """save_answer의 세션 잠금 안에서 재확인한다. 재전송 receipt는 이 검사보다 먼저 반환한다."""
    head = await conn.fetchval("""select coalesce(max(receipt_id),0) from r_answer_receipts
        where store_id=$1 and member_id=$2 and session_id=$3""", store_id, member_id, session_id)
    if type(expected_head) is not int or expected_head < 0 or head != expected_head:
        raise ApiError(409, 'STALE_DIALOGUE', '대화가 변경됐습니다. 최신 대화를 확인한 뒤 다시 질문해 주세요.', retryable=True)


def retrieval_question(question: str, history: DialogueHistory, *, snapshot=None, continuing_choice=False) -> str:
    """최신 질문 우선. 검색 힌트에만 원문을 더하고 현재 질문·확정 슬롯은 덮어쓰지 않는다."""
    if not history.user_turns:
        return question
    hint=''
    if snapshot is not None:
        # Titles are search hints only. Neither retrieval order nor a past
        # assistant offer confirms an entity, temperature, or other condition.
        titles=tuple(dict.fromkeys(c.title.strip() for c in snapshot.cards if c.title.strip()))
        current_names=_mentions(question,titles)
        refers_back=re.search(r'그럼|그러면|그중|그 중|둘 중|첫 번째|두 번째|앞에서|아까|대신|비교|차이',question)
        if not continuing_choice and (re.match(r'\s*(?:다른 질문|별개로|주제를 바꿔)',question)
                or (current_names and not refers_back and question.strip(' .!?') not in current_names)):
            return question
        frame=next((r for r in reversed(history.replies) if r.turn_id==len(history.user_turns)-1),None)
        if frame:
            if frame.slot:hint='\n직전 확인 질문: '+frame.prompt
            # Only mention current published subjects, not the previous answer or all menu options.
            subjects=reply_context(DialogueHistory(replies=(frame,)),snapshot)[0].get('cited_subjects',[])
            if subjects:hint+='\n직전 답변 대상: '+', '.join(subjects)
        # Keep the user's order even if the previous reply listed different options.
        # Put likely referents early for the lexical search token budget.
        if refers_back:
            for turn in reversed(history.user_turns[-3:]):
                names=_mentions(turn,titles)
                if names:
                    hint='\n직원이 말한 대상 순서: '+', '.join(names)+hint
                    break
            scoped=followup_subjects(question,history,snapshot)
            if len(scoped)==1:hint='\n지칭한 대상: '+scoped[0]+hint
    return question + hint + '\n이전 사용자 질문:\n' + '\n'.join(history.user_turns[-3:])
