"""Durable worst-case reservations, shared across processes/runs of one evaluation campaign.

Amounts are integer millionths of KRW. No refund for retries, failures, unknown
usage or process crashes. Rates/caps are explicit reviewed inputs, never defaults.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from uuid import UUID
from typing import Literal

from pydantic import Field, field_validator, model_validator
from app.contracts.common import Contract, EntityId
from app.contracts.hashing import digest

_budget = ContextVar('r_evaluation_budget', default=None)
_SCALE = Decimal(1_000_000)


class BudgetDenied(ValueError):
    pass


def units(value):
    number = Decimal(str(value))
    if not number.is_finite() or number <= 0:
        raise ValueError('positive finite money required')
    result = int((number * _SCALE).to_integral_value(rounding=ROUND_CEILING))
    if result > 9_000_000_000_000_000:
        raise ValueError('money exceeds storage bound')
    return result


class BudgetCall(Contract):
    stage: Literal['QUERY', 'EMBED', 'RERANK']
    model: str = Field(min_length=1, max_length=100)


class BudgetPolicy(Contract):
    campaign_id: UUID
    store_id: EntityId
    evaluation_run_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=100)
    # All allowed calls reserve the SAME conservative token/rate ceiling, including
    # embeddings (unused output allowance is not refunded). One campaign, one cap.
    additional_calls: tuple[BudgetCall, ...] = Field(default=(), max_length=10)
    max_calls: int = Field(strict=True, gt=0, le=100000)
    max_krw: str
    max_input_tokens: int = Field(strict=True, gt=0, le=1000000)
    max_output_tokens: int = Field(strict=True, gt=0, le=100000)
    max_prompt_bytes: int = Field(strict=True, gt=0, le=200000)
    input_krw_per_million: str
    output_krw_per_million: str
    # Include price tier, exchange-rate ceiling and all applicable charges in this evidence.
    price_reference: str = Field(min_length=1, max_length=1000)
    approved_by: str = Field(min_length=1, max_length=100)
    valid_until: datetime

    @field_validator('max_krw', 'input_krw_per_million', 'output_krw_per_million')
    @classmethod
    def money(cls, value):
        units(value)
        return value

    @model_validator(mode='after')
    def complete(self):
        if (len(set(self.evaluation_run_ids)) != len(self.evaluation_run_ids)
                or self.valid_until.tzinfo is None or not self.price_reference.strip() or not self.approved_by.strip()):
            raise ValueError('distinct runs and explicit time/pricing approval required')
        if Decimal(self.max_krw)*_SCALE != (Decimal(self.max_krw)*_SCALE).to_integral_value():
            raise ValueError('budget cap supports at most six decimal KRW places')
        if self.call_units > units(self.max_krw):
            raise ValueError('one worst-case call exceeds campaign budget')
        if len({(c.stage,c.model) for c in self.additional_calls}) != len(self.additional_calls):
            raise ValueError('duplicate stage/model allowance')
        return self

    @property
    def call_units(self):
        return units((Decimal(self.max_input_tokens)*Decimal(self.input_krw_per_million)
            + Decimal(self.max_output_tokens)*Decimal(self.output_krw_per_million)) / _SCALE)


class EvaluationBudget:
    def __init__(self, pool, policy):
        self.pool = pool
        self.policy = BudgetPolicy.model_validate(policy)
        self.hash = digest(self.policy.model_dump(mode='json'))

    def check_scope(self, context, model):
        p = self.policy
        allowed = {('ANSWER',p.model), *((c.stage,c.model) for c in p.additional_calls)}
        if (context.cost_purpose != 'EVALUATION' or (context.stage,model) not in allowed
                or context.store_id != p.store_id or context.evaluation_run_id not in p.evaluation_run_ids
                or datetime.now(timezone.utc) >= p.valid_until):
            raise BudgetDenied('budget scope/model/run expired or mismatched')

    async def reserve(self, context, model):
        self.check_scope(context, model)
        p = self.policy
        key = digest(context.model_dump(mode='json'))
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Campaign identity survives process restarts; changed limits cannot replace it.
                await conn.execute("""insert into r_evaluation_budgets
                    (store_id,campaign_id,policy_hash,policy,max_calls,max_units)
                    values($1,$2,$3,$4::jsonb,$5,$6) on conflict do nothing""",
                    int(p.store_id),p.campaign_id,self.hash,p.model_dump_json(),p.max_calls,units(p.max_krw))
                account = await conn.fetchrow('select * from r_evaluation_budgets where store_id=$1 and campaign_id=$2 for update',
                    int(p.store_id),p.campaign_id)
                if account['policy_hash'] != self.hash or account['halted']:
                    raise BudgetDenied('changed policy or halted campaign')
                if not await conn.fetchval("select exists(select 1 from evaluation_runs where store_id=$1 and run_id=$2 and status='RUNNING')",
                        int(p.store_id),int(context.evaluation_run_id)):
                    raise BudgetDenied('active same-store evaluation run required')
                if await conn.fetchval('select exists(select 1 from r_evaluation_reservations where store_id=$1 and campaign_id=$2 and call_key=$3)',
                        int(p.store_id),p.campaign_id,key):
                    raise BudgetDenied('call already reserved; do not repeat provider')
                if account['reserved_calls'] >= p.max_calls or account['reserved_units'] + p.call_units > units(p.max_krw):
                    raise BudgetDenied('evaluation budget exhausted')
                await conn.execute('update r_evaluation_budgets set reserved_calls=reserved_calls+1,reserved_units=reserved_units+$3 where store_id=$1 and campaign_id=$2',
                    int(p.store_id),p.campaign_id,p.call_units)
                await conn.execute('insert into r_evaluation_reservations(store_id,campaign_id,call_key,evaluation_run_id,reserved_units) values($1,$2,$3,$4,$5)',
                    int(p.store_id),p.campaign_id,key,int(context.evaluation_run_id),p.call_units)
        return key

    async def finish(self, key, *, input_tokens=None, output_tokens=None):
        p = self.policy
        known = all(type(n) is int and n >= 0 for n in (input_tokens,output_tokens))
        status = ('EXCEEDED' if input_tokens > p.max_input_tokens or output_tokens > p.max_output_tokens else 'OBSERVED') if known else 'UNKNOWN'
        observation = digest(dict(input_tokens=input_tokens,output_tokens=output_tokens,status=status))
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Same lock ordering as reserve, including uncertain/crashed callers.
                account = await conn.fetchrow('select policy_hash from r_evaluation_budgets where store_id=$1 and campaign_id=$2 for update',int(p.store_id),p.campaign_id)
                if account is None or account['policy_hash'] != self.hash:
                    raise BudgetDenied('settlement policy mismatch')
                row = await conn.fetchrow('select status,observation_hash from r_evaluation_reservations where store_id=$1 and campaign_id=$2 and call_key=$3 for update',int(p.store_id),p.campaign_id,key)
                if row is None or (row['observation_hash'] is not None and row['observation_hash'] != observation):
                    raise BudgetDenied('foreign or changed budget settlement')
                await conn.execute('update r_evaluation_reservations set status=$4,observation_hash=$5 where store_id=$1 and campaign_id=$2 and call_key=$3',int(p.store_id),p.campaign_id,key,status,observation)
                if status != 'OBSERVED':
                    await conn.execute('update r_evaluation_budgets set halted=true where store_id=$1 and campaign_id=$2',int(p.store_id),p.campaign_id)
        if status == 'EXCEEDED':
            raise BudgetDenied('provider exceeded approved token limits; campaign halted')


@contextmanager
def evaluation_budget_scope(budget):
    token = _budget.set(budget)
    try:
        yield
    finally:
        _budget.reset(token)


def current_budget(context, model):
    budget = _budget.get()
    if budget is None:
        raise BudgetDenied('explicit evaluation budget is required before live provider access')
    budget.check_scope(context,model)
    return budget


def provider_budget(context, model):
    """Resolve trusted HTTP evaluation scope before provider access, not just at sink.start."""
    from app.team.evaluation_usage import evaluation_run_for_store
    run = evaluation_run_for_store(int(context.store_id))
    if run is not None:
        if context.evaluation_run_id not in (None,run):
            raise BudgetDenied('evaluation run conflict')
        context = context.model_copy(update=dict(cost_purpose='EVALUATION',evaluation_run_id=run))
    if context.cost_purpose == 'EVALUATION':
        return context, current_budget(context,model)
    if _budget.get() is not None:
        raise BudgetDenied('budgeted execution must have evaluation attribution')
    return context, None
