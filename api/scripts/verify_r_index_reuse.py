"""공개된 전체 manifest의 블록 벡터 재사용과 cache miss 경계를 검증한다."""
from types import SimpleNamespace
from unittest.mock import patch

from app.reg.index_preparation import prepare_index, documents, _reusable_vectors
from app.reg.lexicon import approve_lexicon, LexiconEntry


async def verify(pool, admin, *, args):
    passed = []
    def check(name, ok):
        assert ok, name
        passed.append(name)
        print('PASS index reuse', name)
    content = args['content']
    docs = documents(content)
    calls = []
    async def embed(texts, **kwargs):
        assert pool.get_idle_size() == pool.get_size()
        calls.append(texts)
        return [[0.0, 1.0]+[0.0]*1534 for _ in texts]
    counter = 0
    async def prepare(candidate=content):
        nonlocal counter
        counter += 1
        return await prepare_index(pool, **dict(args, content=candidate,
            expected_publication_revision=7), idempotency_key=f'reuse-case-{counter}', embedder=embed)
    all_reused = await prepare()
    check('unchanged manifest has zero provider calls', all_reused.status == 'PREPARED' and not calls)
    vectors = await admin.fetch('''select embedding::text as vector from r_index_documents
        where store_id=$1 and prepared_id=$2''', args['store_id'], int(all_reused.prepared_id))
    check('complete manifest persisted with original vectors', len(vectors) == len(docs)
          and all(row['vector'].startswith('[1,0,') for row in vectors))
    changed_card = content.cards[0].model_copy(update=dict(title=content.cards[0].title+' 수정'))
    changed = content.model_copy(update=dict(cards=(changed_card, *content.cards[1:])))
    await prepare(changed)
    check('only changed retrieval text embedded', calls[-1] == [d.retrieval_text for d in documents(changed)
                                                              if d.card_id == changed_card.card_id])
    before = len(calls)
    await prepare(changed)
    check('unpublished preparation is not a reuse source', len(calls) == before+1)
    version_card = content.cards[0].model_copy(update=dict(card_version_id='999999'))
    await prepare(content.model_copy(update=dict(cards=(version_card, *content.cards[1:]))))
    check('same text new immutable version embeds again', len(calls[-1]) == len(version_card.blocks))
    await prepare(content.model_copy(update=dict(renderer_version='synthetic-renderer/v2')))
    check('renderer change misses every block', len(calls[-1]) == len(docs))
    glossary = await approve_lexicon(pool, store_id=args['store_id'], member_id=args['member_id'],
        entries=(LexiconEntry(layer='STORE', term='재사용 검증', variants=('합성 별칭',)),))
    await prepare(content.model_copy(update=dict(glossary_version=glossary)))
    check('glossary change misses every block', len(calls[-1]) == len(docs))
    with patch('app.reg.index_preparation.get_settings', return_value=SimpleNamespace(
            embedding_dim=1536, embedding_model='synthetic-new-model')):
        await prepare()
    check('model change misses every block', len(calls[-1]) == len(docs))
    with patch('app.reg.index_preparation.INDEX_CONFIG_VERSION', 'synthetic-config/v2'):
        await prepare()
    check('index configuration change misses every block', len(calls[-1]) == len(docs))
    cached = await _reusable_vectors(admin, store_id=args['store_id']+99999, content=content,
                                     model='synthetic-1536', docs=docs)
    check('another store cannot reuse vectors', not cached)
    # 같은 입력의 준비 사본이 늘어나도 공개 포인터는 바뀌지 않는다.
    check('preparation does not activate a new index', await admin.fetchval('''select count(*)
        from r_index_publications where store_id=$1''', args['store_id']) == 1)
    print(f'Verified {len(passed)} index reuse checks')
