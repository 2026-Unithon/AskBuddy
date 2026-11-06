"""Model-facing schema and server-owned context allocation; public DTOs stay strict."""
from copy import deepcopy
from uuid import uuid4


def _provider_array_limits(node):
    """Remove decoder array bounds; Pydantic still enforces every server limit.

    The complete GeneralProposal with nested maxItems is rejected by the live
    Gemini endpoint (400). An otherwise identical schema without maxItems is
    accepted. Do not weaken public contracts or repair over-limit model output.
    """
    if not isinstance(node,dict):return
    node.pop('maxItems',None)
    for key in ('properties','$defs'):
        for child in node.get(key,{}).values():_provider_array_limits(child)
    for key in ('items','additionalProperties'):
        _provider_array_limits(node.get(key))
    for key in ('anyOf','oneOf','allOf','prefixItems'):
        for child in node.get(key,[]):_provider_array_limits(child)


def response_schema(schema,*,calculation_fact_ids=None,question_quotes=None,conclusions_enabled=None):
    result=deepcopy(schema.model_json_schema())
    # Protocol version is server-owned, just like context identity. Its public
    # literal/default stays strict; it is not a model interpretation task.
    result.get('properties',{}).pop('schema_version',None)
    result['required']=[k for k in result.get('required',[]) if k!='schema_version']
    if 'checked_raw_blocks' in result.get('properties',{}):
        result['required']=list(dict.fromkeys([*result['required'],'checked_user_turn_ids',
            'reason_code','reason_detail','clarification','candidate_coverage','checked_conclusion_ids','rule_coverage','case_action_review','situation_review']))
    selected=result.get('$defs',{}).get('SelectedBlock')
    if selected is not None:
        selected['required']=list(dict.fromkeys([*selected.get('required',[]),'fact_revision_ids','raw_span_id']))
        selected['properties']['raw_span_id']['description']='Always include this field. RAW: copy the exact candidate block.raw_span_id and set fact_revision_ids=[]. Typed facts: raw_span_id=null. card_id/version/block_id alone is incomplete.'
        selected['properties']['fact_revision_ids']['description']='Always include this field. RAW: []. Typed facts: nonempty approved fact revision IDs from this exact candidate block, with raw_span_id=null.'
    rule=result.get('$defs',{}).get('RuleCoverage')
    if rule is not None:rule['required']=list(dict.fromkeys([*rule['required'],'conclusion_unit_id']))
    case=result.get('$defs',{}).get('CaseAction')
    if case is not None:case['required']=list(dict.fromkeys([*case['required'],'conclusion_id','next_action_quote','state_unit_id']))
    if 'conclusions' in result.get('properties',{}):
        if conclusions_enabled is False:
            result['properties'].pop('conclusions')
            result['properties'].pop('case_requirements',None)
            for name in ('GroundedConclusion','CaseRequirements','CaseRequirement','UserEvidence'):result.get('$defs',{}).pop(name,None)
        elif conclusions_enabled is True:
            result['required']=list(dict.fromkeys([*result['required'],'conclusions','case_requirements']))
    slot=result.get('$defs',{}).get('SlotProposal')
    if slot is not None:
        slot['properties']['question_quote']['description']='Copy an exact contiguous substring from input.question or input.user_turns. Never copy a candidate title or paraphrase it. This is checked by literal substring matching.'
        if question_quotes is not None:
            quotes=list(dict.fromkeys(question_quotes))
            if not quotes or any(not isinstance(q,str) or not q or len(q)>1000 for q in quotes):
                raise ValueError('bounded trusted user quotes required')
            slot['properties']['question_quote']['enum']=quotes
            slot['properties']['question_quote']['description']='Select the exact current or previous user turn that supports this slot. Only these user-authored strings are allowed, never candidate text.'
    if 'AnswerPart' in result.get('$defs',{}):
        result['required']=list(dict.fromkeys([*result.get('required',[]),'slots','interpretation','parts','obligations','unresolved']))
        part=result['$defs']['AnswerPart']
        part['required']=list(dict.fromkeys([*part.get('required',[]),'slots','obligations']))
    if calculation_fact_ids is not None and 'calculations' in result.get('properties',{}):
        ids=list(dict.fromkeys(calculation_fact_ids))
        if not ids:
            # No approved retrieved quantity means no model-facing arithmetic
            # language. The server DTO still rejects any invented operands.
            result['properties'].pop('calculations')
            result['$defs'].pop('Calculation',None)
            result['required'].append('unsupported_calculation')
        else:
            result['$defs']['Calculation']['properties']['fact_ids']['items']['enum']=ids
    plan=result.get('$defs',{}).get('AnswerPlan')
    if plan is not None:
        # The provider selects an action, never issues a server context identity.
        plan['properties'].pop('context_id',None)
        plan['properties'].pop('schema_version',None)
        plan['required']=[key for key in plan.get('required',[]) if key not in ('context_id','schema_version')]
        plan['properties']['action']['enum']=['ANSWER','CLARIFY','ESCALATE']
        plan['properties']['action']['description']='ANSWER selects approved blocks; CLARIFY has choices only; ESCALATE has a reason only. No REFUSE or SAFE_ROUTE.'
    _provider_array_limits(result)
    return result


def parse_proposal(raw):
    from app.learn.general_semantics import GeneralProposal
    if isinstance(raw,GeneralProposal):return raw
    raw=deepcopy(raw)
    if not isinstance(raw,dict):raise ValueError('proposal must be an object')
    plans=[raw.get('plan')]
    if isinstance(raw.get('parts'),list):
        plans.extend(part.get('plan') for part in raw['parts'] if isinstance(part,dict))
    for plan in plans:
        if not isinstance(plan,dict):continue  # Pydantic reports missing/invalid plans.
        if plan.get('context_id') is not None:raise ValueError('model cannot issue context IDs')
        if plan.get('action')=='CLARIFY':plan['context_id']=str(uuid4())
    return GeneralProposal.model_validate(raw)
