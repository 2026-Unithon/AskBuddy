"""Short replies that complete an approved menu name and a price question."""
import re

from app.reg.hybrid import normalize_query

PRICE_WORDS=('가격','금액','요금','판매가','price')

def menu_title(snapshot,text):
    q=normalize_query(text)
    matches={c.entity_id:c.title for c in snapshot.cards if normalize_query(c.title)==q}
    return next(iter(matches.values())) if len(matches)==1 else None

def price_pair(snapshot,first,second):
    for attribute,name in ((first,second),(second,first)):
        if normalize_query(attribute) in PRICE_WORDS:
            title=menu_title(snapshot,name)
            if title:return title
    return None

def is_price_reply(snapshot,stored,question):
    original=stored.context.original_question
    if not price_pair(snapshot,original,question):return False
    return stored.offered_slot==('predicate' if menu_title(snapshot,original) else 'entity')

def price_menu(snapshot,question):
    words=normalize_query(question).rstrip('?.!').split()
    if len(words)<2:return None
    if words[0] in PRICE_WORDS:return menu_title(snapshot,' '.join(words[1:]))
    if words[-1] in PRICE_WORDS:return menu_title(snapshot,' '.join(words[:-1]))
    return None

def states_menu_price(fact,title):
    """The approved text displayed to staff must itself state this menu's price."""
    if fact.predicate not in PRICE_WORDS or fact.polarity!='AFFIRM':return False
    subject=re.escape(normalize_query(title))
    label=r'(?:금액|가격|판매가|요금|price)'
    amount=r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)\s*원'
    return bool(re.fullmatch(rf'(?:{subject}\s*[:：]?\s*)?(?:{label}\s*[=:：]?\s*)?{amount}(?:입니다|이에요)?[.!]?',
        normalize_query(fact.assertion)))
