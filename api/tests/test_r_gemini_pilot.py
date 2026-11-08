from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from app.config import get_settings
from app.errors import ApiError
from app.learn.general_semantics import settings_for_chat_store, product_general_decision

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
