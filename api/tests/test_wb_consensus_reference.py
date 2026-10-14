"""Phase B B-D8-4 — 다수결 참조 일반화. 같은 입력 → 같은 출력(레시피 회귀)."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1]
SCRIPT = API / "scripts" / "build_consensus_reference.py"
GOLDEN = API / "tests" / "fixtures" / "consensus_recipe_golden.json"
RUNS = ["C2 opus", "C1 opus", "C4 sonnet"]


def _load():
    spec = importlib.util.spec_from_file_location("bcr", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _f(attr, value, unit="", *, order=None, subject="음료Z"):
    return {"subject": subject, "variant": "ICE", "attribute": attr, "value": value,
            "unit": unit, "step_order": order, "polarity": "AFFIRM", "conditions": [],
            "original_assertion": f"{subject} {attr} {value}{unit}"}


def _groups():
    """같은 값 3표(샷), 2:1 로 갈린 값(물), 한 실행에만 있는 칸(토핑), 단위 철자 차이(shot)."""
    return {
        "C2 opus": [(1, _f("샷수", "2", "샷")), (1, _f("물량", "225", "ml")),
                    (1, _f("제조순서", "얼음 담기", order=1)), (2, _f("판매가", "4500", "원", subject="음료Y"))],
        "C1 opus": [(1, _f("샷수", "2", "샷")), (1, _f("물량", "220", "ml")),
                    (1, _f("제조순서", "얼음 담기", order=1)), (2, _f("판매가", "4500", "원", subject="음료Y"))],
        "C4 sonnet": [(1, _f("샷수", "2", "shot")), (1, _f("물량", "225", "ml")),
                      (1, _f("토핑", "시나몬"))],
    }


def _snapshot(module, **kw):
    agreed, contested = module.vote(_groups(), RUNS, quorum=2, **kw)
    facts = module.build_facts(agreed, "t", "syn", RUNS)
    return json.loads(json.dumps({"facts": facts, "contested": contested}, ensure_ascii=False))


def test_recipe_output_unchanged_after_refactor():
    assert _snapshot(_load()) == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_priority_argument_changes_representative():
    module = _load()
    agreed, _ = module.vote(_groups(), RUNS, quorum=2,
                            priority=["C4 sonnet", "C1 opus", "C2 opus"])
    assert {rep for (_, rep, _) in agreed.values()} == {"C4 sonnet", "C1 opus"}


def test_runs_file_keeps_old_values():
    priority, labels, dirs = _load().load_runs(API / "eval" / "consensus" / "recipe_runs.json")
    assert priority == ["C2 opus", "C1 opus", "C4 sonnet", "G3 sol", "G4 sol", "C3 sonnet"]
    assert set(labels) == set(dirs) == set(priority)
    # 출력 표기·실행 순서는 예전 RUN_LABEL 삽입 순서 그대로다
    assert list(labels) == ["C1 opus", "C2 opus", "C3 sonnet", "C4 sonnet", "G3 sol", "G4 sol"]
    assert list(dirs) == list(labels)


def test_core_key_uses_common_fields():
    key = _load().core_key({"attribute": "절차 단계", "value": "의자 내리기", "unit": "",
                            "polarity": "AFFIRM"})
    assert key == ("CORE", "절차단계", "의자내리기", "", "AFFIRM")


def test_unknown_logic_stops():
    res = subprocess.run([sys.executable, str(SCRIPT), "--logic", "PROCEDURE"],
                         capture_output=True, text=True)
    assert res.returncode != 0 and "키 함수" in res.stderr
