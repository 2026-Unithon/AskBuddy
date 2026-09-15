"""일회용 PG15에서 실제 W 준비/원장/연결/CAS 검증. 모델은 합성, pgvector는 별도다."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import asyncpg
from app.db_session import ShortSession
from app.ingest.embed.service import prepare_embedding, embed_card
from app.contracts.usage import UsageContext
from app.usage import DbUsageSink
from verify_r_answer_usage import DSN


async def main():
    pool=await asyncpg.create_pool(DSN,min_size=1,max_size=1)
    observer=await asyncpg.connect(DSN)
    passed=[]
    def check(name,ok):
        assert ok,name
        passed.append(name)
        print("PASS",name)
    try:
        await observer.execute("create table knowledge_cards(card_id bigint primary key,store_id bigint,title text,content text,is_verified boolean);"
                               "insert into knowledge_cards values(1,1,'예시','본문',false);")
        loop=asyncio.get_running_loop()
        def provider(**kwargs):
            count=asyncio.run_coroutine_threadsafe(observer.fetchval(
                "select count(*) from ai_usage_attempts where store_id=1 and logical_call_id='w-service-test' and status='STARTED'"),loop).result(timeout=2)
            assert count==1 and pool.get_idle_size()==1
            return NS(data=[NS(index=0,embedding=[1.])],usage=NS(prompt_tokens=7,total_tokens=7))
        settings=NS(openai_api_key="fake",embedding_model="synthetic",embedding_dim=1,embedding_timeout_seconds=30)
        client=NS(embeddings=NS(create=Mock(side_effect=provider)),close=Mock())
        db=ShortSession(pool)
        await db.fetchrow("select * from knowledge_cards where store_id=$1 and card_id=$2",1,1)
        context=UsageContext(store_id="1",cost_phase="REGISTRATION",cost_purpose="DEVELOPMENT",stage="EMBED",logical_call_id="w-service-test")
        with patch("app.ingest.embed.service.get_settings",return_value=settings), \
             patch("app.reg.embeddings.get_settings",return_value=settings), \
             patch("app.reg.embeddings.OpenAI",return_value=client):
            prepared=await prepare_embedding(1,"예시","본문",cost_phase="REGISTRATION",context=context,sink=DbUsageSink(pool))
        check("W service releases one-slot pool before provider and durable STARTED",client.embeddings.create.call_count==1)
        receipt=await observer.fetchrow("select stage,status,prompt_tokens from ai_usage_attempts where store_id=1 and logical_call_id='w-service-test'")
        check("W service records embedding usage",tuple(receipt)==("EMBED","SUCCEEDED",7))
        with patch("app.ingest.embed.service.repo.upsert_embedding") as write:
            try:
                async with db.transaction():
                    await db.execute("update knowledge_cards set is_verified=true,content='다른 내용' where store_id=1 and card_id=1")
                    await embed_card(db,1,1,prepared=prepared)
            except ValueError:
                pass
            else:
                raise AssertionError("stale content accepted")
            check("stale content rolls approval back without index write",not write.called and not await observer.fetchval("select is_verified from knowledge_cards where store_id=1 and card_id=1"))
            async with db.transaction():
                await db.execute("update knowledge_cards set is_verified=true where store_id=1 and card_id=1")
                await embed_card(db,1,1,prepared=prepared)
            check("matching approved content commits index boundary",write.call_count==1)
            try:
                async with db.transaction():
                    await embed_card(db,2,1,prepared=prepared)
            except LookupError:
                pass
            else:
                raise AssertionError("other store accessed")
            check("W service rejects cross-store card lookup",write.call_count==1)
        check("transaction exits return connection",pool.get_idle_size()==1 and db.connection is None)
        print(f"{len(passed)}/{len(passed)} PASS PostgreSQL " + await observer.fetchval("show server_version"))
    finally:
        await observer.close()
        await pool.close()


if __name__=="__main__":
    asyncio.run(main())
