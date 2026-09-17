"""격리 평가용 v2 HTTP 수집과 출력에 고정된 사람 판정 보고. 제품 라우트에서 호출하지 않는다."""
from __future__ import annotations

import asyncio
import httpx
import re
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4

from pydantic import Field, StrictBool, model_validator

from app.contracts.common import Contract, EntityId, RevisionId
from app.contracts.chat import ChatResponse
from app.contracts.hashing import digest
from app.team.answer_metrics import question_metrics

Action = Literal['ANSWER','CLARIFY','ESCALATE','REFUSE','SAFE_ROUTE']


class RequiredRawBlock(Contract):
    card_id:EntityId
    card_version_id:EntityId
    block_id:str=Field(min_length=1)
    raw_span_id:EntityId


class EvaluationCase(Contract):
    question_id:str=Field(min_length=1,max_length=100)
    question:str=Field(min_length=1,max_length=1000)
    expected_action:Action
    must_have:StrictBool
    required_facts:tuple[str,...]
    forbidden_claims:tuple[str,...]
    required_raw_blocks:tuple[RequiredRawBlock,...]=()

    @model_validator(mode='after')
    def unique_raw(self):
        if len({tuple(b.model_dump().values()) for b in self.required_raw_blocks})!=len(self.required_raw_blocks):
            raise ValueError('duplicate required RAW reference')
        return self


class EvaluationManifest(Contract):
    schema_version:Literal['r_v2_manifest/v1']='r_v2_manifest/v1'
    truth_kind:Literal['SYNTHETIC','HUMAN_REVIEWED']
    truth_version:str=Field(min_length=1)
    snapshot_id:EntityId
    knowledge_revision:RevisionId
    snapshot_hash:str=Field(pattern=r'^sha256:[0-9a-f]{64}$')
    cases:tuple[EvaluationCase,...]=Field(min_length=1)

    @model_validator(mode='after')
    def unique_questions(self):
        if len({c.question_id for c in self.cases})!=len(self.cases):
            raise ValueError('duplicate question ID')
        if any(not c.question.strip() or not c.question_id.strip() for c in self.cases):
            raise ValueError('empty question or ID')
        return self


class Judgment(Contract):
    question_id:str
    row_hash:str
    reviewer:str=Field(min_length=1)
    reason:str=Field(min_length=1)
    semantic_correct:StrictBool|None=None
    knowledge_block:StrictBool|None=None
    block_correct:StrictBool|None=None
    action_correct:StrictBool|None=None

    @model_validator(mode='after')
    def review_evidence(self):
        if not self.reviewer.strip() or not self.reason.strip():raise ValueError('review evidence required')
        if self.block_correct is not None and self.knowledge_block is not True:
            raise ValueError('block correctness requires classified knowledge block')
        return self


def _hashed(payload,field):
    return dict(payload,**{field:digest(payload)})


def _error_code(response,fallback):
    try:
        code=response.json()['error']['code']
        return code if isinstance(code,str) and re.fullmatch(r'[A-Z_]{1,80}',code) else fallback
    except (ValueError,KeyError,TypeError):return fallback


async def collect_v2_run(client,manifest:EvaluationManifest,*,headers:dict,configuration:dict,
                         provider_mode:Literal['SYNTHETIC','LIVE'],timeout_seconds:float=5) -> dict:
    """client는 호출자가 격리 API에 연결한다. 세션/문의 생성이 있으므로 운영에서 실행하지 않는다.

    자동 재시도/실패 행 삭제 없음. LIVE 실행 권한과 원가 귀속은 호출자가 별도 준비한다.
    manifest snapshot hash는 사전 입력이며 응답의 ID/revision 대조와 구분한다.
    """
    manifest=EvaluationManifest.model_validate(manifest.model_dump())
    if provider_mode not in ('SYNTHETIC','LIVE') or not 0<timeout_seconds<=60:
        raise ValueError('provider mode and bounded timeout required')
    configuration_hash=digest(configuration)
    root=Path(__file__).resolve().parents[2]
    sources=('app/team/v2_evaluation.py','app/learn/v2_router.py','app/learn/planner.py','app/learn/semantic_grouping.py','app/learn/conditional_scope.py',
             'app/learn/raw_quantity.py','app/learn/answer_storage.py','app/learn/answer_validation.py','app/reg/hybrid.py',
             'app/reg/reranker.py','app/learn/approved_renderer.py','app/team/evaluation_usage.py','app/learn/numeric_scope.py')
    source_hashes={p:digest((root/p).read_text(encoding='utf-8')) for p in sources}
    run_id=uuid4().hex
    rows=[]
    for index,case in enumerate(manifest.cases):
        request_id=f'eval-{run_id}-{index}'
        row=dict(question_id=case.question_id,request_id=request_id,status='TRANSPORT_ERROR',
                 actual_action='ERROR',response=None,receipt_id=None,error_code=None,http_status=None)
        start=perf_counter()
        try:
            async with asyncio.timeout(timeout_seconds):
                session=await client.post('/learn/v2/sessions',headers=headers,json=dict(request_id=request_id+'-s'))
                row['http_status']=session.status_code
                if session.status_code!=200:
                    row.update(status='API_ERROR',error_code=_error_code(session,'SESSION_HTTP_ERROR'))
                else:
                    row['status']='INVALID_RESPONSE'
                    session_id=session.json()['session_id']
                    if not isinstance(session_id,str) or not session_id.isdecimal():raise ValueError('invalid session')
                    row['status']='TRANSPORT_ERROR'
                    response=await client.post('/learn/v2/chat',headers=headers,json=dict(
                        session_id=session_id,request_id=request_id,question=case.question))
                    row['http_status']=response.status_code
                    if response.status_code!=200:
                        row.update(status='API_ERROR',error_code=_error_code(response,'CHAT_HTTP_ERROR'))
                    else:
                        row['status']='INVALID_RESPONSE'
                        row['response']=response.json()
                        parsed=ChatResponse.model_validate(row['response'])
                        receipt=response.headers.get('x-answer-receipt-id')
                        if parsed.request_id!=request_id or not receipt or not receipt.isdecimal():
                            raise ValueError('missing receipt or mismatched request')
                        row['receipt_id']=receipt
                        if (parsed.snapshot_id!=manifest.snapshot_id or parsed.knowledge_revision!=manifest.knowledge_revision):
                            row.update(status='SNAPSHOT_MISMATCH',error_code='SNAPSHOT_MISMATCH')
                        else:row.update(status='RECORDED',actual_action=parsed.action)
        except (TimeoutError,httpx.TransportError) as exc:
            row.update(status='TRANSPORT_ERROR',actual_action='ERROR',error_code=type(exc).__name__)
        except Exception as exc:
            # 예외 본문/인증 헤더를 산출물에 복제하지 않는다. 취소는 상위로 전파한다.
            row.update(status='INVALID_RESPONSE',actual_action='ERROR',error_code=type(exc).__name__)
        row['elapsed_ms']=round((perf_counter()-start)*1000,3)
        rows.append(_hashed(row,'row_hash'))
    return _hashed(dict(schema_version='r_v2_run/v1',run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),scope='ISOLATED_SINGLE_TURN_HTTP',
        provider_mode=provider_mode,manifest=manifest.model_dump(mode='json'),
        manifest_hash=digest(manifest.model_dump(mode='json')),configuration=configuration,
        configuration_hash=configuration_hash,cost_status='UNKNOWN',
        source_hashes=source_hashes,source_unchanged=all(source_hashes[p]==digest((root/p).read_text(encoding='utf-8')) for p in sources),rows=rows),'run_hash')


def build_v2_report(run:dict,judgments:list[dict]|None=None) -> dict:
    """행 hash는 오연결 검출용이지 검토자 인증/전자 서명이 아니다."""
    if run.get('schema_version')!='r_v2_run/v1' or run.get('run_hash')!=digest({k:v for k,v in run.items() if k!='run_hash'}):
        raise ValueError('run hash mismatch')
    if run.get('source_unchanged') is not True:raise ValueError('source changed during collection')
    manifest=EvaluationManifest.model_validate(run['manifest'])
    # Preserve the exact frozen bytes/fields of older v1 manifests: optional
    # RAW defaults added by validation must not invalidate an existing run.
    if run['manifest_hash']!=digest(run['manifest']):raise ValueError('manifest mismatch')
    expected={c.question_id:c for c in manifest.cases}
    rows=run['rows']
    if len(rows)!=len(expected) or {r['question_id'] for r in rows}!=set(expected):raise ValueError('question denominator changed')
    labels={}
    for raw in judgments or []:
        label=Judgment.model_validate(raw)
        if label.question_id in labels or label.question_id not in expected:raise ValueError('duplicate or foreign judgment')
        labels[label.question_id]=label
    scored=[]
    paired={}
    for row in rows:
        if row['row_hash']!=digest({k:v for k,v in row.items() if k!='row_hash'}):raise ValueError('row hash mismatch')
        case=expected[row['question_id']]
        label=labels.get(case.question_id)
        if label and label.row_hash!=row['row_hash']:raise ValueError('judgment belongs to another output')
        action=row['actual_action']
        if row['status'] not in ('RECORDED','API_ERROR','TRANSPORT_ERROR','INVALID_RESPONSE','SNAPSHOT_MISMATCH'):
            raise ValueError('unknown collection status')
        if row['status']=='RECORDED':
            response=ChatResponse.model_validate(row['response'])
            if (response.action!=action or response.request_id!=row['request_id']
                    or response.snapshot_id!=manifest.snapshot_id or response.knowledge_revision!=manifest.knowledge_revision
                    or not row['receipt_id']):raise ValueError('recorded response mismatch')
        elif action!='ERROR':raise ValueError('collection error must remain ERROR')
        correct=label.semantic_correct if label else None
        raw_complete=None
        if case.required_raw_blocks and row['status']=='RECORDED':
            cited={(c.card_id,c.card_version_id,c.block_id,c.raw_span_id) for c in response.citations}
            raw_complete=all((b.card_id,b.card_version_id,b.block_id,b.raw_span_id) in cited
                for b in case.required_raw_blocks)
        if correct is not None and (row['status']!='RECORDED' or action!='ANSWER'):
            raise ValueError('semantic answer label requires recorded ANSWER')
        if label and (label.knowledge_block is not None or label.block_correct is not None) and action not in ('CLARIFY','ESCALATE'):
            raise ValueError('block label requires CLARIFY or ESCALATE')
        if label and label.action_correct is not None and row['status']!='RECORDED':
            raise ValueError('action judgment requires recorded response')
        scored.append(dict(question_id=case.question_id,expected_action=case.expected_action,
            actual_action=action,semantic_correct=correct,knowledge_block=label.knowledge_block if label else None,
            block_correct=label.block_correct if label else None,
            action_correct=label.action_correct if label else None,required_raw_cited=raw_complete))
        if case.expected_action=='ANSWER':
            paired[case.question_id]=(None if row['status'] in ('INVALID_RESPONSE','SNAPSHOT_MISMATCH') else
                (False if raw_complete is False else correct) if action=='ANSWER' else False)
    unjudged=[key for key,value in paired.items() if value is None]
    successes=sum(value is True for value in paired.values())
    return dict(schema_version='r_v2_report/v2',run_hash=run['run_hash'],manifest_hash=run['manifest_hash'],
        metrics=question_metrics(scored),question_count=len(rows),
        grounded_answer_count=successes,answerable_count=len(paired),unjudged_answer_ids=unjudged,
        grounded_answer_rate=successes/len(paired) if paired and not unjudged else None,
        paired_gate_input=paired,must_have_answer_ids=[c.question_id for c in manifest.cases if c.must_have and c.expected_action=='ANSWER'],
        judgments=[j.model_dump(mode='json') for j in labels.values()],rows=scored,
        cost_status='UNKNOWN',production_promotion=False)
