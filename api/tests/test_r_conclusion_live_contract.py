"""Actual rejected outputs stay rejected; schema changes never repair model IDs."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.contracts.hashing import digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.errors import ApiError
from app.learn.general_semantics import GeneralProposal, general_decision
from app.learn.general_verification import Verification
from app.learn.general_wire import parse_proposal, response_schema
from app.learn.planner import decide
from app.reg.hybrid import Candidate, SearchResult, normalize_query
from tests.test_r_general_semantics import setup, provider_for

FROZEN=json.loads((Path(__file__).parent/'fixtures/r_conclusions_live_20261008.json').read_text('utf-8'))


def test_actual_missing_raw_ids_remain_invalid_and_are_required_on_wire():
    raw=deepcopy(FROZEN['events'][0]['output']);original=deepcopy(raw)
    with pytest.raises(ValueError):parse_proposal(raw)
    assert raw==original  # no server repair
    for schema in (GeneralProposal,Verification):
        selected=response_schema(schema)['$defs']['SelectedBlock']
        assert {'fact_revision_ids','raw_span_id'}<=set(selected['required'])
    wire=response_schema(GeneralProposal)
    assert wire['$defs']['GroundedConclusion']['properties']['references']['items']=={'$ref':'#/$defs/SelectedBlock'}


@pytest.mark.asyncio
@pytest.mark.parametrize('proposal_index,verifier_index',[(1,2),(3,4)])
async def test_actual_all_candidate_ids_cannot_pass_selected_reference_check(tmp_path,proposal_index,verifier_index):
    _,_,kw,release=setup(tmp_path)
    event=FROZEN['events'][proposal_index];payload=event['request']['input']
    snap=PublishedKnowledgeSnapshot.model_validate(FROZEN['snapshot'])
    candidates=tuple(Candidate(c['card_id'],c['card_version_id'],c['block']['block_id'],None,None,0) for c in payload['candidates'])
    search=SearchResult(snap,1,candidates,normalize_query(payload['question']))
    release.update(snapshot_hash=snap.snapshot_hash,response_style='grounded_conclusion')
    kw['settings'].r_general_semantics_path.write_text(json.dumps(release),encoding='utf-8')
    kw['settings'].r_general_semantics_hash=digest(release)
    kw.update(question=payload['question'],user_turns=tuple(payload['user_turns']),
        baseline=decide(search,store_id=1,question=payload['question']))
    async def provider(prompt,*,schema,**unused):
        if schema is GeneralProposal:return event['output']
        request=json.loads(prompt.rsplit('\n',1)[1])
        assert len(request['selected_reference_check']['checked_raw_blocks'])==1
        assert len(request['candidate_reference_units'])==9
        result=deepcopy(FROZEN['events'][verifier_index]['output'])
        result['request_hash']=request['request_hash']  # Bind replay to current request, leave bad references untouched.
        return result
    with pytest.raises(ApiError) as error:await general_decision(search,provider=provider,**kw)
    assert error.value.code=='GENERAL_INVALID_PROPOSAL'


@pytest.mark.asyncio
async def test_verifier_receives_distinct_selected_and_full_candidate_scopes(tmp_path):
    search,raw,kw,_=setup(tmp_path)
    base=provider_for(search,raw)
    async def provider(prompt,*,schema,**kwargs):
        result=await base(prompt,schema=schema,**kwargs)
        if schema is Verification:
            request=json.loads(prompt.rsplit('\n',1)[1])
            assert request['selected_reference_check']['checked_raw_blocks']==[list(r) for r in result['checked_raw_blocks']]
            assert request['selected_reference_check']['checked_fact_ids']==list(result['checked_fact_ids'])
            assert len(request['candidate_reference_units'])>len(result['checked_raw_blocks'])
            # Both lists are covered by the signed request hash.
            assert digest({k:v for k,v in request.items() if k!='request_hash'})==request['request_hash']
        return result
    decision,_=await general_decision(search,provider=provider,**kw)
    assert decision.plan.action=='ANSWER'
