"""W3b — 사실 카드 편집 요청·응답 스키마와 설정 기본값."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.cards.fact_edit_schemas import (
    EditAdd,
    EditKeep,
    EditModify,
    FactEditRequest,
    FactFields,
    FactParseRequest,
)
from app.cards.schemas import CardDetail
from app.config import Settings


def _fields(**kw):
    return {"sentence": "음료Z 샷은 2샷", **kw}


def test_fact_fields_sentence_blank_rejected():
    with pytest.raises(ValidationError):
        FactFields(sentence="   ")


def test_fact_fields_empty_value_and_unit_become_none():
    f = FactFields(sentence="a", value="  ", unit="")
    assert f.value is None and f.unit is None


def test_fact_fields_size_blank_is_none():
    assert FactFields(sentence="a", variant={"size": " "}).variant.size is None


def test_fact_fields_conditions_stripped_and_empty_dropped():
    f = FactFields(sentence="a", conditions=["  a ", "", "b"], exceptions=[" ", "c "])
    assert f.conditions == ["a", "b"] and f.exceptions == ["c"]


def test_fact_fields_condition_item_too_long():
    with pytest.raises(ValidationError):
        FactFields(sentence="a", conditions=["x" * 201])


def test_fact_fields_step_order_zero_rejected():
    with pytest.raises(ValidationError):
        FactFields(sentence="a", step_order=0)


def _edit(items, **kw):
    return {
        "expected_version_id": 1,
        "idempotency_key": "key-12345678",
        "blocks": [{"kind": "NOTES", "items": items}],
        **kw,
    }


def test_edit_item_discriminated_by_op():
    req = FactEditRequest(**_edit([
        {"op": "KEEP", "fact_revision_id": 1},
        {"op": "MODIFY", "fact_revision_id": 2, "fact": _fields()},
        {"op": "ADD", "client_ref": "p1", "fact": _fields()},
    ]))
    kinds = [type(i) for i in req.blocks[0].items]
    assert kinds == [EditKeep, EditModify, EditAdd]


def test_edit_item_unknown_op_rejected():
    with pytest.raises(ValidationError):
        FactEditRequest(**_edit([{"op": "DROP", "fact_revision_id": 1}]))


def test_client_ref_with_space_rejected():
    with pytest.raises(ValidationError):
        FactEditRequest(**_edit([{"op": "ADD", "client_ref": "a b", "fact": _fields()}]))


def test_idempotency_key_too_short():
    with pytest.raises(ValidationError):
        FactEditRequest(**{**_edit([{"op": "KEEP", "fact_revision_id": 1}]), "idempotency_key": "a" * 7})


def test_too_many_blocks():
    block = {"kind": "NOTES", "items": [{"op": "KEEP", "fact_revision_id": 1}]}
    with pytest.raises(ValidationError):
        FactEditRequest(expected_version_id=1, idempotency_key="key-12345678", blocks=[block] * 21)


def test_block_without_items_rejected():
    with pytest.raises(ValidationError):
        FactEditRequest(expected_version_id=1, idempotency_key="key-12345678",
                        blocks=[{"kind": "NOTES", "items": []}])


def test_empty_blocks_allowed():
    assert FactEditRequest(expected_version_id=1, idempotency_key="key-12345678").blocks == []


def test_parse_modify_requires_base():
    with pytest.raises(ValidationError):
        FactParseRequest(text="a", mode="MODIFY")


def test_parse_add_forbids_base():
    with pytest.raises(ValidationError):
        FactParseRequest(text="a", mode="ADD", base_fact_revision_id=3)


def test_parse_ok_and_text_stripped():
    req = FactParseRequest(text=" a ", mode="MODIFY", base_fact_revision_id=3)
    assert req.text == "a"
    with pytest.raises(ValidationError):
        FactParseRequest(text="  ")


def test_card_detail_defaults_keep_old_construction_working():
    now = datetime.now(timezone.utc)
    d = CardDetail(card_id=1, review_status="PENDING", assignment_type="AUTOMATIC", updated_at=now)
    assert d.fact_card is False


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.card_fact_parse_max_chars == 1000
    assert s.card_fact_parse_max_facts == 10
