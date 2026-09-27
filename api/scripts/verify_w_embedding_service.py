"""일회용 PG에서 W 카드 임베딩 비용 귀속 검증.

옛 색인(card_embeddings)에 직접 쓰던 prepare_embedding·embed_card 는 2026-09-27 제거했다.
공개 카드 색인은 publish_cards → R 색인 준비 경로 하나다(verify_w_publication_flow 가 검증).
여기서는 남은 비용 귀속(card_usage_context)과 옛 쓰기 경로가 사라졌는지만 본다.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import asyncpg
import app.ingest.embed.service as service
import app.ingest.repository as ingest_repo
from app.db_session import ShortSession
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
        check("legacy card_embeddings writers are removed",
              not any(hasattr(service,n) for n in ("prepare_embedding","embed_card","PreparedEmbedding"))
              and not hasattr(ingest_repo,"upsert_embedding"))
        await observer.execute("create table knowledge_cards(card_id bigint primary key,store_id bigint,source_id bigint,title text,content text,is_verified boolean);"
                               "insert into knowledge_cards values(1,1,null,'예시','본문',true);")
        db=ShortSession(pool)
        context=await service.card_usage_context(db,1,1)
        check("owner-written card embeds as operating product cost",
              (context.stage,context.store_id,context.cost_phase,context.cost_purpose,context.source_id)
              ==("EMBED","1","OPERATING","PRODUCT",None))
        try:
            await service.card_usage_context(db,2,1)
        except LookupError:
            pass
        else:
            raise AssertionError("other store accessed")
        check("usage context rejects cross-store card lookup",True)
        check("short session returns connection",pool.get_idle_size()==1 and db.connection is None)
        print(f"{len(passed)}/{len(passed)} PASS PostgreSQL " + await observer.fetchval("show server_version"))
    finally:
        await observer.close()
        await pool.close()


if __name__=="__main__":
    asyncio.run(main())
