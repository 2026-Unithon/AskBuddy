from dataclasses import replace
from types import SimpleNamespace

from app.contracts.extraction import EvidenceLocator
from app.contracts.snapshot import FactProvenance
from app.learn.approved_renderer import render
from app.learn.citation_origin import citation_origin
from app.learn.planner import decide
from app.reg.hybrid import Candidate, complete_entity_candidates
from tests import test_r_planner as planner_fixture


def split_search():
    search=planner_fixture.PlannerTest().search()
    snap=search.snapshot
    target=snap.fact_revisions[0].model_copy(update={'subject':'라테','requires':('2',)})
    prerequisite=target.model_copy(update={'fact_revision_id':'2','fact_id':'2',
        'predicate':'preparation','assertion':'먼저 컵을 준비하세요','requires':()})
    card=snap.cards[0].model_copy(update={'title':'라테 HOT 2/2'})
    other=card.model_copy(update={'card_id':'2','card_version_id':'2','title':'라테 HOT 1/2',
        'blocks':(card.blocks[0].model_copy(update={'fact_revision_ids':('2',)}),)})
    snap=snap.model_copy(update={'renderer_version':'r-approved/v2','cards':(card,other),'fact_revisions':(target,prerequisite)})
    return replace(search,snapshot=snap,candidates=(*search.candidates,Candidate('2','2','b',None,None,0)))


def test_split_entity_prerequisite_order_heading_and_exact_assertions():
    search=split_search()
    decision=decide(search,store_id=1,question='HOT 라테 우유 얼마나?')
    assert decision.plan.action=='ANSWER'
    assert [b.card_id for b in decision.plan.selected_blocks]==['2','1']
    text=render(decision.plan,search.snapshot,store_id=1,request_id='split-consumer').message
    assert text=='라테 / HOT\n먼저 컵을 준비하세요\nHOT 라테 우유 225ml'
    assert decide(search,store_id=1,question='HOT 말차라테 우유 얼마나?').plan.action!='ANSWER'


def test_missing_sibling_never_answers_and_expansion_only_uses_eligible_references():
    search=split_search()
    ranked=search.candidates[:1]
    incomplete=replace(search,candidates=ranked)
    assert decide(incomplete,store_id=1,question='HOT 라테 우유 얼마나?').plan.action!='ANSWER'
    channels=SimpleNamespace(snapshot=search.snapshot,entity_references=(('2','2','b'),('9','9','b')))
    expanded=complete_entity_candidates(channels,ranked)
    assert len(expanded)==2 and expanded[-1].vector_score is None and expanded[-1].rrf_score==0
    assert decide(replace(search,candidates=expanded),store_id=1,question='HOT 라테 우유 얼마나?').plan.action=='ANSWER'


def test_alias_requires_explicit_selection_and_split_subject_survives_followup():
    search=replace(split_search(),alias_terms=('라테',))
    first=decide(search,store_id=1,question='HOT 라떼 우유 얼마나?')
    assert first.plan.action=='CLARIFY' and first.plan.allowed_options==('라테',)
    second=decide(search,store_id=1,question='HOT 라테 우유 얼마나?',confirmed_slots={'entity':'라테'})
    assert second.plan.action=='ANSWER'


def test_old_renderer_keeps_historical_headings():
    search=split_search()
    snapshot=search.snapshot.model_copy(update={'renderer_version':'r-approved/v1'})
    decision=decide(replace(search,snapshot=snapshot),store_id=1,question='HOT 라테 우유 얼마나?')
    text=render(decision.plan,snapshot,store_id=1,request_id='legacy-headings').message
    assert '라테 HOT 1/2 / HOT' in text and '라테 HOT 2/2 / HOT' in text


def test_split_card_size_clarifies_and_preserves_selected_size():
    search=split_search()
    facts=tuple(f.model_copy(update={'variant':f.variant.model_copy(update={'size':'L'})}) for f in search.snapshot.fact_revisions)
    search=replace(search,snapshot=search.snapshot.model_copy(update={'fact_revisions':facts}))
    missing=decide(search,store_id=1,question='HOT 라테 우유 얼마나?')
    assert missing.plan.action=='CLARIFY' and missing.plan.clarification_slot=='size'
    selected=decide(search,store_id=1,question='HOT 라테 L 우유 얼마나?')
    assert selected.plan.action=='ANSWER' and selected.confirmed_slots['size']=='L'


def test_citation_origin_uses_relationship_not_title_and_preserves_all_occurrences():
    snap=split_search().snapshot
    fact=snap.fact_revisions[0].model_copy(update={'provenance':(
        FactProvenance(source_id='1',occurrence_id='1',locator=EvidenceLocator(type='LINE',line=2)),
        FactProvenance(source_id='1',occurrence_id='2',locator=EvidenceLocator(type='LINE',line=4)),
        FactProvenance(source_id='9',occurrence_id='3'))})
    snap=snap.model_copy(update={'fact_revisions':(fact,)})
    row=dict(source_id=1,owner_answer_id=None,linked_owner_answer_id=None,
             source_type='OWNER_TEXT',raw_span_id=None,fact_revision_id=1)
    direct=citation_origin(snap,row)
    assert direct['source_kind']=='OWNER_TEXT' and direct['related_owner_answer_id'] is None
    assert [p['locator']['line'] for p in direct['source_locations']]==[2,4]
    linked=citation_origin(snap,{**row,'linked_owner_answer_id':8})
    assert linked['source_kind']=='OWNER_ANSWER' and linked['related_owner_answer_id']=='8'
    assert citation_origin(snap,{**row,'source_type':'KAKAO'})['source_kind']=='SOURCE'
    assert citation_origin(snap,{**row,'source_type':None})['source_kind']=='UNKNOWN'
