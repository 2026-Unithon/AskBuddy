from dataclasses import replace
from uuid import uuid4
import pytest
from app.contracts.hashing import snapshot_digest
from app.learn.answer_storage import pending_key
from app.learn.reviewed_grouping import GroupingEvidence, reviewed_context
from app.learn.reviewed_semantics import ReviewedCatalog, apply_reviewed
from app.learn.semantic_proposals import proposal_input
from app.learn.planner import decide
from app.learn.general_semantics import validate_interpretation
from tests.test_r_reviewed_semantics import fixture


def reviewed(search, q, *, change=None):
    payload=proposal_input(search,store_id=1,question=q)
    scope=dict(entity=search.snapshot.cards[0].entity_id,predicate='milk_amount',temperature='HOT',size=None,
        conditions=['주말'],exceptions=['5잔 이상 제외'],scope_bindings=['잔수:2~4'],polarity='POSITIVE',complete=True)
    if change:scope.update(change)
    return ReviewedCatalog(acceptance_reference='synthetic only',entries=[dict(approval_id='test',store_id='1',
        question=q,user_turns=[],confirmed_slots={},proposal=dict(input_hash=payload['input_hash'],snapshot_hash=search.snapshot.snapshot_hash,
            plan=dict(snapshot_id=search.snapshot.snapshot_id,knowledge_revision=search.snapshot.knowledge_revision,
                action='ESCALATE',escalation_reason='INSUFFICIENT_KNOWLEDGE')),interpretation=None,grouping=scope,
        reviewer='synthetic human',review_reference='explicit synthetic scope review')])


def apply(search, q, catalog):
    return apply_reviewed(search,store_id=1,question=q,user_turns=(),baseline=decide(search,store_id=1,question=q),catalog=catalog)[0]


def test_exact_reviewed_paraphrases_merge_but_unknown_input_does_not():
    search,_,_,_=fixture()
    q1='주말 소량 주문에 들어갈 양 알려주세요';q2='휴일 두세 잔 준비할 때 양이 궁금해요'
    a=apply(search,q1,reviewed(search,q1));b=apply(search,q2,reviewed(search,q2))
    assert a.plan.action==b.plan.action=='ESCALATE'
    assert pending_key(store_id=1,semantic_context=a.semantic_context)==pending_key(store_id=1,semantic_context=b.semantic_context)
    unknown=apply(search,q2,reviewed(search,q1))
    assert unknown.semantic_context is None


@pytest.mark.parametrize('change',[{'predicate':'water_amount'},{'temperature':'ICE'},{'size':'L'},
    {'conditions':['평일']},{'exceptions':[]},{'scope_bindings':['잔수:5~9']},{'polarity':'NEGATIVE'}])
def test_scope_changes_never_merge(change):
    search,q,_,_=fixture()
    a=apply(search,q,reviewed(search,q));b=apply(search,q,reviewed(search,q,change=change))
    assert pending_key(store_id=1,semantic_context=a.semantic_context)!=pending_key(store_id=1,semantic_context=b.semantic_context)


def test_review_capability_cannot_be_replayed_for_other_input_or_snapshot():
    search,q,_,_=fixture();a=apply(search,q,reviewed(search,q))
    for evidence,snap,text in [(a.resolved.grouping_evidence,search.snapshot,q+' 다른 조건'),
        (a.resolved.grouping_evidence,search.snapshot.model_copy(update={'snapshot_hash':'sha256:'+'0'*64}),q),
        ({},search.snapshot,q)]:
        with pytest.raises(ValueError):reviewed_context(snap,evidence=evidence,question=text)


def test_entity_clarification_offers_only_unambiguous_approved_candidates():
    search,q,_,_=fixture();card=search.snapshot.cards[0]
    second=card.model_copy(update={'card_id':'999','card_version_id':'999','entity_id':'999','title':'다른 승인 대상'})
    snap=search.snapshot.model_copy(update={'cards':(*search.snapshot.cards,second)})
    snap=snap.model_copy(update={'snapshot_hash':snapshot_digest(snap)})
    candidate=replace(search.candidates[0],card_id='999',card_version_id='999')
    search=replace(search,snapshot=snap,candidates=(*search.candidates,candidate))
    payload=proposal_input(search,store_id=1,question=q);baseline=decide(search,store_id=1,question=q)
    raw=dict(input_hash=payload['input_hash'],snapshot_hash=snap.snapshot_hash,interpretation=None,
        plan=dict(snapshot_id=snap.snapshot_id,knowledge_revision=snap.knowledge_revision,action='CLARIFY',
            clarification_slot='entity',allowed_options=[card.title,second.title],context_id=str(uuid4())))
    chosen=validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline)
    assert chosen.plan.action=='CLARIFY' and chosen.confirmed_slots=={}
    assert str(chosen.plan.context_id)!=raw['plan']['context_id']
    assert validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,clarify_turns=2) is baseline
    with pytest.raises(ValueError):validate_interpretation(search,payload=payload,proposal=raw,
        baseline=replace(baseline,confirmed_slots={'entity':card.title}))
    raw['plan']['allowed_options']=[card.title,'만든 대상']
    with pytest.raises(ValueError):validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline)
