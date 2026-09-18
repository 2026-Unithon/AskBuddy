"""Trusted in-process evaluation hook. Never changes a product decision or merge key."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from time import perf_counter
from pathlib import Path

from app.contracts.hashing import digest
from app.contracts.usage import UsageContext
from app.learn.semantic_proposals import propose, proposal_input
from app.team.evaluation_usage import evaluation_run_for_store, request_usage_sink

_shadow = ContextVar('r_semantic_shadow', default=None)


@contextmanager
def semantic_shadow_scope(*, store_id, record, provider=None, comparisons=()):
    """Nest inside evaluation_usage_scope; record is awaited, private durable output."""
    run_id = evaluation_run_for_store(store_id)
    if run_id is None or not callable(record):
        raise ValueError('isolated evaluation scope and recorder required')
    token = _shadow.set((store_id, run_id, record, provider, tuple(comparisons)))
    try:
        yield
    finally:
        _shadow.reset(token)


async def observe_decision(*, pool, store_id, search, question, user_turns, baseline,
                           request_id, timeout):
    scope = _shadow.get()
    if scope is None:
        return  # No provider, allocations, or output in normal product requests.
    owner, run_id, record, provider, comparisons = scope
    if owner != store_id or evaluation_run_for_store(store_id) != run_id:
        raise ValueError('shadow scope mismatch')
    start = perf_counter()
    context = UsageContext(store_id=str(store_id), cost_phase='OPERATING',
        cost_purpose='EVALUATION', stage='ANSWER', evaluation_run_id=run_id,
        logical_call_id='semantic:' + digest(dict(request_id=request_id,
            snapshot=search.snapshot.snapshot_hash))[7:])
    result = await propose(search, store_id=store_id, question=question, user_turns=user_turns,
        comparisons=comparisons, context=context, sink=request_usage_sink(pool, store_id=store_id),
        timeout=timeout, provider=provider)
    # The actual router baseline includes verified confirmation context and policy handling.
    result = replace(result, baseline_action=baseline.plan.action, baseline_plan=baseline.plan)
    root = Path(__file__).resolve().parents[1]
    sources = ('team/semantic_shadow.py', 'learn/semantic_proposals.py', 'learn/planner.py')
    row = dict(schema_version='r_semantic_observation/v1', evaluation_run_id=run_id,
        request_id=request_id, store_id=str(store_id), input_hash=result.input_hash,
        input=proposal_input(search,store_id=store_id,question=question,user_turns=user_turns,comparisons=comparisons),
        snapshot_hash=search.snapshot.snapshot_hash, status=result.status,
        elapsed_ms=round((perf_counter()-start)*1000, 3),
        provider_mode='SYNTHETIC' if provider is not None else 'LIVE',
        source_hashes={name: digest((root/name).read_text(encoding='utf-8')) for name in sources},
        baseline_plan=baseline.plan.model_dump(mode='json'),
        proposal=result.proposal.model_dump(mode='json') if result.proposal else None,
        production_eligible=False)
    await record(dict(row, row_hash=digest(row)))
