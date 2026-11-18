"""계획 10: 블록의 표시 줄 계약. 줄은 W 표시용이고 snapshot 에 싣지 않는다."""
import pytest

from app.contracts.card import CardBlock, DisplayLine


def test_line_must_cite_fact_of_its_block():
    with pytest.raises(ValueError):
        CardBlock(block_id="b1", kind="STEPS", order=1, fact_revision_ids=("1",),
                  lines=(DisplayLine(text="2샷", fact_revision_ids=("9",)),))


def test_snapshot_card_has_no_display_fields():
    from app.publish.content import snapshot_block_payload
    block = CardBlock(block_id="b1", kind="STEPS", order=1, fact_revision_ids=("1",), heading="HOT",
                      lines=(DisplayLine(text="2샷", fact_revision_ids=("1",)),))
    assert set(snapshot_block_payload(block)) == {"block_id", "kind", "order", "fact_revision_ids"}


def test_wire_dump_never_carries_display_fields():
    # 공개 snapshot 은 CardBlock 을 그대로 직렬화한다. 표시 칸이 끼면 R 계약이 바뀐다
    block = CardBlock(block_id="b1", kind="STEPS", order=1, fact_revision_ids=("1",), heading="HOT",
                      lines=(DisplayLine(text="2샷", fact_revision_ids=("1",)),))
    dumped = block.model_dump(mode="json")
    assert "heading" not in dumped and "lines" not in dumped
