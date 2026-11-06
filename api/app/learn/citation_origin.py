"""인용 wire는 유지하고, 표시용 출처와 snapshot에 고정된 위치를 덧붙인다."""


def citation_origin(content, row) -> dict:
    source_id = str(row['source_id']) if row['source_id'] is not None else None
    owner_id = str(row['owner_answer_id']) if row['owner_answer_id'] is not None else None
    related_id = owner_id or (str(row['linked_owner_answer_id']) if row['linked_owner_answer_id'] is not None else None)
    source_type = row['source_type']
    kind = ('OWNER_ANSWER' if related_id else 'OWNER_TEXT' if source_type == 'OWNER_TEXT'
            else 'SOURCE' if source_type in ('VOICE', 'VIDEO', 'KAKAO', 'SCAN') else 'UNKNOWN')
    if row['raw_span_id'] is not None:
        origins = [next(s for s in content.raw_spans if s.raw_span_id == str(row['raw_span_id']))]
    else:
        fact = next(f for f in content.fact_revisions if f.fact_revision_id == str(row['fact_revision_id']))
        origins = [p for p in fact.provenance if p.source_id == source_id and p.owner_answer_id == owner_id]
    return dict(source_id=source_id, source_type=source_type, source_kind=kind,
        related_owner_answer_id=related_id,
        source_locations=[dict(occurrence_id=getattr(p, 'occurrence_id', None),
            locator=p.locator.model_dump(mode='json', exclude_none=True)) for p in origins])
