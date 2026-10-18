"""Bounded structured calls for an accepted general-interpretation release."""
import asyncio
import json
from datetime import datetime, timezone
from app.config import get_settings
from app.contracts.hashing import digest
from app.learn.answer_usage import observe_answer
from app.learn.general_wire import response_schema
from app.reg.reranker import _BoundedSink
from app.team.evaluation_budget import BudgetDenied, provider_budget
from app.usage.recorder import attempt, NullSink


class IncompleteModelOutput(ValueError):
    """Usage is still recorded, but an incomplete generation is never parsed/repaired."""


def usage_tokens(meta):
    """Omitted zero thoughts are known only when the reported total reconciles.

    Never treat a missing usage object or an unexplained total as free usage.
    Keep the provider's raw metadata intact in the common ledger.
    """
    raw=meta if isinstance(meta,dict) else meta.model_dump(mode='json') if hasattr(meta,'model_dump') else vars(meta) if meta is not None else {}
    def number(key):
        value=raw.get(key)
        return value if type(value)is int and value>=0 else None
    inp=number('prompt_token_count');visible=number('candidates_token_count');thoughts=number('thoughts_token_count')
    if (raw.get('thoughts_token_count') is None and inp is not None and visible is not None
            and number('total_token_count')==inp+visible and raw.get('tool_use_prompt_token_count') in (None,0)):
        thoughts=0
    return inp,visible,thoughts


async def generate(prompt,*,schema,release,context,sink,calculation_fact_ids=None,question_quotes=None):
    from google import genai
    from google.genai import types
    settings=get_settings()
    if (context.stage!='ANSWER' or context.store_id!=release.store_id or sink is None
            or isinstance(sink,NullSink) or settings.gemini_model!=release.model
            or release.valid_until.tzinfo is None or datetime.now(timezone.utc)>=release.valid_until):
        raise ValueError('accepted model and durable ANSWER usage required')
    context,budget=provider_budget(context,release.model)
    max_input=release.max_input_tokens
    max_output=release.max_output_tokens
    max_bytes=release.max_prompt_bytes
    if budget:
        max_input=min(max_input,budget.policy.max_input_tokens)
        max_output=min(max_output,budget.policy.max_output_tokens)
        max_bytes=min(max_bytes,budget.policy.max_prompt_bytes)
    wire_schema=response_schema(schema,calculation_fact_ids=calculation_fact_ids,question_quotes=question_quotes,
        conclusions_enabled=release.response_style=='grounded_conclusion')
    schema_text=json.dumps(wire_schema,ensure_ascii=False,separators=(',',':'))
    # Developer API countTokens cannot accept generation_config. Count the
    # prompt plus its separately supplied schema, with headroom; actual provider
    # usage is checked again and overages halt the evaluation budget.
    counted_prompt=prompt+'\nJSON schema:\n'+schema_text
    prompt_bytes=len(counted_prompt.encode('utf-8'))
    if prompt_bytes>max_bytes:raise ValueError('prompt exceeds accepted byte limit')
    config=types.GenerateContentConfig(response_mime_type='application/json',response_json_schema=wire_schema,
        temperature=0,max_output_tokens=max_output,
        thinking_config=types.ThinkingConfig(thinking_level=release.thinking_level),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    key=await budget.reserve(context,release.model) if budget else None
    client=None
    input_tokens=output_tokens=None
    try:
        client=genai.Client(api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
        async with attempt(_BoundedSink(sink,.2),context,model=release.model,prompt_hash=digest(prompt),
                config_hash=digest(dict(release=release.model_dump(mode='json'),generation=config.model_dump(mode='json')))) as rec:
            rec.measure_input(input_bytes=prompt_bytes)
            # countTokens 는 생성과 별개의 왕복이다. 2026-10-15 유료 진단에서 단계마다
            # 2.3~2.9초, 한 턴 16.9초 중 5.2초를 여기서 썼다.
            #
            # 토큰 하나는 최소 1바이트를 먹으므로 **바이트 수가 토큰 수의 상한**이다.
            # 바이트로 센 상한이 같은 여유분까지 두고도 한도 안이면 정확한 수를 물어볼
            # 이유가 없다 — 어떤 값이 나와도 한도를 넘을 수 없다. 한도에 가까울 때만
            # 공급자에게 묻는다. 한도를 푸는 게 아니라 **같은 한도를 더 싸게** 지킨다.
            # 실제 사용량은 응답을 받은 뒤 다시 검사한다.
            if prompt_bytes+max(32,(prompt_bytes+9)//10)>max_input:
                counted=await client.aio.models.count_tokens(model=release.model,contents=counted_prompt)
                if (type(counted.total_tokens) is not int or counted.total_tokens<0
                        or counted.total_tokens+max(32,(counted.total_tokens+9)//10)>max_input):
                    raise ValueError('input tokens exceed accepted limit or are unknown')
            response=await client.aio.models.generate_content(model=release.model,contents=prompt,
                config=config)
            observe_answer(rec,response)
            meta=getattr(response,'usage_metadata',None)
            input_tokens,visible,thoughts=usage_tokens(meta)
            if type(visible) is int and type(thoughts) is int:output_tokens=visible+thoughts
            if (type(input_tokens) is not int or type(output_tokens) is not int
                    or not 0<=input_tokens<=max_input or not 0<=output_tokens<=max_output):
                raise ValueError('usage unknown or exceeds accepted limit')
            candidates=getattr(response,'candidates',None)
            if not candidates or len(candidates)!=1 or getattr(candidates[0],'finish_reason',None)!='STOP':
                raise IncompleteModelOutput('generation did not finish with STOP')
            return json.loads(response.text or '')
    finally:
        try:
            if key is not None:
                await asyncio.wait_for(budget.finish(key,input_tokens=input_tokens,output_tokens=output_tokens),.2)
        finally:
            if client is not None:
                try:await asyncio.wait_for(client.aio.aclose(),.2)
                except Exception:pass
