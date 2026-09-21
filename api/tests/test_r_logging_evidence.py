from datetime import datetime, timezone, timedelta
import pytest
from app.team.logging_evidence import check_evidence, CONTROLS


@pytest.mark.parametrize('change', [None,'missing','unknown','failed','commit','old','future'])
def test_operator_evidence_is_never_automatic_hosting_verification(change):
    now=datetime.now(timezone.utc)
    raw=dict(service='synthetic',environment='test',deployed_commit='1'*40,observed_at=now,
        reviewer='synthetic operator',controls={name:dict(status='CONFIRMED',reference='restricted://synthetic/'+name) for name in CONTROLS})
    if change=='missing':raw['controls']['restricted_access']['reference']=None
    if change in ('unknown','failed'):raw['controls']['restricted_access']['status']=change.upper()
    if change=='commit':raw['deployed_commit']='2'*40
    if change=='old':raw['observed_at']=now-timedelta(days=31)
    if change=='future':raw['observed_at']=now+timedelta(seconds=1)
    result=check_evidence(raw,service='synthetic',environment='test',deployed_commit='1'*40,now=now)
    assert result['status']==('BLOCKED' if change else 'READY_FOR_REVIEW')
    assert result['hosting_verified_by_tool'] is False
