"""Prepare/verify pinned releases for a store pilot or the demo. No provider calls."""
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
    demo=mode.endswith('-demo')
    op=mode.removesuffix('-demo')
    if op not in ('prepare','verify'): raise ValueError('unknown operation')
    if not (s.r_v2_enabled and s.gemini_api_key and not s.r_reranker_enabled):
        raise ValueError('basic chat, Gemini key, and disabled reranking are required')
    db=await asyncpg.connect(s.supabase_db_url,timeout=8)
    try:
        async with db.transaction(readonly=True,isolation='repeatable_read'):
            await db.execute("set local statement_timeout='8s'")
            ids=[STORE]
            if demo:
                # Trusted operator enumerates stores; every subsequent index read is store scoped.
                ids=[row['store_id'] for row in await db.fetch("""select distinct store_id
                    from knowledge_cards where review_status='APPROVED' and is_verified
                    and published_version_id is not null order by store_id""")]
            if not ids: raise ValueError('no stores have approved searchable cards')
            snapshots={}
            for sid in ids:
                snapshot,_,_=await read_current_index(db,store_id=sid)
                if not snapshot.cards: raise ValueError(f'no published cards in store {sid}')
                snapshots[sid]=snapshot
    finally: await db.close()
    if op=='verify':
        if (not s.r_general_semantics_enabled or s.r_general_semantics_demo_enabled!=demo
                or (not demo and s.r_general_semantics_store_id!=STORE)):
            raise ValueError('effective pilot flags do not match')
        for sid,snapshot in snapshots.items():
            rel=load_release(s,SimpleNamespace(snapshot=snapshot),sid)
        print(json.dumps(dict(config_verified=True,stores=ids,model=rel.model,expires=rel.valid_until.isoformat(),provider_calls=0)))
        return
    if s.r_general_semantics_enabled and not (demo and s.r_general_semantics_demo_enabled):
        raise ValueError('existing different rollout active; disable before replacing')
    expiry=datetime.now(timezone.utc)+timedelta(days=7 if demo else 1)
    version=source_hash()
    common=dict(source_hash=version,model=s.gemini_model,approved_by='Operator executing the authenticated demo activation' if demo else 'Operator executing the authenticated store-9 activation',
        acceptance_reference=('Explicit 2026-11-08 request for Gemini for every employee tester in the AskBuddy demo; not a production quality signoff.' if demo else
            'Explicit 2026-11-08 request for a limited store-9 live pilot following receipts 18-22; not a production-wide quality signoff.'),
        valid_until=expiry,response_style='grounded_conclusion',max_prompt_bytes=100000,max_input_tokens=32000,max_output_tokens=4096,thinking_level='low')
    releases={str(sid):Release(store_id=str(sid),snapshot_hash=snapshot.snapshot_hash,**common).model_dump(mode='json')
              for sid,snapshot in snapshots.items()}
    raw=dict(schema_version='r-demo-release-set/v1',releases=releases) if demo else releases[str(STORE)]
    print(json.dumps(dict(release=raw,pin=digest(raw)),ensure_ascii=False))

if __name__=='__main__':
    try: asyncio.run(main(sys.argv[1]))
    except Exception as exc:
        print('Pilot check failed: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
