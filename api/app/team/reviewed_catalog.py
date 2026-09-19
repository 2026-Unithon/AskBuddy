"""Offline human-reviewed observation -> pinned catalog. Never installs or enables it."""
from dataclasses import replace
from app.contracts.hashing import digest
from app.learn.planner import decide
from app.learn.reviewed_semantics import ReviewedCatalog, apply_reviewed
from app.learn.semantic_proposals import proposal_input
from app.team.semantic_review import SemanticJudgment, semantic_report


def build_catalog(items, *, acceptance_reference):
    if not items or len(items)>500:
        raise ValueError('one to 500 explicitly reviewed inputs required')
    entries=[]
    searches=[]
    for item in items:
        search=item['search']
        row=item['observation']
        label=SemanticJudgment.model_validate(item['judgment'])
        semantic_report([row],[label.model_dump()])
        if (row['status']!='REVIEW_REQUIRED' or not label.semantic_correct or label.false_block
                or label.false_merge or label.citation_error or label.expected_action!=row['proposal']['plan']['action']):
            raise ValueError('explicit correct action/meaning/citation judgment required')
        payload=row['input']
        expected=proposal_input(search,store_id=int(search.snapshot.store_id),question=payload['question'],
            user_turns=tuple(payload['user_turns']))
        if expected!=payload:
            raise ValueError('current snapshot/candidates/input differ from reviewed observation')
        entries.append(dict(approval_id=item['approval_id'],store_id=search.snapshot.store_id,
            question=payload['question'],user_turns=payload['user_turns'],confirmed_slots=item['confirmed_slots'],
            proposal=row['proposal'],interpretation=item['interpretation'],reviewer=label.reviewer,
            review_reference=label.reason+'; observation='+row['row_hash']))
        searches.append(search)
    catalog=ReviewedCatalog(acceptance_reference=acceptance_reference,entries=entries)
    for search,entry in zip(searches,catalog.entries):
        baseline=decide(search,store_id=int(entry.store_id),question=entry.question)
        baseline=replace(baseline,confirmed_slots=entry.confirmed_slots)
        _,selected=apply_reviewed(search,store_id=int(entry.store_id),question=entry.question,
            user_turns=entry.user_turns,baseline=baseline,catalog=catalog,context_verified=True)
        # Offline consistency only. Runtime still requires authenticated live context.
        if selected!=entry.approval_id:
            raise ValueError('review is not applicable to the product admission path')
    data=catalog.model_dump(mode='json')
    return data,digest(data)
