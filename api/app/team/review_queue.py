"""Deterministic, pre-evaluation sampling for human review; no auto truth."""
from collections import defaultdict
from app.contracts.hashing import digest


def prepare_review_queue(review, *, limit=40):
    if type(limit) is not int or not 1<=limit<=200:
        raise ValueError('review limit must be 1..200')
    if review.get('schema_version')!='r_dev_review/v1' or review.get('split')!='dev':
        raise ValueError('dev review required')
    if digest({k:v for k,v in review.items() if k!='review_hash'})!=review.get('review_hash'):
        raise ValueError('altered review')
    groups=defaultdict(list)
    for row in review['cases']:
        label=row['source_label']
        # Balance source type, attribute and missing/explicit variant. These are
        # sampling strata only, not assertions about semantic applicability.
        key=(review['sources'][label['source_key']]['type'],label['attribute'],bool(label.get('variant')))
        groups[key].append(row)
    by_type=defaultdict(list)
    for key,rows in sorted(groups.items(),key=lambda item:str(item[0])):
        by_type[key[0]].append(sorted(rows,key=lambda row:row['meaning_id']))
    ordered=[by_type[kind][index] for index in range(max(map(len,by_type.values()),default=0))
             for kind in sorted(by_type) if index<len(by_type[kind])]
    selected=[]
    offset=0
    while len(selected)<limit:
        batch=[rows[offset] for rows in ordered if len(rows)>offset]
        if not batch:break
        selected.extend(batch[:limit-len(selected)])
        offset+=1
    if not selected:raise ValueError('empty review queue')
    judgments=[dict(meaning_id=row['meaning_id'],question=row['question_draft'],expected_action=None,
        must_have=None,applicability=None,conditions=None,exceptions=None,scope_reason=None,
        forbidden_claims=None,required_fact_revisions=None,required_raw_blocks=None,reviewer=None,reason=None) for row in selected]
    distinct_questions=len({' '.join(row['question_draft'].split()) for row in selected})
    result=dict(schema_version='r_review_queue/v1',review_hash=review['review_hash'],
        status='TEMPLATE_DRAFT',source_fact_count=len(review['cases']),
        requested_count=limit,draft_count=len(selected),distinct_question_draft_count=distinct_questions,
        minimum_question_target=30,minimum_draft_count_reached=distinct_questions>=30,
        reviewed_question_count=0,snapshot_coverage_verified=False,
        selected_meaning_ids=[row['meaning_id'] for row in selected],
        selection_reason='Before evaluation: source-type-first round-robin across attribute/variant strata; stable meaning-ID order.',
        judgments=judgments,source_rows=selected,evaluation_ready=False,semantic_accuracy=None,
        blockers=['HUMAN_QUESTION_ACTION_SCOPE_REVIEW','APPROVED_SNAPSHOT_AND_REVISION_MAPPING'])
    result['queue_hash']=digest(result)
    return result
