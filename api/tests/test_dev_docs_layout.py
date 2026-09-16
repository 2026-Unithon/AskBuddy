"""개발 문서 이동 뒤 런타임 원가 입력 경로가 끊기지 않는지 확인한다."""
from pathlib import Path

from app.usage.report import SCENARIOS_PATH, load_scenarios


def test_cost_scenarios_use_dev_docs():
    root = Path(__file__).resolve().parents[2]
    assert SCENARIOS_PATH == root / "docs" / "dev" / "c0_cost_scenarios.json"
    assert isinstance(load_scenarios(), dict)
