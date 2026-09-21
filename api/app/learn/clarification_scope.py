"""Server choice sets for the bounded entity/temperature/size extension."""


def validate_options(search, *, plan, slots, entity_id=None, predicate=None):
    attr = plan.clarification_slot
    if attr not in ('entity', 'temperature', 'size') or slots.get(attr):
        raise ValueError('unsupported or already confirmed clarification')
    snap = search.snapshot
    cards = {c.card_id:snap.card(c.card_id) for c in search.candidates}
    if attr == 'entity':
        identities = {}
        for card in cards.values():
            identities.setdefault(card.title, set()).add(card.entity_id)
        if any(len(ids) != 1 for ids in identities.values()):
            raise ValueError('entity titles are ambiguous')
        if len({c.entity_id for c in cards.values()}) < 2:
            raise ValueError('distinct entity choices required')
        options = set(identities)
    else:
        cards = {k:c for k,c in cards.items() if c.entity_id == entity_id}
        if not cards or not predicate:
            raise ValueError('reviewed entity and predicate required')
        facts = [snap.fact(fid) for c in cards.values() for b in c.blocks for fid in b.fact_revision_ids
            if snap.fact(fid).predicate == predicate]
        other = 'size' if attr == 'temperature' else 'temperature'
        facts = [f for f in facts if not slots.get(other) or getattr(f.variant, other) == slots[other]]
        options = {getattr(f.variant, attr) for f in facts} - {None}
    if len(options) < 2 or set(plan.allowed_options) != options or len(plan.allowed_options) != len(options):
        raise ValueError('invented, duplicate or incomplete clarification options')
