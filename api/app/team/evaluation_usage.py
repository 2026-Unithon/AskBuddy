"""격리 평가가 제품 월 원가에 섞이지 않도록 명시적으로 감싸는 sink."""
from app.contracts.usage import UsageAttempt, UsageContext
from contextlib import contextmanager
from contextvars import ContextVar

_evaluation_scope=ContextVar('r_evaluation_usage',default=None)


@contextmanager
def evaluation_usage_scope(*,store_id:int,evaluation_run_id:str):
    """Trusted in-process isolated harness only; never accept this from HTTP headers.

    ContextVar keeps concurrent ASGI requests/runs isolated and resets on failure.
    A remote HTTP harness must configure its isolated server separately.
    """
    validated=UsageContext(store_id=str(store_id),evaluation_run_id=evaluation_run_id,
        cost_phase='OPERATING',cost_purpose='EVALUATION',stage='QUERY',logical_call_id='scope')
    token=_evaluation_scope.set((int(validated.store_id),validated.evaluation_run_id))
    try:yield
    finally:_evaluation_scope.reset(token)


def request_usage_sink(pool,*,store_id:int):
    from app.usage import DbUsageSink
    sink=DbUsageSink(pool)
    scope=_evaluation_scope.get()
    if scope is None:return sink
    if scope[0]!=store_id:raise ValueError('evaluation request store mismatch')
    return EvaluationUsageSink(sink,store_id=store_id,evaluation_run_id=scope[1])


class EvaluationUsageSink:
    """운영 라우트의 전역 설정을 바꾸지 않는다. 격리 하네스가 생성/주입한다."""

    def __init__(self, sink, *, store_id: int, evaluation_run_id: str):
        self._scope=UsageContext(store_id=str(store_id),evaluation_run_id=evaluation_run_id,
            cost_phase='OPERATING',cost_purpose='EVALUATION',stage='QUERY',logical_call_id='scope')
        self._sink=sink
        self._started={}

    def _mapped(self, attempt):
        attempt=UsageAttempt.model_validate(attempt.model_dump())
        if attempt.context.store_id!=self._scope.store_id:
            raise ValueError('evaluation cannot cross stores')
        if attempt.context.evaluation_run_id not in (None,self._scope.evaluation_run_id):
            raise ValueError('evaluation run conflict')
        context=attempt.context.model_copy(update=dict(cost_purpose='EVALUATION',
            evaluation_run_id=self._scope.evaluation_run_id))
        return attempt.model_copy(update=dict(context=context))

    async def start(self, attempt):
        mapped=self._mapped(attempt)
        attempt_id=await self._sink.start(mapped)
        if type(attempt_id) is not int or attempt_id<=0 or attempt_id in self._started:
            raise ValueError('durable distinct usage attempt required')
        self._started[attempt_id]=mapped.context.model_dump()
        return attempt_id

    async def finalize(self, attempt_id, attempt, known_cost, cost, price_status):
        mapped=self._mapped(attempt)
        if self._started.get(attempt_id)!=mapped.context.model_dump():
            raise ValueError('foreign or changed usage attempt')
        await self._sink.finalize(attempt_id,mapped,known_cost,cost,price_status)
