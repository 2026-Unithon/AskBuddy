"""Closed quantity-question grammar; never infer omitted conditions from similarity."""
from __future__ import annotations

import re
from app.learn.menu_context import PRICE_WORDS
from app.contracts.hashing import digest
from app.reg.hybrid import normalize_query

VERSION = "r-explicit-question/v4"


def supported_question(question: str, *, titles: tuple[str, ...], predicate: str,
                       sizes: tuple[str, ...] = ()) -> bool:
    if predicate in ('milk_amount','water_amount'):
        return quantity_question(question,titles=titles,predicate=predicate,sizes=sizes)
    request = {
        'location': r'(?:어디(?:에)?(?:\s*(?:있어|있나요|보관해|보관하나요))?|(?:보관\s*)?위치(?:는)?)',
        'price': r'(?:(?:가격|금액|요금|판매가)(?:은|이)?(?:\s*얼마(?:야|인가요)?)?|얼마(?:야|인가요)?|price)',
        'quantity': r'(?:수량(?:은)?|몇\s*개(?:야|인가요)?)',
    }.get('price' if predicate in PRICE_WORDS else predicate)
    if not titles:
        return False
    title = '(?:'+'|'.join(re.escape(normalize_query(t)) for t in titles)+')'
    variants = ['hot','ice','아이스','핫','따뜻한','뜨거운','차가운',*sizes]
    variant = '(?:'+'|'.join(re.escape(normalize_query(v)) for v in variants)+')'
    if request is None:
        # 닫힌 어휘 밖의 속성은 '속성 이름이 질문에 그대로 나올 때'만 지원한다.
        # 유사어 추정이 아니라 글자 일치이며, 대상·속성·규격·조사·맺음말 외의
        # 낱말이 남으면 지원하지 않는다. 그래야 기존 보수성이 유지된다.
        return explicit_attribute_question(question,title=title,variant=variant,predicate=predicate)
    if predicate in PRICE_WORDS and re.fullmatch(rf'{request}\s+{title}[.!?]*(?:\s+{variant}[.!?]*)*',normalize_query(question)):
        return True
    return re.fullmatch(rf'(?:{variant}\s+)*{title}(?:의|는|은)?\s+(?:{variant}\s+)*'
        rf'{request}[.!?]*(?:\s+{variant}[.!?]*)*',normalize_query(question)) is not None


CLOSING = r'(?:\s*(?:알려줘|알려주세요|알려줄래|뭐야|뭔가요|어떻게\s*돼|어떻게\s*되나요|좀))?'


def explicit_attribute_question(question: str, *, title: str, variant: str, predicate: str) -> bool:
    """`<대상> <속성>` 처럼 승인 속성 이름을 그대로 말한 요청만 인정한다.

    속성 이름은 W가 붙인 자유 문자열이라 미리 어휘를 정할 수 없다. 대신 질문에
    같은 글자가 있는지로만 판단하고, 남는 낱말이 있으면 지원하지 않는다.
    """
    # predicate 는 계약상 None 일 수 있다(extraction.py). 이름이 없으면 지원하지 않는다.
    name = normalize_query(predicate) if predicate else ''
    if len(name) < 2:
        return False
    attribute = re.escape(name).replace(r'\ ', r'\s*')
    return re.fullmatch(
        rf'(?:{variant}\s+)*{title}(?:의|는|은|에서|에)?\s+(?:{variant}\s+)*'
        rf'{attribute}(?:은|는|이|가|을|를)?{CLOSING}[.!?]*(?:\s+{variant}[.!?]*)*',
        normalize_query(question)) is not None


def quantity_question(question: str, *, titles: tuple[str, ...], predicate: str,
                      sizes: tuple[str, ...] = ()) -> bool:
    """Recognize the entire request, including a trailing clarification selection.

    This is intentionally not a general Korean intent classifier. Unrecognized
    modifiers (replacement, ratio, exception, etc.) must not disappear in R3.
    """
    ingredient = {"milk_amount": "우유|milk", "water_amount": "물|water"}.get(predicate)
    if ingredient is None or not titles:
        return False
    title = "(?:" + "|".join(re.escape(normalize_query(t)) for t in titles) + ")"
    variant = r"(?:hot|ice|아이스|핫|따뜻한|뜨거운|차가운)"
    if sizes:
        variant = "(?:" + variant + "|" + "|".join(re.escape(normalize_query(s)) for s in sizes) + ")"
    amount = r"(?:얼마나(?:\s*넣(?:어|나요|어요|어야\s*해))?|양(?:은|이)?(?:\s*얼마(?:야|인가요)?)?|몇\s*(?:ml|밀리리터|g|그램|리터)(?:\s*넣(?:어|나요|어요))?|용량)"
    pattern = (rf"(?:{variant}\s+)*{title}(?:의|에|는|은)?\s+"
               rf"(?:{variant}\s+)*(?:{ingredient})(?:의|은|는|을|를)?\s*{amount}"
               rf"[.!?]*(?:\s+{variant}[.!?]*)*")
    return re.fullmatch(pattern, normalize_query(question)) is not None


def explicit_context(snapshot, *, question: str, entity: str, predicate: str,
                     variants: tuple, has_context: bool) -> dict | None:
    if has_context or len(variants) != 1 or variants[0][0] not in ('HOT','ICE'):
        return None
    from app.learn.entity_names import entity_names
    titles = entity_names(snapshot, entity)
    facts = [f for f in snapshot.fact_revisions if f.entity_id == entity and f.predicate == predicate]
    if not facts:
        return None
    from app.learn.conditional_scope import conditional_match, prerequisite_closure
    sizes=tuple(sorted({f.variant.size for f in facts if f.variant.size}))
    if sizes and variants[0][1] not in sizes:
        return None
    scopes=set()
    for fact in facts:
        match=conditional_match(question,snapshot=snapshot,fact=fact,titles=titles,sizes=sizes)
        if match is None:
            continue
        closure=prerequisite_closure(snapshot,fact)
        scopes.add((tuple(sorted({condition for item in closure for condition in item.conditions})),
                    tuple(sorted({exception for item in closure for exception in item.exceptions})),match[1]))
    if len(scopes)!=1:
        return None
    conditions,exceptions,bindings=next(iter(scopes))
    return dict(version=VERSION, snapshot_id=snapshot.snapshot_id,
                knowledge_revision=snapshot.knowledge_revision, snapshot_hash=snapshot.snapshot_hash,
                entity=entity, predicate=predicate, temperature=variants[0][0],
                size=variants[0][1],conditions=list(conditions),exceptions=list(exceptions),
                scope_bindings=list(bindings),policy_scope='work_explicit')


def explicit_key(*, store_id: int, context: dict) -> str | None:
    required = {"version", "snapshot_id", "knowledge_revision", "snapshot_hash", "entity", "predicate", "temperature", "size", "conditions", "exceptions", "scope_bindings", "policy_scope"}
    if (set(context) != required or context.get("version") != VERSION
            or context.get("predicate") not in ("milk_amount", "water_amount",'location','price','quantity')
            or context.get("temperature") not in ("HOT", "ICE")
            or context.get('policy_scope') != 'work_explicit'
            or (context.get('size') is not None and (not isinstance(context['size'],str) or not context['size'].strip()))
            or any(not isinstance(context.get(k), str) or not context[k] for k in required-{'conditions','exceptions','scope_bindings','size'})
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", context["snapshot_hash"])):
        return None
    for field in ('conditions','exceptions','scope_bindings'):
        values=context[field]
        if (not isinstance(values,list) or any(not isinstance(value,str) or not value.strip() for value in values)
                or values!=sorted(set(values))):
            return None
    return digest(dict(store_id=store_id, **context))
