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


@pytest.mark.parametrize("name", FILES)
def test_friendly_sentence_rule(name):
    # 2026-11-08 사용자: '원문 그대로'를 보이는 글에서 없앤다. 원문은 근거로만, 보이는 글은 정리한 문장
    text = (PROMPTS / name).read_text(encoding="utf-8")
    assert "`assertion`" in text and "사람이 읽기 좋게" in text
    assert "원문에 없는 숫자" in text
    assert '"우유가 많이 나가면 사장님께 말해 주세요. 사장님이 추가로 주문해요."' in text


@pytest.mark.parametrize("name", FILES)
def test_same_topic_same_subject(name):
    text = (PROMPTS / name).read_text(encoding="utf-8")
    assert "같은 대상은 같은 `subject`" in text
