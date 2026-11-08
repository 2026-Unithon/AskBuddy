"""Recognize an explicit request to display one complete, approved card."""
import re
import unicodedata
from app.contracts.answer import SelectedBlock

def norm(text):
    return ' '.join(unicodedata.normalize('NFKC',text).casefold().split())

def requested_card(snapshot,question):
    q=norm(question)
    literal=re.fullmatch(r'(.+?)(?:의)?\s+카드\s*원문\s*(?:보여줘|보여주세요|보기)[.!?]?',q)
    # 같은 요청을 직원이 쓰는 여러 이름으로 받는다. 제목은 여전히 완전일치다.
    # '어떻게 만들어?' 같은 서술형 자유 질문은 넣지 않는다 — 그건 원문 열람을
    # 승인하지 않는다(test_r_raw_original.test_free_questions_do_not_gain_raw_authorization).
    recipe=r'(?:만드는\s*(?:법|방법)|제조\s*(?:법|방법|순서)|레시피|순서)'
    procedure=re.fullmatch(
        rf'(.+?)(?:의|는|은)?\s+{recipe}(?:\s*(?:전부|전체))?(?:\s*(?:알려줘|알려주세요|좀|보여줘))*[.!?]*',q)
    match=literal or procedure
    if not match:return None
    title=match[1].replace(' ','')
    cards=[c for c in snapshot.cards if norm(c.title).replace(' ','')==title]
    if not cards:
        # A topic transition is not part of the card name. Still require an
        # exact, unique title after it and an explicit request for the source.
        new_title=re.sub(r'^(?:이번엔|이번에는|다음은|다음으로)\s+', '',match[1]).replace(' ','')
        cards=[c for c in snapshot.cards if norm(c.title).replace(' ','')==new_title]
    if len(cards)!=1:return None
    card=cards[0]
    if not literal and not any(b.kind=='STEPS' for b in card.blocks):return None
    return card

def whole_card_refs(card):
    return tuple(SelectedBlock(card_id=card.card_id,card_version_id=card.card_version_id,block_id=b.block_id,
        raw_span_id=b.raw_span_id,fact_revision_ids=b.fact_revision_ids) for b in sorted(card.blocks,key=lambda b:b.order))
