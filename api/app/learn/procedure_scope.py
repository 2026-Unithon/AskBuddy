"""Read a first step from approved procedure statements for explicitly named subjects."""
import re
from dataclasses import dataclass

from app.contracts.answer import SelectedBlock
from app.reg.hybrid import normalize_query
from app.learn.dialogue_history import _mentions


@dataclass(frozen=True)
class ProcedureScope:
    subjects: tuple[str, ...]
    temperature: str | None


@dataclass(frozen=True)
class Step:
    title: str
    temperature: str
    instruction: str
    ref: SelectedBlock


def _pair(question, snapshot):
    titles=tuple(dict.fromkeys(c.title for c in snapshot.cards))
    names=_mentions(question,titles)
    if len(names)!=2:return None
    pair=r'\s*(?:이?랑|하고|와|과|,|및)\s*'.join(re.escape(n) for n in names)
    match=re.fullmatch(r'\s*'+pair+r'(?:를|을|의|는|은)?\s*(.*)',question,re.I)
    if not match:return None
    return tuple(names),normalize_query(match[1])


def _comparison(question,snapshot):
    pair=_pair(question,snapshot)
    if not pair:return None
    names,request=pair
    # Consume the whole request so modifiers such as a substitution, allergy,
    # size, equipment failure, or a second question cannot disappear.
    pattern=(r'(?:둘\s*다\s*)?(?:(?:주문받았어|주문받았어요)[.,]?\s*)?'
        r'(?:승인된\s*카드\s*기준으로\s*)?(?:(hot|ice|아이스|핫)\s*(?:기준으로\s*)?)?'
        r'(?:제조(?:할\s*때|\s*(?:순서|과정)|법)|만들\s*때)(?:를|을|의|가)?\s*(?:헷갈리기\s*쉬운\s*)?'
        r'(?:(?:차이(?:점)?|다른\s*점)(?:를|을|가)?\s*(?:한\s*가지(?:만)?\s*)?(?:알려줘|알려주세요|뭐야)?'
        r'|비교해\s*(?:줘|주세요)|어떻게\s*달라(?:요)?)[?!.]*')
    match=re.fullmatch(pattern,request)
    if not match:return None
    return ProcedureScope(names,_temperature(match[1]))


def _temperature(label):
    return {'핫':'HOT','hot':'HOT','아이스':'ICE','ice':'ICE'}.get(label)


def procedure_scope(snapshot,question,previous=None):
    compare=_comparison(question,snapshot)
    if compare or previous is None:return compare
    prior=_comparison(previous,snapshot)
    if not prior:return None
    followup=re.fullmatch(r'(?:그럼|그러면)?\s*(첫|두)\s*번째\s*(?:음료|메뉴|제품|것)(?:만|를|을|는|은)?\s*'
        r'(?:(hot|ice|아이스|핫)\s*(?:기준으로\s*)?)?(?:만들\s*때(?:는)?\s*)?'
        r'(?:뭘\s*먼저\s*해야\s*(?:해|하나요)|뭐부터\s*(?:시작해|시작하나요|해)|'
        r'첫\s*단계(?:는|가)?\s*(?:뭐야|뭔가요)?)[?.!]*',
        normalize_query(question))
    if not followup:return None
    title=prior.subjects[0 if followup[1]=='첫' else 1]
    return ProcedureScope((title,),_temperature(followup[2]) or prior.temperature)


def _steps_for(snapshot,title):
    cards=[card for card in snapshot.cards if card.title==title]
    if len(cards)!=1:return {}
    card=cards[0]
    if any(c.entity_id==card.entity_id and c.card_id!=card.card_id for c in snapshot.cards):return {}
    steps={}
    representatives={}
    for block in card.blocks:
        for fid in block.fact_revision_ids:
            fact=snapshot.fact(fid)
            if (fact.predicate or '').replace(' ','')!='제조순서':continue
            temp=fact.variant.temperature
            if (temp not in ('HOT','ICE') or fact.variant.size or fact.conditions or fact.exceptions
                    or fact.polarity!='AFFIRM' or (fact.subject and fact.subject!=title)):
                return {}
            # Quote only an explicit ordered list. Each applicable revision
            # must agree, even if it was not a top-ranked vector candidate.
            match=re.fullmatch(r'제조\s*순서\s*[=:：]\s*(.+?)\s*(?:→|->)\s*\S.*',fact.assertion)
            if not match:return {}
            first=match[1].strip()
            if not first or (temp in steps and steps[temp]!=first):return {}
            steps[temp]=first
            if not fact.requires and temp not in representatives:
                ref=SelectedBlock(card_id=card.card_id,card_version_id=card.card_version_id,
                                  block_id=block.block_id,fact_revision_ids=(fid,))
                representatives[temp]=Step(title,temp,first,ref)
    return representatives if representatives.keys()==steps.keys() else {}


def approved_first_steps(snapshot,scope):
    groups=[_steps_for(snapshot,title) for title in scope.subjects]
    if not all(groups):return ()
    temps=(scope.temperature,) if scope.temperature else ('ICE','HOT')
    if len(groups)==2:
        for temp in temps:
            if all(temp in g for g in groups) and groups[0][temp].instruction!=groups[1][temp].instruction:
                return tuple(g[temp] for g in groups)
        return ()
    return tuple(groups[0][t] for t in temps if t in groups[0])


def step_refs(snapshot,steps):
    groups={}
    for step in steps:
        ref=step.ref
        key=(ref.card_id,ref.card_version_id,ref.block_id)
        groups.setdefault(key,[]).extend(ref.fact_revision_ids)
    result=[]
    for (cid,version,bid),ids in groups.items():
        block=next(b for b in snapshot.card(cid).blocks if b.block_id==bid)
        ordered=sorted((i for i in block.fact_revision_ids if i in ids),key=lambda i:snapshot.fact(i).order or 0)
        result.append(SelectedBlock(card_id=cid,card_version_id=version,block_id=bid,fact_revision_ids=tuple(ordered)))
    return tuple(result)


def step_lines(steps,citations):
    comparing=len({s.title for s in steps})==2
    intro=(f'{steps[0].temperature} 기준으로 두 메뉴의 첫 단계가 달라요.' if comparing
           else f'{steps[0].title}의 승인된 제조 순서예요.')
    lines=[intro]
    for step in steps:
        n=next(i for i,c in enumerate(citations,1) if c.fact_revision_id==step.ref.fact_revision_ids[0])
        label=step.title if comparing else step.temperature
        lines.append(f'{label} · 첫 단계: {step.instruction} [출처 {n}]')
    return lines
