"""원장 중복 판정이 조건·부정·단위·예외를 구분하는지 검증한다.

값이 같아도 조건·부정·단위·예외가 다르면 서로 다른 사실이다.
같은 것으로 보면 `on conflict (source_id, content_hash) do nothing` 에 걸려
뒤에 들어온 주장이 조용히 사라진다.
"""
import pytest
from app.ingest.repository import fact_content_hash, insert_source_facts


def _hash(**over):
    """같은 대상·속성·값을 두고 지정한 필드만 바꾼 해시를 만든다."""
    base = dict(subject="음료Z", variant=None, attribute="얼음", value="3",
                unit=None, polarity="AFFIRM", conditions=None, exceptions=None)
    base.update(over)
    return fact_content_hash(
        base["subject"], base["variant"], base["attribute"], base["value"],
        unit=base["unit"], polarity=base["polarity"],
        conditions=base["conditions"], exceptions=base["exceptions"])


def test_same_value_under_different_conditions_are_distinct_facts():
    # 여름엔 얼음 3개 / 겨울엔 얼음 3개 — 값이 같아도 적용 조건이 다르다
    assert _hash(conditions=["여름"]) != _hash(conditions=["겨울"])


def test_negated_assertion_is_distinct_from_affirmed():
    # "얼음 3개를 넣는다" 와 "넣지 않는다" 가 합쳐지면 반대 지시가 사라진다
    assert _hash(polarity="AFFIRM") != _hash(polarity="NEGATE")


def test_same_number_with_different_unit_is_a_distinct_fact():
    # 275 ml 와 275 g 은 다른 사실이다
    assert _hash(unit="ml") != _hash(unit="g")


def test_different_exceptions_are_distinct_facts():
    assert _hash(exceptions=["재고 부족"]) != _hash(exceptions=["포장 주문"])


def test_condition_presence_differs_from_absence():
    # 무조건 적용되는 사실과 조건부 사실을 같게 보지 않는다
    assert _hash(conditions=None) != _hash(conditions=["여름"])


def test_identical_assertion_still_deduplicates_on_re_extraction():
    # 재추출은 흔하다. 완전히 같은 주장은 여전히 한 행이어야 한다
    assert _hash(conditions=["여름"], unit="ml") == _hash(conditions=["여름"], unit="ml")


def test_condition_order_does_not_create_a_duplicate():
    # 모델이 같은 조건을 다른 순서로 뱉어도 새 사실로 세지 않는다
    assert _hash(conditions=["여름", "포장"]) == _hash(conditions=["포장", "여름"])


def test_empty_list_and_none_conditions_are_the_same_fact():
    # 조건 없음의 두 표현이 서로 다른 행을 만들지 않게 한다
    assert _hash(conditions=None) == _hash(conditions=[])


class _RecordingConn:
    """insert_source_facts 가 실제로 넘긴 content_hash 를 붙잡는 가짜 연결."""

    def __init__(self):
        self.digests: list[str] = []
        self._next_id = 0

    async def fetchval(self, query: str, *args):
        if "insert into source_facts" in query:
            self.digests.append(args[9])  # $10 = content_hash
            self._next_id += 1
            return self._next_id
        raise AssertionError(f"예상하지 못한 질의: {query[:40]}")


@pytest.mark.asyncio
async def test_insert_passes_conditions_into_the_duplicate_key():
    # 값이 같고 조건만 다른 두 주장이 같은 열쇠를 받으면 뒤엣것이 사라진다
    conn = _RecordingConn()
    facts = [
        dict(subject="음료Z", attribute="얼음", value="3", conditions=["여름"]),
        dict(subject="음료Z", attribute="얼음", value="3", conditions=["겨울"]),
    ]
    await insert_source_facts(conn, store_id=1, source_id=7, facts=facts,
                              locator_type="TIMESTAMP", locator={})
    assert len(set(conn.digests)) == 2


@pytest.mark.asyncio
async def test_insert_passes_polarity_into_the_duplicate_key():
    conn = _RecordingConn()
    facts = [
        dict(subject="음료Z", attribute="얼음", value="3", polarity="AFFIRM"),
        dict(subject="음료Z", attribute="얼음", value="3", polarity="NEGATE"),
    ]
    await insert_source_facts(conn, store_id=1, source_id=7, facts=facts,
                              locator_type="TIMESTAMP", locator={})
    assert len(set(conn.digests)) == 2


@pytest.mark.asyncio
async def test_insert_passes_unit_into_the_duplicate_key():
    conn = _RecordingConn()
    facts = [
        dict(subject="음료Z", attribute="용량", value="275", unit="ml"),
        dict(subject="음료Z", attribute="용량", value="275", unit="g"),
    ]
    await insert_source_facts(conn, store_id=1, source_id=7, facts=facts,
                              locator_type="TIMESTAMP", locator={})
    assert len(set(conn.digests)) == 2


@pytest.mark.asyncio
async def test_insert_still_dedupes_a_fully_identical_reextraction():
    conn = _RecordingConn()
    fact = dict(subject="음료Z", attribute="얼음", value="3", conditions=["여름"])
    await insert_source_facts(conn, store_id=1, source_id=7, facts=[fact, dict(fact)],
                              locator_type="TIMESTAMP", locator={})
    assert len(set(conn.digests)) == 1
