"""Closed numeric scope algebra. No inferred units, measurements or conversions."""
from dataclasses import dataclass
from decimal import Decimal
import re

from app.reg.hybrid import normalize_query

NUMBER=r'\d{1,12}(?:\.\d{1,6})?'
UNIT=r'(?:ml|kg|도|g|l|개|분)'
BOUND=rf'{NUMBER}{UNIT} (?:이상|미만|초과|이하)'
EXPRESSION=rf'[가-힣a-z]+(?: [가-힣a-z]+)* (?:{BOUND}(?: {BOUND})?|{NUMBER}{UNIT}(?:인 경우|일 때))'


@dataclass(frozen=True)
class NumericScope:
    axis:str
    unit:str
    lower:Decimal
    upper:Decimal
    lower_closed:bool=False
    upper_closed:bool=False

    @property
    def empty(self):
        return self.lower>self.upper or (self.lower==self.upper and not (self.lower_closed and self.upper_closed))

    def intersect(self,other):
        if (self.axis,self.unit)!=(other.axis,other.unit):return None
        lower,upper=max(self.lower,other.lower),min(self.upper,other.upper)
        lc=(self.lower_closed if self.lower>other.lower else other.lower_closed if self.lower<other.lower
            else self.lower_closed and other.lower_closed)
        uc=(self.upper_closed if self.upper<other.upper else other.upper_closed if self.upper>other.upper
            else self.upper_closed and other.upper_closed)
        return NumericScope(self.axis,self.unit,lower,upper,lc,uc)

    def entails(self,approved):
        overlap=self.intersect(approved)
        return not self.empty and not approved.empty and overlap==self


def parse_numeric_scope(text):
    value=normalize_query(text)
    match=re.fullmatch(rf'([가-힣a-z]+(?: [가-힣a-z]+)*) ({NUMBER})({UNIT})(인 경우|일 때)',value)
    if match:
        return NumericScope(match[1],match[3],Decimal(match[2]),Decimal(match[2]),True,True)
    match=re.fullmatch(rf'([가-힣a-z]+(?: [가-힣a-z]+)*) ({BOUND})(?: ({BOUND}))?',value)
    if not match:return None
    scope=None
    directions=[]
    for phrase in (match[2],match[3]):
        if phrase is None:continue
        bound=re.fullmatch(rf'({NUMBER})({UNIT}) (이상|미만|초과|이하)',phrase)
        number,unit,op=Decimal(bound[1]),bound[2],bound[3]
        lower=op in ('이상','초과')
        directions.append(lower)
        item=NumericScope(match[1],unit,number if lower else Decimal('-Infinity'),
            Decimal('Infinity') if lower else number,op=='이상',op=='이하')
        if scope is None:scope=item
        else:
            scope=scope.intersect(item)
            if scope is None:return None
    # Two-bound syntax must express a lower and upper bound on one unit.
    if len(directions)!=len(set(directions)) or scope.empty:return None
    return scope


def matching_numeric_prefix(question,approved):
    constraint=parse_numeric_scope(approved)
    if constraint is None:return None
    match=re.match('('+EXPRESSION+r')(?: 그리고 | 및 | )',question)
    if not match:return None
    supplied=parse_numeric_scope(match[1])
    if supplied is None or not supplied.entails(constraint):return None
    return question[match.end():],match[1]


def invalid_numeric_scope(text):
    return re.fullmatch(EXPRESSION,normalize_query(text)) is not None and parse_numeric_scope(text) is None
