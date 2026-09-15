"""일회용 PG15 별도 schema에서 새 판정과 기존 freeze를 실제 검증한다."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import asyncpg
from verify_r_answer_usage import DSN


async def main():
    db=await asyncpg.connect(DSN)
    try:
        await db.execute("create schema w_score_verify; set search_path=w_score_verify;"
                         "create table stores(store_id bigint primary key); create table users(user_id bigint primary key);"
                         "insert into stores values(1)")
        root=Path(__file__).resolve().parents[2]/"supabase/migrations"
        for name in ("20260914090000_extraction_eval.sql","20260917100000_w_score_undetermined.sql"):
            await db.execute((root/name).read_text(encoding="utf-8"))
        await db.execute("insert into extraction_runs(store_id,label,code_version,prompt_version,extract_model,stt_model,ingest_mode) "
                         "values(1,'synthetic','test','test','test','test','mock')")
        insert="insert into extraction_results(run_id,store_id,fact_id,subject,attribute,value,source_key,source_type,verdict) values(1,1,$1,'예시','시간','1분','s','SCAN',$2)"
        await db.execute(insert,"t","UNDETERMINED")
        print("PASS new UNDETERMINED verdict accepted")
        try:
            await db.execute(insert,"invalid","INVALID")
        except asyncpg.CheckViolationError:
            print("PASS unknown verdict rejected")
        else:
            raise AssertionError("invalid verdict accepted")
        for sql in ("update extraction_results set verdict='COVERED'", "delete from extraction_results"):
            try:
                await db.execute(sql)
            except asyncpg.RaiseError:
                print("PASS prior append-only result guard retained")
            else:
                raise AssertionError("result freeze bypassed")
        print("4/4 PASS PostgreSQL "+await db.fetchval("show server_version"))
    finally:
        await db.close()


if __name__=="__main__":
    asyncio.run(main())
