import pytest

from app.team.lexicon_review import prepare_lexicon_review


def entry():
    return dict(layer='COMMON',term='에스프레소',variants=['에스프레쏘'],source='PUBLIC_WEB',
        source_url='https://example.org/terms',collected_at='2026-09-16',usage_basis='합성 허용 범위')


def test_duplicate_collection_never_auto_approves():
    report=prepare_lexicon_review([entry(),entry()],collection_reference='synthetic/source')
    assert report['unique_count']==1
    assert report['approval_version'] is None
    assert report['status']=='REVIEW_REQUIRED'


@pytest.mark.parametrize('fault',['source','recipe','ambiguity'])
def test_untraceable_or_recipe_or_ambiguous_terms_rejected(fault):
    rows=[entry()]
    if fault=='source':rows[0]['usage_basis']=None
    elif fault=='recipe':rows[0]['variants']=['우유 225ml']
    else:rows.append(dict(entry(),term='아메리카노'))
    with pytest.raises(ValueError): prepare_lexicon_review(rows,collection_reference='synthetic')
