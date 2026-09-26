"""격리 schema DB에서 실제 카드 저장/rollback/조립 복구를 검증한다. provider는 합성이다."""
import copy
import json
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import asyncpg

from app.ingest import pipeline, extract, recovery, job_repository
from app.ingest.schemas import ExtractedAssertion, ExtractedCard, ExtractedFact, ExtractionResult
from verify_w_partial_extraction import _seed, _new_source


async def verify(db, dsn):
    user, store, job = await _seed(db)
    source = await _new_source(db, store, user, 'VIDEO')
    await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) values($1,$2,$3,'QUEUED')", store, job, source)
    # 다른 매장은 동일 리소스 ID를 읽거나 바꿀 수 없다.
    _, other_store, _ = await _seed(db)
    try:
        await recovery.load(db, other_store, job, source)
    except recovery.RecoveryConflict:
        pass
    else:
        raise AssertionError('cross-store recovery read')
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    counts = dict(extract=0, assembly=0)
    phase = dict(fail_extract=True, fail_assembly=False)
    segments = [('first', []), ('second', [])]
    async def extract_fake(**kw):
        counts['extract'] += 1
        # max_size=1에서도 외부 호출 안의 receipt용 연결을 획득한다.
        async with pool.acquire() as c:
            assert await c.fetchval('select 1') == 1
        if kw['text'] == 'second' and phase['fail_extract']:
            raise RuntimeError('synthetic extraction failure')
        value = '10' if kw['text'] == 'first' else '20'
        return NS(assertions=[ExtractedAssertion(local_ref='f1', original_assertion=f'물 {value}ml',
            subject='음료Z', attribute='물', value=value, unit='ml', confidence=.9)], unresolved=[])
    async def assemble_fake(**kw):
        counts['assembly'] += 1
        if phase['fail_assembly']:
            raise RuntimeError('synthetic assembly failure')
        return ExtractionResult(cards=[ExtractedCard(category_name='기타', title='합성 카드', content=f["값"],
            confidence=.9, facts=[ExtractedFact(object_name='음료Z', attribute='물', value=f['값'],
            ref=f['ref'], confidence=.9)]) for f in kw['facts']])
    async def state():
        return await recovery.load(db, store, job, source)
    async def cards():
        return await db.fetchval('select count(*) from knowledge_cards where store_id=$1 and source_id=$2', store, source)
    async def run(**kw):
        return await pipeline.process_source(store, source, job_id=job, **kw)
    try:
        with ExitStack() as stack:
            for obj, name, replacement in [
                (pipeline, 'get_pool', lambda: pool),
                (pipeline, '_preprocess', AsyncMock(side_effect=lambda *a, **kw: ('source', [], segments))),
                (pipeline.shutil, 'rmtree', lambda *a, **kw: None),
                (extract, 'extract_facts', extract_fake), (extract, 'assemble_cards', assemble_fake),
            ]:
                stack.enter_context(patch.object(obj, name, replacement))
            await run()
            assert await cards() == 1
            committed = await state()
            assert committed['phase'] == 'COMMITTED'
            assert committed['outcome']['failed_segment_ids'] == ['seg2']

            # 누락된 최초 manifest는 임의 재구성하지 않는다.
            await db.execute('update ingest_job_sources set recovery_state=null where store_id=$1 and job_id=$2 and source_id=$3', store, job, source)
            before = counts.copy()
            assert await run(retry_segments=['seg2'], expected_segments_total=2) == pipeline.PARTIAL_RETRY_UNAVAILABLE
            assert counts == before and await cards() == 1
            async with db.transaction():
                await recovery.replace(db, store, job, source, None, committed)

            # 개수가 같은 내용 변경은 추출/조립을 호출하지 않는다.
            segments[1] = ('changed', [])
            assert await run(retry_segments=['seg2'], expected_segments_total=2) == pipeline.PARTIAL_RETRY_UNAVAILABLE
            assert counts == before and await cards() == 1
            segments[1] = ('second', [])

            # 추출 성공 + 조립 실패: 이전 카드와 조립 대기 사실을 보존한다.
            phase.update(fail_extract=False, fail_assembly=True)
            await run(retry_segments=['seg2'], expected_segments_total=2)
            pending = await state()
            assert pending['phase'] == 'EXTRACTED' and pending['outcome']['assertions']
            assert await cards() == 1
            assert await db.fetchval('select status from sources where store_id=$1 and source_id=$2', store, source) == 'FAILED'
            assert await db.fetchval('select failed_segment_ids from ingest_job_sources where store_id=$1 and job_id=$2 and source_id=$3', store, job, source) == ['seg2']
            extract_count = counts['extract']

            # 카드 저장 뒤 실패 구간 기록에서 DB 오류: 카드와 완료 상태가 같이 rollback.
            phase['fail_assembly'] = False
            original_record = pipeline._record_segment_failures
            async def fail_record(conn, *args, **kw):
                assert conn.is_in_transaction()
                await original_record(conn, *args, **kw)
                raise RuntimeError('synthetic failure after card insert')
            with patch.object(pipeline, '_record_segment_failures', fail_record):
                await run(retry_segments=['seg2'], expected_segments_total=2)
            assert await cards() == 1 and await state() == pending
            assert counts['extract'] == extract_count

            # 실패 source 재접수도 추출 복구본을 지우지 않는다.
            await db.execute("update ingest_job_sources set status='FAILED' where store_id=$1 and job_id=$2 and source_id=$3", store, job, source)
            assert await job_repository.reset_retryable_sources(db, store, job, include_no_result=True) == 1
            assert await state() == pending
            await run()
            assert await cards() == 2 and counts['extract'] == extract_count
            finished = await state()
            assert finished['phase'] == 'COMMITTED' and not finished['outcome']['failed_segment_ids']
            assert not finished['outcome']['assertions'] and not finished['ledger_ids']
            assert await db.fetchval('select segments_failed from ingest_job_sources where store_id=$1 and job_id=$2 and source_id=$3', store, job, source) == 0
            assert await db.fetchval('select count(*) from source_facts where store_id=$1 and source_id=$2', store, source) == 2
            before = counts.copy()
            await run()
            assert await cards() == 2 and counts == before
            try:
                async with db.transaction():
                    await recovery.replace(db, store, job, source, pending, finished)
            except recovery.RecoveryConflict:
                pass
            else:
                raise AssertionError('stale recovery accepted')
            invalid = copy.deepcopy(finished)
            invalid['phase'] = None
            try:
                async with db.transaction():
                    await db.execute('update ingest_job_sources set recovery_state=$4::jsonb where store_id=$1 and job_id=$2 and source_id=$3', store, job, source, json.dumps(invalid))
            except asyncpg.CheckViolationError:
                pass
            else:
                raise AssertionError('invalid recovery accepted')
        print('PASS W recovery: isolated store, single connection, layout drift, legacy guard, assembly resume, atomic rollback, replay, CAS, schema constraint')
    finally:
        await pool.close()
