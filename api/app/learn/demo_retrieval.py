"""An unavailable vector channel is not proof of missing store knowledge."""
import asyncio
from openai import APIConnectionError, APIStatusError
from app.errors import ApiError
from app.usage.repository import UsageWriteError
from app.team.evaluation_budget import BudgetDenied

def demo_active(settings):
    return bool(getattr(settings,'r_general_semantics_demo_enabled',False)
                and getattr(settings,'r_general_semantics_enabled',False))

async def retrieve(pool, *, store_id, question, embed, search_fn, timeout, allow_fallback):
    try:
        vectors=await asyncio.wait_for(embed(), timeout=timeout)
    except (UsageWriteError,BudgetDenied):
        raise
    except (TimeoutError,APIConnectionError,APIStatusError) as exc:
        transient=not isinstance(exc,APIStatusError) or exc.status_code in (408,429) or exc.status_code>=500
        if not (allow_fallback and transient):
            if isinstance(exc,TimeoutError): raise
            raise ApiError(503,'MODEL_UNAVAILABLE','질문 검색을 완료하지 못했습니다.',retryable=True) from exc
        search=await search_fn(pool,store_id=store_id,question=question,query_vector=None)
        if not search.candidates:
            raise ApiError(503,'MODEL_UNAVAILABLE','검색을 완료하지 못했습니다. 다시 시도해 주세요.',retryable=True) from exc
        return search,'LEXICAL_AFTER_EMBEDDING_FAILURE',type(exc).__name__
    except Exception as exc:
        raise ApiError(503,'MODEL_UNAVAILABLE','질문 검색을 완료하지 못했습니다.',retryable=True) from exc
    return await search_fn(pool,store_id=store_id,question=question,query_vector=vectors[0]),'HYBRID',None
