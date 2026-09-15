"""R 운영 시나리오. W 추가자료/Storage 관측을 누락한 채 D21을 통과시키지 않는다."""
from decimal import Decimal
from app.usage.report import load_scenarios, judge_d21


def _amount(value):
    if value is None:
        return None
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("비용과 환율은 유한한 0 이상 값이어야 한다")
    return result


def operating_scenarios(*, read_cost_per_turn_usd, additional_ai_by_month=None,
                        storage_and_transfer_by_month=None, usd_krw=None,
                        rate_version=None, fx_version=None):
    """첫 달/안정기·추가 턴·저장 기간을 분리한 36개 가정. 실측 보고서가 아니다.

    read_cost_per_turn에는 QUERY+ANSWER+retry의 완전한 원가를 전달한다.
    원장의 known_cost를 완전 단가로 사용해서는 안 된다.
    """
    plan = load_scenarios()
    unit, fx = _amount(read_cost_per_turn_usd), _amount(usd_krw)
    if fx is not None and fx == 0:
        raise ValueError("환율은 0일 수 없다")
    rows = []
    for scenario in plan["scenarios"]:
        for month in plan["retention_forecast_months"]:
            daily_key = "questions_per_employee_day_first_month" if month == 1 else "questions_per_employee_day_stable"
            questions = Decimal(scenario["employees"]) * Decimal(str(scenario[daily_key])) * plan["calendar_days_assumption"]
            for profile in plan["clarification_profiles"]:
                turns = questions * (1 + Decimal(profile["additional_user_turns_per_question"]))
                read = turns * unit if unit is not None else None
                added = _amount((additional_ai_by_month or {}).get(month))
                storage = _amount((storage_and_transfer_by_month or {}).get(month))
                parts = [read, added, storage]
                total = sum(parts) if all(p is not None for p in parts) and rate_version else None
                krw = total * fx if total is not None and fx is not None and fx_version else None
                rows.append(dict(scenario=scenario["id"], month=month, profile=profile["id"],
                    base_questions=int(questions), user_turns=str(turns), read_cost_usd=str(read) if read is not None else None,
                    total_operating_krw=str(krw) if krw is not None else None,
                    decision=judge_d21(krw), rate_version=rate_version, fx_version=fx_version))
    return dict(schema_version="r_operating_scenarios/v1", status="PLANNING_NOT_OBSERVED", rows=rows)
