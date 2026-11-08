"""추출 프롬프트 규칙 1: 한 문장에서 여러 사실을 뽑아도 표 칸 이름은 남긴다(계획 7 Task 1).

계획 6 예시가 '재료=' 까지 떼어 '컵=20' 이 '20' 으로 저장됐다. 실제 모델로는 측정하지 않았다(사용자 지시).
"""
from pathlib import Path

import pytest

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
FILES = ["extract_facts.ko.txt", "extract_facts_locator.ko.txt"]


@pytest.mark.parametrize("name", FILES)
def test_table_cell_keeps_column_name(name):
    text = (PROMPTS / name).read_text(encoding="utf-8")
    assert "칸 이름=값" in text
    assert '맞음: "컵=20"' in text and '틀림: "20"' in text


@pytest.mark.parametrize("name", FILES)
def test_value_split_keeps_label(name):
    text = (PROMPTS / name).read_text(encoding="utf-8")
    assert '① "재료=레몬퓨레 1.5P"  ② "재료=슈가시럽 1P"' in text
    assert '① "레몬퓨레 1.5P"  ② "슈가시럽 1P"   (둘 다 order 없음)' not in text


@pytest.mark.parametrize("name", FILES)
def test_step_split_rule_still_present(name):
    text = (PROMPTS / name).read_text(encoding="utf-8")
    assert '틀림: ①②③ 모두 "제조순서=블랜더(재료,얼음) → 믹싱 → 토핑"' in text
