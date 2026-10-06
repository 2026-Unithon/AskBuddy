"""선택한 typed 수량만 Decimal로 계산한다. RAW에서 숫자를 추측하거나 정책을 해석하지 않는다."""
import re
from decimal import Decimal, localcontext
from typing import Literal
from pydantic import Field, model_validator
from app.contracts.common import Contract, EntityId
from app.contracts.validate import validate_answer_references


class Calculation(Contract):
    operator: Literal['ADD', 'SUBTRACT', 'SCALE']
    fact_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=2)
    count: int | None = Field(default=None, strict=True, ge=1, le=1000000)
    count_quote: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode='after')
    def shape(self):
        if self.operator == 'SCALE':
            if len(self.fact_ids) != 1 or self.count is None or self.count_quote is None:
                raise ValueError('scale requires one approved quantity and a quoted user count')
        elif len(self.fact_ids) != 2 or self.count is not None or self.count_quote is not None:
            raise ValueError('binary operation requires two approved quantities')
        if len(set(self.fact_ids)) != len(self.fact_ids):
            raise ValueError('duplicate operands')
        return self


# 정해진 차원 안의 환산만 허용한다. 가격/비율/단위당 의미는 별도 의미 검증 대상이다.
UNITS = {'ml': ('ml', '1'), 'l': ('ml', '1000'), 'g': ('g', '1'), 'kg': ('g', '1000'),
         '원': ('원', '1'), '개': ('개', '1'), '분': ('분', '1'), '시간': ('분', '60')}


def number(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def calculate(calculations, *, plan, snapshot, store_id: int, question: str, user_turns=()) -> tuple[str, ...]:
    if not calculations:
        return ()
    if plan.action != 'ANSWER' or len(calculations) > 8:
        raise ValueError('bounded answer calculations required')
    refs = validate_answer_references(plan, snapshot, store_id=str(store_id))
    lines = []
    with localcontext() as ctx:
        ctx.prec = 48
        for raw in calculations:
            calc = Calculation.model_validate(raw)
            values, units = [], []
            for fid in calc.fact_ids:
                if fid not in refs.fact_ids:
                    raise ValueError('calculation operand outside selected facts')
                fact = snapshot.fact(fid)
                quantity = fact.quantity
                if quantity is None or quantity.unit.lower() not in UNITS:
                    raise ValueError('unsupported quantity or unit')
                if fact.polarity != 'AFFIRM':
                    raise ValueError('negative assertion is not a numeric operand')
                value = Decimal(quantity.value)
                if not value.is_finite() or abs(value) > Decimal('1e15') or value.as_tuple().exponent < -8:
                    raise ValueError('quantity outside calculation bounds')
                unit, factor = UNITS[quantity.unit.lower()]
                values.append(value * Decimal(factor))
                units.append(unit)
            if len(set(units)) != 1:
                raise ValueError('incompatible quantity units')
            unit = units[0]
            if calc.operator == 'SCALE':
                if not any(calc.count_quote in turn for turn in (question, *user_turns)):
                    raise ValueError('count quote outside user input')
                # 문장 내 다른 숫자를 계수로 가져오지 못하도록 단위가 붙은 한 숫자만 허용한다.
                matches = re.findall(r'(?<![\d.,+-])(\d+)\s*(?:개|명|잔|건|배)(?![가-힣])', calc.count_quote)
                if matches != [str(calc.count)]:
                    raise ValueError('count does not match quoted user quantity')
                result = values[0] * calc.count
                expression = f'{number(values[0])}{unit} × {calc.count}'
            else:
                result = values[0] + values[1] if calc.operator == 'ADD' else values[0] - values[1]
                op = '+' if calc.operator == 'ADD' else '−'
                expression = f'{number(values[0])}{unit} {op} {number(values[1])}{unit}'
            if abs(result) > Decimal('1e21'):
                raise ValueError('calculation result outside bounds')
            lines.append(f'계산: {expression} = {number(result)}{unit}')
    return tuple(lines)
