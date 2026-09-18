import json
from unittest.mock import AsyncMock, patch
import pytest
from app.team.lexicon_review import collect_lexicon_review, approve_lexicon_review


def entry():
    return dict(layer='STORE', term='라테', variants=['라떼'], source='OWNER')


def test_import_is_idempotent_and_preserves_human_edits(tmp_path):
    review = collect_lexicon_review(tmp_path, [entry(), entry()], collection_reference='synthetic-observation-1')
    assert review['input_count'] == 2 and review['unique_count'] == 1
    assert collect_lexicon_review(tmp_path, [entry(), entry()], collection_reference='synthetic-observation-1') == review
    target = next(tmp_path.iterdir())
    target.write_text(json.dumps(dict(review, status='EDITED')), encoding='utf-8')
    with pytest.raises(ValueError):
        collect_lexicon_review(tmp_path, [entry(), entry()], collection_reference='synthetic-observation-1')


@pytest.mark.asyncio
async def test_approval_binds_review_and_delegates_owner_authorization(tmp_path):
    review = collect_lexicon_review(tmp_path, [entry()], collection_reference='synthetic-observation-1')
    with patch('app.reg.lexicon.approve_lexicon', AsyncMock(return_value='rlex:synthetic')) as approve:
        version = await approve_lexicon_review(None, store_id=1, member_id=2, review=review, expected_hash=review['review_hash'])
        assert version == 'rlex:synthetic' and approve.call_args.kwargs['member_id'] == 2
        review['entries'][0]['term'] = '모카'
        with pytest.raises(ValueError):
            await approve_lexicon_review(None, store_id=1, member_id=2, review=review, expected_hash=review['review_hash'])
        assert approve.await_count == 1


def test_public_sources_need_real_provenance(tmp_path):
    with pytest.raises(ValueError):
        collect_lexicon_review(tmp_path, [dict(entry(), source='PUBLIC_WEB')], collection_reference='synthetic')
