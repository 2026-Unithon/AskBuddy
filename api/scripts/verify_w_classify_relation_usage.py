"""PG15 일회용 MC0 DB용 W 분류/관계 검증. 기존 verify_r_answer_usage 이후 실행."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncpg
from app.categories.classifier import classify_cards
from app.contracts.usage import UsageContext
from app.db_session import ShortSession
from app.learn.knowledge_loop import build_knowledge_plan
from app.usage import DbUsageSink
from verify_r_answer_usage import DSN


async def main():
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=1)
    observer = await asyncpg.connect(DSN)
    passed = []
    def check(name, ok):
        assert ok, name
        passed.append(name)
        print("PASS", name)
    settings = NS(ingest_mode="real", gemini_api_key="fake", gemini_model="synthetic",
                  answer_mode="grounded_llm", retrieval_threshold=.35)
    try:
        await observer.execute("create table task_categories (store_id bigint, category_id bigint, "
            "category_name text, is_system boolean, deleted_at timestamptz, is_enabled boolean default true, sort_order int); "
            "insert into task_categories(store_id,category_id,category_name,is_system,sort_order) values "
            "(1,9,'기타',true,1),(2,19,'타 매장',true,1)")
        state = {"stage": "CLASSIFY", "text": '{"items":[{"card_id":11,"category_name":"기타"}]}'}
        async def provider(**kw):
            check("STARTED committed before " + state["stage"], await observer.fetchval(
                "select count(*) from ai_usage_attempts where store_id=1 and stage=$1 and status='STARTED'",
                state["stage"]) == 1)
            check("pool free during " + state["stage"], pool.get_idle_size() == 1)
            return NS(text=state["text"], usage_metadata=NS(prompt_token_count=12, candidates_token_count=3),
                      model_version="synthetic-response-model", response_id="w-db-response")
        client = NS(aio=NS(models=NS(generate_content=AsyncMock(side_effect=provider)), aclose=AsyncMock()), close=lambda: None)
        ctx = UsageContext(store_id="1", cost_phase="OPERATING", cost_purpose="DEVELOPMENT",
                           stage="CLASSIFY", operation_id="reclass:111", logical_call_id="w-db-classify")
        with patch("app.categories.classifier.get_settings", return_value=settings), \
             patch("google.genai.Client", return_value=client):
            await classify_cards([dict(card_id=11,title="업무 A",content="합성 업무")], ["기타"],
                                 usage_context=ctx, usage_sink=DbUsageSink(pool))
        row = await observer.fetchrow("select * from ai_usage_attempts where store_id=1 and logical_call_id='w-db-classify'")
        check("CLASSIFY final attribution and nullable price", row["stage"] == "CLASSIFY" and
            row["cost_purpose"] == "DEVELOPMENT" and row["prompt_tokens"] == 12 and
            row["status"] == "SUCCEEDED" and row["cost_usd"] is None)
        state.update(stage="RELATION", text="{broken")
        with patch("app.learn.knowledge_loop.get_settings", return_value=settings), \
             patch("app.deps.get_pool", return_value=pool), \
             patch("app.learn.knowledge_loop.find_owner_answer_candidates", AsyncMock(return_value=[])), \
             patch("google.genai.Client", return_value=client):
            result = await build_knowledge_plan(ShortSession(pool), 1, "업무 질문", "합성 답변")
        row = await observer.fetchrow("select * from ai_usage_attempts where store_id=1 and stage='RELATION'")
        check("runtime default sink records RELATION parse failure", row["status"] == "FAILED" and
              row["prompt_tokens"] == 12 and row["cost_phase"] == "OPERATING" and
              bool(row["operation_id"]) and not result.auto_publish)
        check("other store does not receive W receipts", await observer.fetchval(
            "select count(*) from ai_usage_attempts where store_id=2 and stage in ('CLASSIFY','RELATION')") == 0)
        print(f"{len(passed)}/{len(passed)} PASS PostgreSQL " + await observer.fetchval("show server_version"))
    finally:
        await pool.close()
        await observer.close()


if __name__ == "__main__":
    asyncio.run(main())
