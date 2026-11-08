"""Recognize an explicit request to display one complete, approved card."""
import re
import unicodedata
from app.contracts.answer import SelectedBlock

def norm(text):
    return ' '.join(unicodedata.normalize('NFKC',text).casefold().split())

def requested_card(snapshot,question):
    q=norm(question)
    literal=re.fullmatch(r'(.+?)(?:의)?\s+카드\s*원문\s*(?:보여줘|보여주세요|보기)[.!?]?',q)
    procedure=re.fullmatch(r'(.+?)(?:의)?\s+(?:만드는\s*법(?:\s*(?:전부|전체))?(?:\s*(?:알려줘|알려주세요))?|순서(?:\s*(?:알려줘|알려주세요))?)[.!?]?',q)
    match=literal or procedure
    if not match:return None
    title=match[1].replace(' ','')
    cards=[c for c in snapshot.cards if norm(c.title).replace(' ','')==title]
    if len(cards)!=1:return None
    card=cards[0]
    if not literal and not any(b.kind=='STEPS' for b in card.blocks):return None
    return card

def whole_card_refs(card):
    return tuple(SelectedBlock(card_id=card.card_id,card_version_id=card.card_version_id,block_id=b.block_id,
        raw_span_id=b.raw_span_id,fact_revision_ids=b.fact_revision_ids) for b in sorted(card.blocks,key=lambda b:b.order))
