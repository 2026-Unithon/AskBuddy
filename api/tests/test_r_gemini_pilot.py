from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
import json
from datetime import datetime,timedelta,timezone
from app.contracts.hashing import digest
from app.config import get_settings
from app.errors import ApiError
from app.learn.general_semantics import settings_for_chat_store, product_general_decision

@pytest.mark.asyncio
async def test_demo_enrolls_multiple_stores_only_for_their_own_snapshot(tmp_path):
    hashes={8:'sha256:'+'8'*64,9:'sha256:'+'9'*64}
    releases={str(sid):dict(store_id=str(sid),snapshot_hash=h,source_hash='sha256:'+'a'*64,model='demo',
        approved_by='test',acceptance_reference='synthetic test',valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
        max_input_tokens=10000,max_output_tokens=2000,max_prompt_bytes=30000) for sid,h in hashes.items()}
    bundle=dict(schema_version='r-demo-release-set/v1',releases=releases)
    path=tmp_path/'releases.json'; path.write_text(json.dumps(bundle))
    settings=get_settings().model_copy(update=dict(r_general_semantics_enabled=True,r_general_semantics_demo_enabled=True,
        r_general_semantics_store_id=None,gemini_model='demo',r_general_semantics_path=str(path),r_general_semantics_hash=digest(bundle)))
    async def eligible(sid,snapshot_hash):
        @asynccontextmanager
        async def acquire(): yield NS(fetchval=AsyncMock(return_value=snapshot_hash))
        return (await settings_for_chat_store(settings,sid,NS(acquire=acquire))).r_general_semantics_enabled
    with patch('app.learn.general_semantics.source_hash',return_value='sha256:'+'a'*64):
        assert await eligible(8,hashes[8]) and await eligible(9,hashes[9])
        assert not await eligible(9,hashes[8])  # same set, wrong store's snapshot
        assert not await eligible(17,hashes[9]) and not await eligible(12,None)
        bundle['releases']['9']['approved_by']='changed'
        path.write_text(json.dumps(bundle))
        assert not await eligible(9,hashes[9])

@pytest.mark.asyncio
async def test_demo_bundle_preparation_covers_every_store_with_approved_cards(capsys):
    from scripts import chat_gemini_pilot as script
    from unittest.mock import MagicMock
    db=MagicMock(); db.execute=AsyncMock(); db.close=AsyncMock()
    db.fetch=AsyncMock(return_value=[{'store_id':8},{'store_id':17}])
    async def read(conn,*,store_id):
        return NS(snapshot_hash='sha256:'+str(store_id).zfill(64),cards=[object()]),1,1
    settings=get_settings().model_copy(update=dict(r_v2_enabled=True,r_general_semantics_enabled=False,
        r_reranker_enabled=False,gemini_api_key='synthetic'))
    with patch.object(script,'get_settings',return_value=settings), patch.object(script.asyncpg,'connect',AsyncMock(return_value=db)), \
         patch.object(script,'read_current_index',read), patch.object(script,'source_hash',return_value='sha256:'+'a'*64):
        await script.main('prepare-demo')
    result=json.loads(capsys.readouterr().out)
    assert result['pin']==digest(result['release'])
    assert set(result['release']['releases'])=={'8','17'}

def pilot():
    return get_settings().model_copy(update=dict(r_general_semantics_enabled=True,r_general_semantics_store_id=9))

@pytest.mark.asyncio
async def test_other_store_skips_release_and_history_without_changing_global_setting():
    settings=pilot()
    scoped=await settings_for_chat_store(settings,8,None)
    assert not scoped.r_general_semantics_enabled and settings.r_general_semantics_enabled

@pytest.mark.asyncio
@pytest.mark.parametrize('valid',[True,False])
async def test_target_store_requires_current_valid_release(valid):
    @asynccontextmanager
    async def acquire():
        yield NS(fetchval=AsyncMock(return_value='current-snapshot'))
    with patch('app.learn.general_semantics.load_release',side_effect=None if valid else ValueError()) as load:
        settings=await settings_for_chat_store(pilot(),9,NS(acquire=acquire))
    assert settings.r_general_semantics_enabled is valid
    assert load.call_args.args[1].snapshot.snapshot_hash=='current-snapshot'

@pytest.mark.asyncio
@pytest.mark.parametrize('reason,fallback',[('GENERAL_DEADLINE',True),('GENERAL_INVALID_PROPOSAL',True),('USAGE_UNAVAILABLE',False)])
async def test_pilot_keeps_baseline_only_for_model_or_release_errors(reason,fallback):
    baseline=object()
    with patch('app.learn.general_semantics.general_decision',side_effect=ApiError(503,reason,'test')):
        if fallback:
            decision,audit=await product_general_decision(None,baseline=baseline,settings=pilot(),store_id=9)
            assert decision is baseline and audit==dict(status='PILOT_BASELINE',reason=reason)
        else:
            with pytest.raises(ApiError):
                await product_general_decision(None,baseline=baseline,settings=pilot(),store_id=9)
