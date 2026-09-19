from copy import deepcopy
from dataclasses import replace
import pytest
from app.contracts.hashing import digest
from app.learn.semantic_proposals import proposal_input
from app.team.reviewed_catalog import build_catalog
from tests.test_r_reviewed_semantics import fixture


def item():
    search,q,baseline,catalog=fixture()
    entry=catalog.entries[0]
    payload=proposal_input(search,store_id=1,question=q)
    row=dict(schema_version='r_semantic_observation/v1',store_id='1',snapshot_hash=search.snapshot.snapshot_hash,
        status='REVIEW_REQUIRED',production_eligible=False,provider_mode='SYNTHETIC',source_hashes={'synthetic':'test'},
        input=payload,input_hash=payload['input_hash'],elapsed_ms=1,baseline_plan=baseline.plan.model_dump(mode='json'),
        proposal=entry.proposal.model_dump(mode='json'))
    row['row_hash']=digest(row)
    label=dict(row_hash=row['row_hash'],reviewer='synthetic human',reason='synthetic only',expected_action='ANSWER',
        semantic_correct=True,false_block=False,false_merge=False,citation_error=False)
    return dict(search=search,observation=row,judgment=label,approval_id='test-approval',confirmed_slots={},
        interpretation=entry.interpretation.model_dump(mode='json'))


def test_compiles_exact_reviewed_observation_without_installing():
    value=item()
    data,key=build_catalog([value],acceptance_reference='synthetic acceptance only')
    assert key==digest(data) and data['entries'][0]['proposal']==value['observation']['proposal']
    assert value['observation']['row_hash'] in data['entries'][0]['review_reference']


@pytest.mark.parametrize('change',['unreviewed','wrong','citation','action','drift','raw','duplicate','acceptance'])
def test_no_implicit_approval_or_reference_repair(change):
    value=item();values=[value];acceptance='synthetic only'
    if change=='unreviewed':value['judgment']={}
    if change=='wrong':value['judgment']['semantic_correct']=False
    if change=='citation':value['judgment']['citation_error']=True
    if change=='action':value['judgment']['expected_action']='ESCALATE'
    if change=='drift':value['search']=replace(value['search'],candidates=())
    if change=='raw':value['interpretation']['raw_blocks']=[]
    if change=='duplicate':values=[value,deepcopy(value)]
    if change=='acceptance':acceptance=' '
    with pytest.raises(ValueError):build_catalog(values,acceptance_reference=acceptance)


def test_cli_writes_loadable_catalog_and_never_overwrites(tmp_path,monkeypatch):
    from dataclasses import asdict
    import json
    from scripts.build_r_reviewed_catalog import main
    from app.learn.reviewed_semantics import load_catalog
    value=item();search=value['search']
    value['search']=dict(snapshot=search.snapshot.model_dump(mode='json'),index_revision=search.index_revision,
        candidates=[asdict(c) for c in search.candidates])
    source=tmp_path/'review.json';target=tmp_path/'catalog.json'
    source.write_text(json.dumps(dict(acceptance_reference='synthetic only',items=[value])),encoding='utf-8')
    monkeypatch.setattr('sys.argv',['build_r_reviewed_catalog','--input',str(source),'--output',str(target)])
    main()
    raw=json.loads(target.read_text(encoding='utf-8'))
    assert len(load_catalog(target,digest(raw)).entries)==1
    before=target.read_bytes()
    with pytest.raises(FileExistsError):main()
    assert target.read_bytes()==before
