"""계획 10 Task 6: 추출 프롬프트는 본문 한 벌 + 근거 위치 부분만 둘."""
from app.ingest.extract.gemini import render_facts_prompt


def _without_evidence(p: str) -> str:
    head = p.split("## 매장 용어 사전")[0]
    return head.replace(head[head.index("8. **근거 위치"):head.index("9. `local_ref`")], "")


def test_one_body_two_evidence_parts():
    a = render_facts_prompt(source_type="SCAN", text="x", glossary=[], locator_hints=False)
    b = render_facts_prompt(source_type="SCAN", text="x", glossary=[], locator_hints=True)
    assert _without_evidence(a) == _without_evidence(b)
    assert "[3쪽]" in b and "[3쪽]" not in a


def test_multi_menu_note_rule():
    assert "여러 메뉴에 걸친" in render_facts_prompt(source_type="SCAN", text="x", glossary=[])


def test_placeholders_filled():
    p = render_facts_prompt(source_type="SCAN", text="합성 자료 글", glossary=[], locator_hints=True)
    assert "{evidence_rules}" not in p and "{transcript}" not in p and "합성 자료 글" in p
