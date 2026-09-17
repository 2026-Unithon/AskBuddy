"""격리 v2 API 다회 대화 수집. 서버가 발급한 문맥/버전만 다음 선택에 사용한다."""
import asyncio
from time import perf_counter
from uuid import uuid4
from pathlib import Path

from pydantic import Field, model_validator

from app.contracts.chat import ChatResponse
from app.contracts.common import Contract
from app.contracts.hashing import digest
from app.team.v2_evaluation import Action


class DialogueTurn(Contract):
    turn_id: str = Field(min_length=1)
    question: str = Field(min_length=1,max_length=1000)
    expected_action: Action
    option: str | None = None


class DialogueCase(Contract):
    case_id: str = Field(min_length=1)
    turns: tuple[DialogueTurn,...] = Field(min_length=1,max_length=20)

    @model_validator(mode='after')
    def distinct(self):
        if not self.case_id.strip() or any(not t.turn_id.strip() or not t.question.strip() for t in self.turns):
            raise ValueError('nonempty case/turn/question required')
        if len({t.turn_id for t in self.turns})!=len(self.turns): raise ValueError('duplicate turn')
        if self.turns[0].option is not None: raise ValueError('first turn has no server context')
        return self


async def collect_dialogue(client,case,*,headers,expected_snapshot,provider_mode,configuration,timeout_seconds=5):
    case=DialogueCase.model_validate(case)
    if set(expected_snapshot)!={'snapshot_id','knowledge_revision'}:
        raise ValueError('expected snapshot ID/revision required')
    if type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=60:
        raise ValueError('bounded timeout required')
    if provider_mode not in ('SYNTHETIC','LIVE') or not isinstance(configuration,dict):
        raise ValueError('provider mode and evaluation configuration required')
    root=Path(__file__).resolve().parents[1]
    files=('team/dialogue_evaluation.py','learn/v2_router.py','learn/planner.py','learn/semantic_grouping.py','learn/conditional_scope.py','learn/answer_storage.py',
        'learn/raw_quantity.py','learn/answer_validation.py','reg/hybrid.py','reg/reranker.py','team/evaluation_usage.py','learn/numeric_scope.py')
    sources={name:digest((root/name).read_text(encoding='utf-8')) for name in files}
    run_id=uuid4().hex
    rows=[]
    previous=None
    context_revision=None
    session_id=None
    broken=False
    for i,turn in enumerate(case.turns):
        row=dict(turn_id=turn.turn_id,expected_action=turn.expected_action,
            status='NOT_RUN',actual_action=None,response=None,receipt_id=None,error_code=None)
        start=perf_counter()
        if not broken:
            try:
                async with asyncio.timeout(timeout_seconds):
                    if session_id is None:
                        session=await client.post('/learn/v2/sessions',headers=headers,json=dict(request_id=run_id+'-session'))
                        if session.status_code!=200: raise ValueError('SESSION_HTTP_ERROR')
                        session_id=session.json()['session_id']
                        if not isinstance(session_id,str) or not session_id.isdecimal():raise ValueError('INVALID_SESSION')
                    request_id=f'{run_id}-{i}'
                    body=dict(session_id=session_id,request_id=request_id,question=turn.question)
                    if turn.option is not None:
                        if (previous is None or previous.action!='CLARIFY' or not context_revision
                                or turn.option not in previous.allowed_options):raise ValueError('UNAVAILABLE_CONTEXT_OPTION')
                        body.update(context_id=str(previous.context_id),context_revision=context_revision,option=turn.option)
                    response=await client.post('/learn/v2/chat',headers=headers,json=body)
                    if response.status_code!=200:
                        row.update(status='API_ERROR',actual_action='ERROR',error_code=f'HTTP_{response.status_code}')
                        broken=True
                    else:
                        parsed=ChatResponse.model_validate(response.json())
                        receipt=response.headers.get('x-answer-receipt-id')
                        if parsed.request_id!=request_id or not receipt or not receipt.isdecimal():raise ValueError('INVALID_RECEIPT')
                        if any(getattr(parsed,k)!=v for k,v in expected_snapshot.items()):raise ValueError('SNAPSHOT_MISMATCH')
                        rev=response.headers.get('x-context-revision')
                        if parsed.action=='CLARIFY' and (not rev or not rev.isdecimal() or int(rev)<1):
                            raise ValueError('INVALID_CONTEXT_REVISION')
                        previous=parsed
                        context_revision=int(rev) if parsed.action=='CLARIFY' else None
                        row.update(status='RECORDED',actual_action=parsed.action,response=parsed.model_dump(mode='json'),receipt_id=receipt)
            except TimeoutError:
                row.update(status='TRANSPORT_ERROR',actual_action='ERROR',error_code='TimeoutError')
                broken=True
            except Exception as exc:
                # 인증/예외 원문은 산출물에 넣지 않는다. 취소는 상위로 전달된다.
                row.update(status='COLLECTION_ERROR',actual_action='ERROR',error_code=type(exc).__name__)
                broken=True
        row['elapsed_ms']=round((perf_counter()-start)*1000,3)
        rows.append(dict(row,row_hash=digest(row)))
    result=dict(schema_version='r_dialogue_run/v1',run_id=run_id,case=case.model_dump(mode='json'),
        case_hash=digest(case.model_dump(mode='json')),provider_mode=provider_mode,
        configuration=configuration,configuration_hash=digest(configuration),source_hashes=sources,
        source_unchanged=all(value==digest((root/name).read_text(encoding='utf-8')) for name,value in sources.items()),
        expected_snapshot=expected_snapshot,rows=rows,scope='ISOLATED_MULTI_TURN_HTTP',
        recorded_turns=sum(r['status']=='RECORDED' for r in rows),planned_turns=len(rows),
        action_sequence_matches=all(r['actual_action']==r['expected_action'] for r in rows),
        semantic_completion=None,cost_status='UNKNOWN',production_promotion=False)
    return dict(result,run_hash=digest(result))
