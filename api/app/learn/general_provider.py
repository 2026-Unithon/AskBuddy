"""Bounded structured calls for an accepted general-interpretation release."""
import asyncio
import json
from datetime import datetime, timezone
from app.config import get_settings
from app.contracts.hashing import digest
from app.learn.answer_usage import observe_answer
from app.reg.reranker import _BoundedSink
from app.team.evaluation_budget import BudgetDenied, provider_budget
from app.usage.recorder import attempt, NullSink


async def generate(prompt,*,schema,release,context,sink):
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
    prompt+='\nJSON schema:\n'+json.dumps(schema.model_json_schema(),ensure_ascii=False)
    if len(prompt.encode('utf-8'))>max_bytes:raise ValueError('prompt exceeds accepted byte limit')
    key=await budget.reserve(context,release.model) if budget else None
    client=None
    input_tokens=output_tokens=None
    try:
        client=genai.Client(api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
        async with attempt(_BoundedSink(sink,.2),context,model=release.model,prompt_hash=digest(prompt),
                config_hash=digest(dict(release=release.model_dump(mode='json'),max_output=max_output,temperature=0))) as rec:
            rec.measure_input(input_bytes=len(prompt.encode('utf-8')))
            counted=await client.aio.models.count_tokens(model=release.model,contents=prompt)
            if type(counted.total_tokens) is not int or not 0<=counted.total_tokens<=max_input:
                raise ValueError('input tokens exceed accepted limit or are unknown')
            response=await client.aio.models.generate_content(model=release.model,contents=prompt,
                config=types.GenerateContentConfig(response_mime_type='application/json',temperature=0,max_output_tokens=max_output))
            observe_answer(rec,response)
            meta=getattr(response,'usage_metadata',None)
            input_tokens=getattr(meta,'prompt_token_count',None)
            visible=getattr(meta,'candidates_token_count',None)
            thoughts=getattr(meta,'thoughts_token_count',None)
            if type(visible) is int and type(thoughts) is int:output_tokens=visible+thoughts
            if (type(input_tokens) is not int or type(output_tokens) is not int
                    or not 0<=input_tokens<=max_input or not 0<=output_tokens<=max_output):
                raise ValueError('usage unknown or exceeds accepted limit')
            return json.loads(response.text or '')
    finally:
        try:
            if key is not None:
                await asyncio.wait_for(budget.finish(key,input_tokens=input_tokens,output_tokens=output_tokens),.2)
        finally:
            if client is not None:
                try:await asyncio.wait_for(client.aio.aclose(),.2)
                except Exception:pass
