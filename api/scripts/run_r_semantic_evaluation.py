"""Bounded live proposal evaluation on an explicitly isolated local DB; no product promotion.

Input format matches compare_r_semantic_proposal.py. Run three or more repetitions
per pre-registered arm; JSONL output survives interruption. No automatic retries.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.learn.planner import decide
from app.learn.semantic_proposals import ComparisonQuestion, proposal_input
from app.reg.hybrid import Candidate, SearchResult
from app.team.evaluation_usage import evaluation_usage_scope
from app.team.semantic_shadow import semantic_shadow_scope, observe_decision
from app.team.evaluation_budget import EvaluationBudget, evaluation_budget_scope
from app.contracts.hashing import digest


async def run(args):
    import asyncpg
    dsn = os.environ.get('R_EVALUATION_DATABASE_URL', '')
    if urlparse(dsn).hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('explicit local isolated R_EVALUATION_DATABASE_URL required')
    data = json.loads(args.input.read_text(encoding='utf-8'))
    policy = json.loads(args.budget_policy.read_text(encoding='utf-8'))
    if digest(policy) != args.budget_hash:
        raise ValueError('approved budget policy hash mismatch')
    snapshot = PublishedKnowledgeSnapshot.model_validate(data['snapshot'])
    search = SearchResult(snapshot, data['index_revision'], tuple(Candidate(**c) for c in data['candidates']), data['question'])
    store_id = int(snapshot.store_id)
    turns = tuple(data.get('user_turns', ()))
    comparisons = tuple(ComparisonQuestion.model_validate(c) for c in data.get('comparisons', ()))
    proposal_input(search, store_id=store_id, question=data['question'], user_turns=turns, comparisons=comparisons)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        budget = EvaluationBudget(pool, policy)
        if budget.policy.store_id != str(store_id) or str(args.run_id) not in budget.policy.evaluation_run_ids:
            raise ValueError('budget is for another store/run')
        async with pool.acquire() as conn:
            if not await conn.fetchval("select exists(select 1 from evaluation_runs where run_id=$1 and store_id=$2 and status='RUNNING')", args.run_id, store_id):
                raise ValueError('existing RUNNING evaluation run in this store required')
        # Open exclusively before any provider call. Caller chooses a private store-local path.
        with args.output.open('x', encoding='utf-8') as stream:
            async def record(row):
                row = dict(row, budget_campaign_id=str(budget.policy.campaign_id), budget_policy_hash=budget.hash,
                    reserved_units_per_call=budget.policy.call_units)
                row['row_hash'] = digest({k:v for k,v in row.items() if k != 'row_hash'})
                stream.write(json.dumps(row, ensure_ascii=False)+'\n')
                stream.flush()
                os.fsync(stream.fileno())
            with evaluation_usage_scope(store_id=store_id, evaluation_run_id=str(args.run_id)), evaluation_budget_scope(budget):
                with semantic_shadow_scope(store_id=store_id, record=record, comparisons=comparisons):
                    for _ in range(args.repeat):
                        await observe_decision(pool=pool, store_id=store_id, search=search, question=data['question'],
                            user_turns=turns, baseline=decide(search, store_id=store_id, question=data['question']),
                            request_id=uuid4().hex, timeout=args.timeout)
    finally:
        await pool.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--budget-policy', type=Path, required=True, help='explicit approved campaign limits and pricing ceilings')
    parser.add_argument('--budget-hash', required=True, help='pinned approved policy hash')
    parser.add_argument('--repeat', type=int, choices=range(1, 21), default=3)
    parser.add_argument('--timeout', type=float, default=2)
    parser.add_argument('--isolated-live', action='store_true', required=True,
        help='explicit paid provider execution on an isolated evaluation DB')
    args = parser.parse_args()
    if not 0 < args.timeout <= 3:
        parser.error('timeout must be within (0,3] seconds')
    asyncio.run(run(args))
    print(json.dumps(dict(status='REVIEW_REQUIRED', calls_max=args.repeat, production_eligible=False)))


if __name__ == '__main__': main()
