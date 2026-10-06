"""참조 대조 스크립트 순수 함수 테스트. DB 없이 익명 픽스처만 쓴다."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from compare_reference import compare  # noqa: E402


def ref(row, attr, value, unit=None, subject="메뉴A", variant=None, polarity="ASSERT",
        step_order=None, assertion="", conditions=None):
    return {"consensus": {"row": row}, "subject": subject, "variant": variant,
            "attribute": attr, "value": value, "unit": unit, "polarity": polarity,
            "step_order": step_order, "original_assertion": assertion,
            "conditions": conditions or []}


def led(attr, value, unit=None, subject="메뉴A", variant=None, polarity="ASSERT",
        step_order=None, assertion="", conditions=None):
    return {"subject": subject, "variant": variant, "attribute": attr, "value": value,
            "unit": unit, "polarity": polarity, "step_order": step_order,
            "original_assertion": assertion, "conditions": conditions or [],
            "exceptions": []}


def test_price_and_num_exact():
    r = [ref(1, "판매가", "4,500"), ref(1, "시럽", "3", "p")]
    l = [led("판매가", "4500"), led("시럽", "3", "p")]
    out = compare(r, l)
    assert out["recalled"] == 2 and out["recall"] == 1.0


def test_unit_spelling_difference():
    out = compare([ref(1, "시럽", "3", "p")], [led("시럽", "3", "펌프")])
    assert out["recalled"] == 1


def test_subject_containment_with_variant_word():
    r = [ref(1, "판매가", "5000", subject="메뉴A", variant="ICE")]
    l = [led("판매가", "5000", subject="ICE 메뉴A")]
    out = compare(r, l)
    assert out["ledger_mapped"] == 1 and out["recalled"] == 1


def test_ambiguous_containment_unmapped():
    r = [ref(1, "판매가", "5000", subject="메뉴AB"), ref(2, "판매가", "6000", subject="메뉴AC")]
    out = compare(r, [led("판매가", "5000", subject="메뉴A")])
    assert out["ledger_unmapped"] == 1 and out["recalled"] == 0


def test_neg_same_column_only():
    r = [ref(1, "얼음", "넣지 않음", polarity="NEGATE")]
    same = compare(r, [led("얼음", "없음", polarity="NEGATE")])
    other = compare(r, [led("토핑", "없음", polarity="NEGATE")])
    assert same["recalled"] == 1 and other["recalled"] == 0


def test_step_needle_in_ledger_text():
    r = [ref(1, "제조순서", "컵에 얼음을 채운다", step_order=1)]
    l = [led("제조순서", "x", assertion="2. 컵에 얼음을 채운다 그리고", step_order=2)]
    assert compare(r, l)["by_kind"]["STEP"]["recalled"] == 1


def test_value_conflict():
    r = [ref(1, "컵", "225", "ml")]
    l = [led("컵", "255", "ml", assertion="컵 255ml")]
    out = compare(r, l)
    assert len(out["conflicts"]) == 1 and out["recalled"] == 0


def test_aggregate_keys_and_recall():
    r = [ref(1, "판매가", "4500"), ref(2, "판매가", "5000", subject="메뉴B"),
         ref("각주", "시럽", "3", "p", subject="각주")]
    l = [led("판매가", "4500"), led("판매가", "1", subject="없는메뉴")]
    out = compare(r, l)
    for k in ("reference_total", "recalled", "recall", "by_kind", "menu_rows_total",
              "menu_rows_touched", "price_recalled", "ledger_total", "ledger_mapped",
              "ledger_unmapped", "unmapped_subjects", "conflicts", "missed_examples"):
        assert k in out
    assert out["reference_total"] == 3 and out["recalled"] == 1
    assert out["recall"] == 0.333
    assert out["menu_rows_total"] == 2 and out["menu_rows_touched"] == 1
    assert out["price_recalled"] == 1
    assert out["ledger_total"] == 2 and out["ledger_unmapped"] == 1
    assert out["by_kind"]["PRICE"] == {"total": 2, "recalled": 1}
    assert out["missed_examples"][0][0] == 2


def test_price_digit_boundary():
    for ledger_val in ("4500", "5000"):
        assert compare([ref(1, "판매가", "500")], [led("판매가", ledger_val)])["recalled"] == 0


def test_num_digit_boundary():
    out = compare([ref(1, "컵", "25", "ml")], [led("컵", "225", "ml", assertion="225ml")])
    assert out["recalled"] == 0 and len(out["conflicts"]) == 1


def test_price_comma_text_recalled():
    out = compare([ref(1, "판매가", "1500")], [led("판매가", "x", assertion="1,500원")])
    assert out["recalled"] == 1


def test_variant_from_subject():
    r = [ref(1, "판매가", "4000", variant="HOT"), ref(2, "판매가", "4500", variant="ICE")]
    l = [led("판매가", "4500", subject="ICE 메뉴A")]
    out = compare(r, l)
    assert out["recalled"] == 1 and out["missed_examples"][0][0] == 1


def test_footnote_mapping():
    r = [ref("각주", "시럽", "3", "p", subject="각주시럽")]
    out = compare(r, [led("시럽", "3", "p", subject="각주시럽")])
    assert out["recalled"] == 1 and out["by_scope"]["각주"] == {"total": 1, "recalled": 1}
