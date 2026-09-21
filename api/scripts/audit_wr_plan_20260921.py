"""No database/provider calls: focused audit reproductions against real functions."""
import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.ingest import job_worker, job_repository, pipeline
from app.ingest.router import _job_detail
from pydantic import ValidationError


async def main():
    conn = AsyncMock()
    job = dict(job_id=2, title=None, status='SUCCEEDED', category_version=1,
               total_source_count=1, success_source_count=0, failed_source_count=0, card_count=3)
    source = dict(source_id=3, filename='synthetic.pdf', status='PARTIAL', card_count=3,
                  error_code='PARTIAL_EXTRACTION', error_message='synthetic failure')
    with patch.object(job_repository, 'get_job', AsyncMock(return_value=job)), \
         patch.object(job_repository, 'get_job_sources', AsyncMock(return_value=[source])):
        try:
            await _job_detail(conn, 1, 2)
        except ValidationError as exc:
            print(json.dumps({'case': 'partial_job_detail', 'actual': type(exc).__name__,
                              'field': exc.errors()[0]['loc'], 'error_type': exc.errors()[0]['type']}))
    conn.fetchrow.return_value = {
        'total': 1, 'succeeded': 0, 'failed': 0, 'no_result': 0, 'cards': 3,
    }
    status, cards = await job_worker._refresh_job(conn, 1, 2, final=True)
    print(json.dumps({'case': 'one_partial_source_with_cards', 'expected': 'PARTIAL',
                      'actual': status, 'cards': cards}))
    conn.fetch.return_value = []
    await job_repository.reset_retryable_sources(conn, 1, 2, include_no_result=True)
    retry_statuses = conn.fetch.call_args.args[3]
    print(json.dumps({'case': 'partial_retry', 'eligible_statuses': retry_statuses,
                      'partial_eligible': 'PARTIAL' in retry_statuses}))

    class Lease:
        async def __aenter__(self):
            pool.held = True
            return conn

        async def __aexit__(self, *args):
            pool.held = False

    class Pool:
        held = False
        def acquire(self):
            return Lease()

    pool = Pool()
    observations = []

    async def preprocess(*args, **kwargs):
        observations.append({'stage': 'preprocess', 'db_connection_held': pool.held})
        return 'synthetic', None, []

    async def extract(**kwargs):
        observations.append({'stage': 'extract', 'db_connection_held': pool.held})
        raise RuntimeError('audit stop before provider call')

    with patch.object(pipeline, 'get_pool', return_value=pool), \
         patch.object(pipeline.repo, 'get_source', AsyncMock(return_value={'source_type': 'TEXT'})), \
         patch.object(pipeline.repo, 'set_status', AsyncMock()), \
         patch.object(pipeline.repo, 'enabled_categories', AsyncMock(return_value=[])), \
         patch.object(pipeline.repo, 'glossary', AsyncMock(return_value=[])), \
         patch.object(pipeline, '_preprocess', preprocess), \
         patch.object(pipeline, '_extract_facts_all', extract), \
         patch.object(pipeline, '_mark_failed', AsyncMock()), \
         patch.object(pipeline.logger, 'exception'), \
         patch.object(pipeline.storage, 'workdir', return_value='audit-unused'), \
         patch.object(pipeline.shutil, 'rmtree'):
        await pipeline.process_source(1, 2)
    print(json.dumps({'case': 'connection_during_external_stages', 'observations': observations}))


asyncio.run(main())
