"""Literal conditional questions: preserve all approved conjunction terms.

This supports an explicitly stated hypothetical scope, not inferred real-world
condition fulfillment. Explicit OR branches and same-unit numeric scopes are
supported; arbitrary paraphrases and inferred measurements remain unsupported.
"""
import re
from app.reg.hybrid import normalize_query
from app.learn.semantic_grouping import supported_question
from app.learn.numeric_scope import parse_numeric_scope,matching_numeric_prefix,invalid_numeric_scope


def exclusive_conditions(left,right):
    """Proof of disjoint literal branches, not a heuristic about related words."""
    def boolean(text):
        match=re.fullmatch(r'(.+?)(인 경우|이 아닌 경우|가 아닌 경우)',normalize_query(text))
        if not match or re.search(r'또는|그리고|및|아닌|[()]',match[1]):return None
        return match[1],match[2]=='인 경우'
    for a in left:
        for b in right:
            ba,bb=boolean(a),boolean(b)
            if ba and bb and ba[0]==bb[0] and ba[1]!=bb[1]:return True
            na,nb=parse_numeric_scope(a),parse_numeric_scope(b)
            overlap=na.intersect(nb) if na and nb else None
            if overlap is not None and overlap.empty:return True
    return False


def prerequisite_closure(snapshot, fact):
    result = {}
    pending = [fact.fact_revision_id]
    while pending:
        fid = pending.pop()
        if fid not in result:
            current = snapshot.fact(fid)
            result[fid] = current
            pending.extend(current.requires)
    return tuple(result.values())


def conditional_core(question, *, snapshot, fact, titles, sizes):
    result=conditional_match(question,snapshot=snapshot,fact=fact,titles=titles,sizes=sizes)
    return result[0] if result else None


def condition_alternatives(condition):
    """Only parenthesized OR defines a branch. Preserve all other clauses literally."""
    if condition.startswith('(') and condition.endswith(')'):
        parts=condition[1:-1].split(' 또는 ')
        if 2<=len(parts)<=3 and all(p and not re.search(r'[()]|그리고|또는|이거나',p) for p in parts):
            return tuple(re.escape(p) for p in parts)
    return (re.escape(condition),)


def conditional_match(question, *, snapshot, fact, titles, sizes):
    closure = prerequisite_closure(snapshot, fact)
    conditions = tuple(dict.fromkeys(normalize_query(condition) for item in closure for condition in item.conditions))
    exceptions = tuple(dict.fromkeys(normalize_query(exception) for item in closure for exception in item.exceptions))
    if len(conditions)+len(exceptions)>4 or any(not condition for condition in conditions):
        return None
    if any(invalid_numeric_scope(condition) for condition in conditions):return None
    terms=[(condition_alternatives(condition),condition) for condition in conditions]
    for exception in exceptions:
        # Only explicit exclusion clauses have a defined complement here.
        # An alternative amount, general warning or arbitrary negated sentence
        # cannot be turned into a false exception by keyword overlap.
        match=re.fullmatch(r'(.{1,120}?) (?:인 경우 )?제외',exception)
        if match is None or re.search(r'아닌|아니|아닐|않|없|또는|그리고|및|이거나|이면서|제외|\d',match[1]):
            return None
        terms.append(((re.escape(match[1])+r'(?:이|가) 아닌 경우',),None))
    q = normalize_query(question)
    cores = [(q,())] if not terms else []
    # Consume only matching prefixes instead of compiling all OR permutations.
    # Each recursion removes one of at most four complete clauses.
    def consume(rest,remaining,bindings):
        if not remaining:
            if any(exclusive_conditions((a,),(b,)) for index,a in enumerate(bindings) for b in bindings[index+1:]):
                return
            cores.append((rest,tuple(sorted(set(bindings)))))
            return
        for index,(alternatives,approved) in enumerate(remaining):
            numeric=matching_numeric_prefix(rest,approved) if approved else None
            if numeric:
                consume(numeric[0],remaining[:index]+remaining[index+1:],bindings+(numeric[1],))
            for term in alternatives:
                prefix=re.match('('+term+')'+r'(?: 그리고 | 및 | )',rest)
                if prefix:
                    consume(rest[prefix.end():],remaining[:index]+remaining[index+1:],bindings+(prefix[1],))
    if terms:consume(q,terms,())
    valid = {item for item in cores if supported_question(item[0],titles=titles,predicate=fact.predicate,sizes=sizes)}
    return next(iter(valid)) if len(valid)==1 else None
