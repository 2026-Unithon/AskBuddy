"""Whole-span RAW quantity recognition; never create or approve a typed fact.

Only a single atomic, explicit-temperature statement is supported. Additional
text, conditions, competing cards or typed evidence make this path ineligible.
"""
import re
from app.reg.hybrid import normalize_query
from app.learn.semantic_grouping import quantity_question


def procedure_signature(question, title):
    """Whole-question procedural requests; keep temperature and task identity."""
    query=normalize_query(question)
    match=re.fullmatch(r'(?:(hot|ice)\s+)?'+re.escape(normalize_query(title))+
        r'(?:의)?\s+(준비|제조|청소|마감|오픈|보관)(?:는|은)?\s*'
        r'(?:어떻게\s*(?:해|하나요|하죠)|(?:방법|순서)\s*(?:알려줘|알려주세요))[.!?]*',query)
    return match.groups() if match else None


def raw_answer_reference(snapshot, *, entity, question, candidates):
    atomic=raw_quantity_reference(snapshot,entity=entity,question=question,candidates=candidates)
    if atomic:
        return atomic
    cards=[card for card in snapshot.cards if card.entity_id==entity]
    if len(cards)!=1 or any(fact.entity_id==entity for fact in snapshot.fact_revisions):
        return None
    card=cards[0]
    if len(card.blocks)!=1:
        return None
    block=card.blocks[0]
    if not block.raw_span_id or block.fact_revision_ids or (card.card_id,card.card_version_id,block.block_id) not in candidates:
        return None
    raw=next(span for span in snapshot.raw_spans if span.raw_span_id==block.raw_span_id)
    # An approved, explicit question-answer record carries its own exact
    # applicability. Never infer scope from an unrelated heading or first card.
    pair=re.fullmatch(r'질문: ([^\r\n]+)\r?\n답변: ([\s\S]+)',raw.text.strip())
    if pair:
        equivalent=(normalize_query(pair[1])==normalize_query(question) or
            (procedure_signature(question,card.title) is not None and
             procedure_signature(question,card.title)==procedure_signature(pair[1],card.title)))
        if not pair[2].strip() or not equivalent or re.search(r'(?:^|\n)\s*질문:',pair[2]):return None
    else:
        # An approved procedure heading supplies an explicit task binding.
        # Return the whole span including all warnings/conditions, never a step excerpt.
        signature=procedure_signature(question,card.title)
        if signature is None:return None
        temperature,task=signature
        heading=(f'{temperature} ' if temperature else '')+normalize_query(card.title)+' '+task
        heading_match=re.fullmatch(re.escape(heading)+r' (?:방법|절차|순서):\r?\n([\s\S]+)',normalize_query_lines(raw.text))
        if not heading_match or not heading_match[1].strip():return None
        if re.search(r'(?:^|\n)\s*(?:질문|답변):',heading_match[1]):return None
    if card.variant.temperature and not re.search(r'\b'+card.variant.temperature.lower()+r'\b',normalize_query(question)):
        return None
    if card.variant.size and normalize_query(card.variant.size) not in normalize_query(question).split():
        return None
    return card,block,'approved_qa',()


def normalize_query_lines(text):
    return '\n'.join(normalize_query(line) for line in text.strip().splitlines())


def raw_quantity_reference(snapshot, *, entity, question, candidates):
    cards=[card for card in snapshot.cards if card.entity_id==entity]
    if len(cards)!=1 or any(fact.entity_id==entity for fact in snapshot.fact_revisions):
        return None
    card=cards[0]
    if len(card.blocks)!=1:
        return None
    block=card.blocks[0]
    if not block.raw_span_id or block.fact_revision_ids or (card.card_id,card.card_version_id,block.block_id) not in candidates:
        return None
    raw=next(span for span in snapshot.raw_spans if span.raw_span_id==block.raw_span_id)
    pattern=(r'(HOT|ICE)\s+'+re.escape(card.title)+
        r'\s+(우유|물)\s+(\d+(?:\.\d+)?)\s*(ml|l|g|kg)(?:\s*넣는다)?[.]?')
    match=re.fullmatch(pattern,raw.text.strip(),flags=re.I)
    if not match:
        return None
    temperature=match[1].upper()
    # Card metadata must not contradict the complete RAW statement.
    if card.variant.size is not None or card.variant.temperature not in (None,temperature):
        return None
    predicate='milk_amount' if match[2]=='우유' else 'water_amount'
    if not quantity_question(question,titles=(card.title,),predicate=predicate):
        return None
    # Require literal HOT/ICE in the question. No omitted/default variant or
    # fuzzy temperature inference, even if only one variant was found.
    query=normalize_query(question)
    if re.search(r'아이스|핫|따뜻한|뜨거운|차가운',query):
        return None
    temps={item.upper() for item in re.findall(r'\b(?:hot|ice)\b',query)}
    if temps!={temperature}:
        return None
    return card,block,predicate,((temperature,None),)
