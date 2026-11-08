"""Prepare/verify a short store-9 operational pilot. No SDK or provider call."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import sys
from types import SimpleNamespace
import asyncpg
from app.config import get_settings
from app.contracts.hashing import digest
from app.learn.general_semantics import Release, load_release, source_hash
from app.reg.hybrid import read_current_index

STORE=9

async def main(mode):
    s=get_settings()
    if mode not in ('prepare','verify'): raise ValueError('unknown operation')
    if not (s.r_v2_enabled and s.gemini_api_key and not s.r_reranker_enabled):
        raise ValueError('basic chat, Gemini key, and disabled reranking are required')
    db=await asyncpg.connect(s.supabase_db_url,timeout=8)
    try:
        async with db.transaction(readonly=True,isolation='repeatable_read'):
            await db.execute("set local statement_timeout='8s'")
            snapshot,_,_=await read_current_index(db,store_id=STORE)
            if not snapshot.cards: raise ValueError('no published cards in pilot store')
    finally: await db.close()
    if mode=='verify':
        if not s.r_general_semantics_enabled or s.r_general_semantics_store_id!=STORE:
            raise ValueError('effective pilot flags do not match')
        rel=load_release(s,SimpleNamespace(snapshot=snapshot),STORE)
        print(json.dumps(dict(config_verified=True,store=STORE,model=rel.model,expires=rel.valid_until.isoformat(),provider_calls=0)))
        return
    if s.r_general_semantics_enabled: raise ValueError('existing rollout active; disable before replacing')
    raw=Release(store_id=str(STORE),snapshot_hash=snapshot.snapshot_hash,source_hash=source_hash(),
        model=s.gemini_model,approved_by='Operator executing the authenticated store-9 activation',
        acceptance_reference='Explicit 2026-11-08 request for a limited store-9 live pilot following receipts 18-22; not a production-wide quality signoff.',
        valid_until=datetime.now(timezone.utc)+timedelta(hours=24),response_style='grounded_conclusion',
        max_prompt_bytes=100000,max_input_tokens=32000,max_output_tokens=4096,thinking_level='low').model_dump(mode='json')
    print(json.dumps(dict(release=raw,pin=digest(raw)),ensure_ascii=False))

if __name__=='__main__':
    try: asyncio.run(main(sys.argv[1]))
    except Exception as exc:
        print('Pilot check failed: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
