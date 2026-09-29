"""W2-1 대상 이름 정규화·규격 파싱·후보 판정 (순수 함수, DB 없음)."""
import pytest

from app.config import Settings
from app.ingest.entity_names import (candidate_reason, normalize_alias, normalize_subject,
                                     parse_variant)


def test_space_and_case_same_norm():
    for raw in ("음료Z", "음료 Z", "음료z "):
        parts = normalize_subject(raw)
        assert parts.name_norm == "음료z"
        assert parts.temperature_hint is None and parts.size_hint is None
    assert normalize_alias(" 음료 Z ") == "음료z"


def test_temperature_token_stripped():
    for raw, hint in (("아이스 음료Z", "ICE"), ("음료Z(ICE)", "ICE"), ("HOT 음료Z", "HOT")):
        parts = normalize_subject(raw)
        assert parts.name_norm == "음료z", raw
        assert parts.temperature_hint == hint, raw
        assert parts.size_hint is None
        assert parts.display_name == "음료Z"


def test_size_token_stripped():
    for raw in ("라지 음료Z", "음료Z L"):
        parts = normalize_subject(raw)
        assert parts.name_norm == "음료z"
        assert parts.size_hint == "L"
        assert parts.temperature_hint is None


def test_partial_token_not_stripped():
    for raw in ("핫초코", "아이스크림", "아이스티"):
        parts = normalize_subject(raw)
        assert parts.name_norm == raw
        assert parts.temperature_hint is None and parts.size_hint is None


def test_only_variant_token_kept():
    parts = normalize_subject("아이스")
    assert parts.name_norm == "아이스"
    assert parts.display_name == "아이스"
    assert parts.temperature_hint is None and parts.size_hint is None


def test_two_temperatures_hint_none():
    parts = normalize_subject("HOT/ICE 음료Z")
    assert parts.name_norm == "음료z"
    assert parts.temperature_hint is None


def test_same_temperature_twice_keeps_hint():
    assert normalize_subject("ICE 아이스 음료Z").temperature_hint == "ICE"


def test_task_name_space_insensitive():
    assert normalize_subject("주문 응대").name_norm == normalize_subject("주문응대").name_norm == "주문응대"
    assert normalize_subject("주문 응대").display_name == "주문 응대"


def test_punctuation_only_empty():
    assert normalize_subject("!!!").name_norm == ""
    assert normalize_subject("   ").name_norm == ""
    assert normalize_alias("!!!") == ""


def test_parse_variant():
    v = parse_variant("ICE")
    assert (v.temperature, v.size, v.other, v.multi_temperature) == ("ICE", None, None, False)
    v = parse_variant("HOT L")
    assert (v.temperature, v.size, v.other) == ("HOT", "L", None)
    assert parse_variant("아이스").temperature == "ICE"
    assert parse_variant("따뜻한").temperature == "HOT"
    assert parse_variant("차가운").temperature == "ICE"
    v = parse_variant("디카페인")
    assert (v.temperature, v.size, v.other) == (None, None, "디카페인")
    v = parse_variant("HOT/ICE")
    assert v.temperature is None and v.multi_temperature is True
    for empty in ("", None, "  "):
        v = parse_variant(empty)
        assert (v.temperature, v.size, v.other, v.multi_temperature) == (None, None, None, False)


def test_parse_variant_other_sorted():
    assert parse_variant("샷추가 디카페인").other == "디카페인 샷추가"
    assert parse_variant("디카페인 샷추가").other == "디카페인 샷추가"


def test_candidate_reason():
    assert candidate_reason("카페라떼", "카페라테") == "EDIT1"
    assert candidate_reason("카페라테", "카페라떼") == "EDIT1"
    assert candidate_reason("우유", "우유거품") == "CONTAINS"
    assert candidate_reason("우유거품", "우유") == "CONTAINS"
    assert candidate_reason("주문응대", "주문응대원칙") == "CONTAINS"
    assert candidate_reason("우유", "커피") is None
    assert candidate_reason("ab", "ac") is None
    assert candidate_reason("음료z", "음료y") == "EDIT1"


def test_config_flags_default_off():
    s = Settings(_env_file=None)
    assert s.w_entity_revision_enabled is False
    assert s.w_entity_candidate_max == 5
    assert s.w_upload_proposals_enabled is False
    with pytest.raises(ValueError):
        Settings(_env_file=None, w_upload_proposals_enabled=True)
    ok = Settings(_env_file=None, w_upload_proposals_enabled=True, w_entity_revision_enabled=True)
    assert ok.w_upload_proposals_enabled is True
