"""Cite approved, ordered operating instructions for bounded staff questions."""
import re
from dataclasses import dataclass

from app.contracts.answer import SelectedBlock
from app.reg.hybrid import normalize_query


def compact(text):
    return normalize_query(text).replace(' ', '').strip().rstrip('?!。.！')


OPEN_ORDER = re.compile(
    r'(?:(?P<solo>혼자오픈하는첫근무(?:예요|에요|야))[.,]?)?'
    r'(?:문열기전에|오픈(?:준비)?(?:할때|할때는)?|개점전에)?'
    r'(?:(?P<pair>시재(?:와|랑)비품|비품(?:과|이랑)시재)중)?'
    r'(?:(?:무엇을|뭘)먼저확인(?:해|해요|하나요|해야해)|뭐부터확인(?:해|해요|하나요)|'
    r'준비순서(?:를)?(?:알려줘|알려주세요)?|순서(?:를)?(?:알려줘|알려주세요)?)')
REFUND_REQUEST = re.compile(
    r'(?:(?:이|해당)?주문(?:을|의)?|한건을?)?환불'
    r'(?:하려면어떻게(?:처리)?(?:해|하나요|해야해)|은?어떻게(?:처리)?(?:해|하나요)|'
    r'(?:처리)?(?:절차|방법|순서)(?:를)?(?:알려줘|알려주세요)?|'
    r'(?P<first>할때(?:무엇을|뭘)먼저확인(?:해|하나요)|공통(?:절차|단계)(?:만)?(?:알려줘)?))')
CHANNEL_DETAIL = re.compile(
    r'(?P<channel>배달앱|매장직접|매장pos)(?:(?:으로|에서)?결제(?:한주문)?|주문)?'
    r'(?:이야|이에요|예요|했어요|했어|이고|인데)?'
    r'(?P<noreceipt>(?:종이)?영수증(?:이|은)?없(?:어|어요))?')
CHANNEL_QUESTION = '배달앱 결제인가요, 매장 직접 결제인가요?'


@dataclass(frozen=True)
class Guidance:
    refs: tuple[SelectedBlock, ...]
    followup: str | None = None
    previous: str | None = None


def _refund_request(snapshot, text):
    # Only discard a complete order introduction containing two published titles.
    if '.' in text:
        intro, text = text.split('.', 1)
        titles = {compact(card.title) for card in snapshot.cards}
        orders = intro.removesuffix('주문이하나씩있어')
        if orders == intro or not any(orders.startswith(title + join) and
                                      orders[len(title + join):] in titles
                                      for title in titles for join in ('랑', '이랑', '와', '과', '하고')):
            return None
    return REFUND_REQUEST.fullmatch(text)


def _rows(snapshot, titles):
    cards = [c for c in snapshot.cards if compact(c.title) in titles]
    if len(cards) != 1:
        return []
    card = cards[0]
    return [(card, block, snapshot.fact(fid)) for block in card.blocks for fid in block.fact_revision_ids]


def _one(rows, matches, *, conditions=()):
    choices = [row for row in rows if matches(row[2])]
    if len(choices) != 1:
        return None
    fact = choices[0][2]
    if (fact.polarity != 'AFFIRM' or fact.variant.temperature or fact.variant.size or fact.exceptions
            or tuple(map(compact, fact.conditions)) != conditions):
        return None
    return choices[0]


def _guidance(rows, *, followup=None, previous=None):
    blocks = {}
    seen = set()
    for card, block, fact in rows:
        if not set(fact.requires) <= seen:
            return None
        seen.add(fact.fact_revision_id)
        blocks.setdefault((card.card_id, card.card_version_id, block.block_id), []).append(fact.fact_revision_id)
    refs = tuple(SelectedBlock(card_id=c, card_version_id=v, block_id=b, fact_revision_ids=tuple(ids))
                 for (c, v, b), ids in blocks.items())
    return Guidance(refs, followup, previous)


def _opening(snapshot, text):
    match = OPEN_ORDER.fullmatch(text)
    if not match or not re.search('오픈|문열기|개점', text):
        return None
    rows = _rows(snapshot, {'오픈준비', '개점준비'})
    steps = [_one(rows, lambda fact: fact.order == order) for order in (1, 2)]
    if not all(steps):
        return None
    if match['pair'] and not all(any(term in step[2].assertion for step in steps) for term in ('시재', '비품')):
        return None
    if match['solo']:
        scope = _one(_rows(snapshot, {'오픈준비순서', '개점준비순서'}),
                     lambda f: compact(f.predicate or '') == '적용범위',
                     conditions=('혼자오픈하는첫근무인경우',))
        if not scope or not re.search(r'같은순서(?:입니다|예요|다)?$', compact(scope[2].assertion)):
            return None
        steps.append(scope)
    return _guidance(steps)


def resolve_guidance(snapshot, question, previous=None):
    text = compact(question)
    opening = _opening(snapshot, text)
    if opening:
        return opening
    request = _refund_request(snapshot, text)
    detail = CHANNEL_DETAIL.fullmatch(text)
    channel_prefix = re.match(r'(.+?(?:인데|이고|했는데|이에요[.]|예요[.]))(.+)', text)
    if channel_prefix and _refund_request(snapshot, channel_prefix[2]):
        detail = CHANNEL_DETAIL.fullmatch(channel_prefix[1].rstrip('.').removesuffix('했는데'))
    else:
        channel_prefix = None
    prior = previous if detail and previous and _refund_request(snapshot, compact(previous)) else None
    if not request and not (detail and (prior or channel_prefix)):
        return None
    rows = _rows(snapshot, {'주문환불', '환불절차', '환불처리'})
    common = _one(rows, lambda f: f.order == 1)
    if not common or compact(common[2].predicate or '') not in {'사전확인', '사전확인사항', '공통절차', '공통단계'}:
        return None
    def branch(prefix):
        return [row for row in rows if row[2].order == 2 and compact(row[2].assertion).startswith(prefix)
                and common[2].fact_revision_id in row[2].requires]
    app = branch('배달앱')
    pos = branch('매장직접결제')
    # A receipt-specific instruction remains explicitly conditional in the reply.
    app_step = _one(app, lambda f: True) or _one(app, lambda f: True, conditions=('종이영수증이없는경우',))
    pos_step = _one(pos, lambda f: True)
    if request:
        followup = CHANNEL_QUESTION if app_step and pos_step and not request['first'] else None
        return _guidance([common], followup=followup)
    is_app = detail['channel'] == '배달앱'
    step = app_step if is_app else pos_step
    if not is_app and detail['noreceipt']:
        return None
    if not step:
        return None
    return _guidance([common, step], previous=prior if not channel_prefix else None)


def guidance_lines(guidance, snapshot, citations, owner_sources=None):
    lines = []
    for ref in guidance.refs:
        for fid in ref.fact_revision_ids:
            fact = snapshot.fact(fid)
            n, citation = next((i, c) for i, c in enumerate(citations, 1) if c.fact_revision_id == fid)
            owner = citation.owner_answer_id or (owner_sources or {}).get(citation.source_id)
            label = f'점주 답변 {owner} · ' if owner else ''
            lines.append(' '.join((*fact.conditions, fact.assertion, *fact.exceptions, f'[{label}출처 {n}]')))
    if guidance.followup:
        lines.append(guidance.followup)
    return lines
