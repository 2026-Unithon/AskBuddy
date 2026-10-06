from dataclasses import replace
import pytest
from app.contracts.answer import AnswerPlan
from app.contracts.hashing import snapshot_digest
from app.learn.grounded_calculations import Calculation, calculate
from tests.test_r_composite_reasoning import fixture


def run(raw, *, question='3개 필요해', updates=None):
    search, _, proposal, _ = fixture()
    snap = search.snapshot
    if updates:
        facts = tuple(f.model_copy(update=updates.get(f.fact_revision_id, {})) for f in snap.fact_revisions)
        snap = snap.model_copy(update=dict(fact_revisions=facts))
        snap = snap.model_copy(update=dict(snapshot_hash=snapshot_digest(snap)))
    return calculate((Calculation.model_validate(raw),), plan=AnswerPlan.model_validate(proposal['plan']),
        snapshot=snap, store_id=1, question=question)


def test_scale_and_direction_are_server_calculated():
    assert run(dict(operator='SCALE',fact_ids=['1'],count=3,count_quote='3개')) == ('계산: 120원 × 3 = 360원',)
    assert run(dict(operator='SUBTRACT',fact_ids=['2','1'])) == ('계산: 30원 − 120원 = -90원',)


def test_decimal_unit_conversion_is_exact():
    search, _, _, _ = fixture()
    quantity = search.snapshot.fact_revisions[0].quantity
    assert run(dict(operator='ADD',fact_ids=['1','2']),updates={
        '1':dict(quantity=quantity.model_copy(update=dict(value='0.1',unit='kg'))),
        '2':dict(quantity=quantity.model_copy(update=dict(value='0.2',unit='g')))}) == ('계산: 100g + 0.2g = 100.2g',)


@pytest.mark.parametrize('count,quote,question', [(4,'3개','3개 필요'),(3,'3개','4개 필요'),
    (3,'3.3개','3.3개 필요'),(3,'-3개','-3개 필요'),(3,'3개 4개','3개 4개 필요'),(True,'1개','1개')])
def test_invented_ambiguous_or_noninteger_count_rejected(count,quote,question):
    with pytest.raises(ValueError):
        run(dict(operator='SCALE',fact_ids=['1'],count=count,count_quote=quote),question=question)


@pytest.mark.parametrize('change',['units','negative','unknown','missing','raw','huge'])
def test_unsupported_calculation_fails(change):
    search, _, _, _ = fixture()
    q = search.snapshot.fact_revisions[0].quantity
    updates = {
        'units': {'quantity':q.model_copy(update=dict(unit='g'))},
        'negative': {'polarity':'DENY'},
        'unknown': {'quantity':q.model_copy(update=dict(unit='%'))},
        'missing': {'quantity':None},
        'huge': {'quantity':q.model_copy(update=dict(value='10000000000000000'))},
    }
    with pytest.raises(ValueError):
        run(dict(operator='ADD',fact_ids=['1','999'] if change=='raw' else ['1','2']),
            updates={'1':updates[change]} if change!='raw' else None)
