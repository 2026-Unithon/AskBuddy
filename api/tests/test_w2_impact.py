"""W2-4 영향 카드 계산·업로드 검수 제안 — 순수 판정과 파이프라인 연결.

설정은 필드가 몇 개뿐인 NS 로 patch 한다(F18). 모델·DB 는 부르지 않는다.
실제 DB 동작은 verify_w_entity_revision 의 P1~P5 가 확인한다.
"""
import inspect
import re
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import impact, pipeline
from app.ingest.impact import classify_fact, proposal_relation, variant_compatible
from app.ingest.schemas import ExtractedCard, ExtractedFact, ExtractionResult


# ── classify_fact ───────────────────────────────────────────────────────────

def test_no_approved_card_is_new():
    assert classify_fact(matched_approved=set(), fact_card_ids={1}, conflict_card_ids={1},
                         preexisting=True) == "NEW"


def test_preexisting_fact_already_on_approved_card_is_identical():
    assert classify_fact(matched_approved={1, 2}, fact_card_ids={2}, conflict_card_ids=set(),
                         preexisting=True) == "IDENTICAL"


def test_open_conflict_partner_on_approved_card_is_conflict():
    assert classify_fact(matched_approved={1}, fact_card_ids=set(), conflict_card_ids={1},
                         preexisting=False) == "CONFLICT"


def test_other_fact_of_an_approved_card_entity_is_supplement():
    assert classify_fact(matched_approved={1}, fact_card_ids=set(), conflict_card_ids=set(),
                         preexisting=False) == "SUPPLEMENT"


def test_preexisting_fact_not_on_approved_card_is_supplement():
    # 전에 있던 사실이라도 승인 카드에 실리지 않았으면 같은 내용이 아니다
    assert classify_fact(matched_approved={1}, fact_card_ids={7}, conflict_card_ids=set(),
                         preexisting=True) == "SUPPLEMENT"


def test_new_fact_on_same_card_is_not_identical():
    # 이 자료가 처음 만든 사실은 IDENTICAL 이 아니다
    assert classify_fact(matched_approved={1}, fact_card_ids={1}, conflict_card_ids=set(),
                         preexisting=False) == "SUPPLEMENT"


def test_conflict_partner_only_on_draft_card_is_supplement():
    assert classify_fact(matched_approved={1}, fact_card_ids=set(), conflict_card_ids={9},
                         preexisting=False) == "SUPPLEMENT"


# ── proposal_relation ──────────────────────────────────────────────────────

@pytest.mark.parametrize("relations, has_approved, expected", [
    (["IDENTICAL", "SUPPLEMENT", "CONFLICT"], True, "CONFLICT"),
    (["IDENTICAL", "SUPPLEMENT"], True, "SUPPLEMENT"),
    (["IDENTICAL", "IDENTICAL"], True, "IDENTICAL"),
    (["IDENTICAL", "NEW"], True, "SUPPLEMENT"),     # 전부 IDENTICAL 이 아니면 보충
    (["CONFLICT", "NEW"], True, "CONFLICT"),
    (["NEW", "NEW"], False, "NEW"),
    (["SUPPLEMENT", "CONFLICT"], False, "NEW"),     # 승인 카드가 없으면 머리는 NEW
    ([], False, "NEW"),
])
def test_proposal_relation_priority(relations, has_approved, expected):
    assert proposal_relation(relations, has_approved) == expected


# ── 규격 호환 (D19) ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("temp, size, card, expected", [
    (None, None, [("ICE", "L")], True),             # 새 사실에 규격 없음
    ("HOT", None, [], True),                        # 카드에 이어진 사실 없음
    ("HOT", None, [(None, None)], True),            # 카드에 규격 정보 전혀 없음
    ("HOT", None, [("ICE", None)], False),          # ICE 뿐인 카드 — HOT 은 영향 없음
    ("HOT", None, [("ICE", None), ("HOT", None)], True),   # 한 카드에 HOT·ICE 함께
    ("HOT", None, [(None, "L")], True),             # 온도 정보 없는 카드
    ("HOT", "L", [("HOT", "S")], False),            # 사이즈가 다르다
    (None, "L", [(None, "L"), ("ICE", "S")], True),
])
def test_variant_compatible(temp, size, card, expected):
    assert variant_compatible(temp, size, card) is expected


# ── DB 경계 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_affected_cards_empty_list_does_not_touch_the_db():
    conn = NS(fetch=AsyncMock(), fetchrow=AsyncMock(), fetchval=AsyncMock(),
              execute=AsyncMock())
    result = await impact.affected_cards(conn, 3, [], exclude_source_id=5)
    assert result.card_ids == () and result.by_fact_revision == {}
    conn.fetch.assert_not_awaited()


def test_impact_never_writes_existing_card_rows():
    # 결정 G·불변식 12 — 카드·카드 버전·점주 답변 제안 표에 쓰지 않는다
    src = inspect.getsource(impact).lower()
    for table in ("knowledge_cards", "card_versions", "knowledge_change_proposals",
                  "card_facts", "knowledge_snapshots"):
        assert not re.search(rf"(update|insert\s+into|delete\s+from)\s+{table}\b", src), table


def test_impact_sql_filters_by_store():
    # 모든 조회·쓰기가 매장으로 좁혀진다 (D1)
    assert inspect.getsource(impact).count("store_id = $1") >= 6


# ── 파이프라인 연결 (F18) ──────────────────────────────────────────────────

def _settings(**extra):
    return NS(gemini_model="gemini-synthetic", extract_temperature=0.0, ingest_mode="mock",
              extract_locator_hints=False, **extra)


def _card():
    return ExtractedCard(category_name="기타", title="음료Z", content="물 10ml", confidence=.9,
                         facts=[ExtractedFact(object_name="음료Z", attribute="물", value="10",
                                              confidence=.9, ref="f1")])


async def _run_persist(settings):
    conn = NS(fetchval=AsyncMock(return_value="SCAN"))
    record = AsyncMock(return_value=1)
    order: list[str] = []
    set_state = AsyncMock(side_effect=lambda *a, **k: order.append("assembly_state"))
    record.side_effect = lambda *a, **k: order.append("proposals")
    with patch.object(pipeline.repo, "insert_card", AsyncMock(return_value=9)), \
         patch.object(pipeline.repo, "insert_facts", AsyncMock()), \
         patch.object(pipeline.repo, "link_card_facts", AsyncMock()), \
         patch.object(pipeline.repo, "insert_card_evidence", AsyncMock()), \
         patch.object(pipeline.repo, "set_assembly_state", set_state), \
         patch("app.ingest.fact_ledger.card_entity_for", AsyncMock(return_value=None)), \
         patch("app.ingest.entities.lock_store_knowledge", AsyncMock()), \
         patch.object(impact, "record_upload_proposals", record), \
         patch("app.config.get_settings", return_value=settings):
        await pipeline._persist(conn, 3, 5, {"기타": 1}, ExtractionResult(cards=[_card()]),
                                job_id=11, category_version=1, ledger_ids={"f1": 77})
    return conn, record, order


@pytest.mark.asyncio
async def test_persist_flag_absent_does_not_record_proposals():
    _, record, _ = await _run_persist(_settings())
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_flag_off_does_not_record_proposals():
    _, record, _ = await _run_persist(_settings(w_entity_revision_enabled=True,
                                                w_upload_proposals_enabled=False))
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_flag_on_records_after_assembly_state_with_same_conn():
    conn, record, order = await _run_persist(_settings(w_entity_revision_enabled=True,
                                                       w_upload_proposals_enabled=True))
    record.assert_awaited_once()
    assert record.await_args.args == (conn, 3, 5)
    assert record.await_args.kwargs == {"job_id": 11}
    assert order[-1] == "proposals" and "assembly_state" in order


# ── 결정 J — 항목은 PENDING_REVIEW 제안에서만 지금 계산으로 갱신 ──────────

class _ProposalConn:
    """record_upload_proposals 가 부르는 조회를 문장 조각으로 흉내 낸다."""

    def __init__(self, status):
        self.status = status
        self.writes: list[tuple[str, tuple]] = []

    async def fetch(self, query, *args):
        if "from source_fact_revision_links l" in query and "sf.source_id" in query:
            return [{"fact_id": 70, "fact_revision_id": 700, "link_kind": "CREATED",
                     "entity_id": 5}]
        if "from knowledge_cards" in query:
            return [{"card_id": 9, "review_status": "APPROVED", "published_version_id": 90}]
        if "from fact_conflicts" in query:
            return [{"fact_id_low": 70, "fact_id_high": 71}]
        if "join card_facts" in query:
            return [{"fact_id": 71, "card_id": 9}]
        raise AssertionError(query)

    async def fetchrow(self, query, *args):
        assert "from upload_change_proposals" in query and "store_id = $1" in query
        return {"proposal_id": 40, "status": self.status}

    async def execute(self, query, *args):
        self.writes.append((query, args))
        return "INSERT 0 1"


async def _record(status):
    conn = _ProposalConn(status)
    affected = impact.AffectedCards(card_ids=(9,), by_fact_revision={700: (9,)})
    with patch.object(impact, "lock_store_knowledge", AsyncMock()), \
         patch.object(impact, "affected_cards", AsyncMock(return_value=affected)):
        await impact.record_upload_proposals(conn, 3, 8, job_id=None)
    return [w for w in conn.writes if "upload_change_proposal_facts" in w[0]]


@pytest.mark.asyncio
async def test_pending_proposal_items_are_upserted_with_current_values():
    items = await _record("PENDING_REVIEW")
    assert len(items) == 1
    query, args = items[0]
    assert "on conflict (store_id, proposal_id, fact_revision_id) do update" in query
    for column in ("relation_type", "conflict_fact_ids", "affected_card_ids"):
        assert f"{column} = excluded.{column}" in query
    assert args == (3, 40, 700, 70, "CONFLICT", [71], [9])


@pytest.mark.parametrize("status", ["ACCEPTED", "DISMISSED", "SUPERSEDED"])
@pytest.mark.asyncio
async def test_decided_proposal_gets_no_item_writes(status):
    assert await _record(status) == []


class _AffectedConn:
    """카드 1장에 대상 5 의 사실(규격 없음)과 대상 6 의 ICE 사실이 함께 이어져 있다."""

    async def fetch(self, query, *args):
        if "from fact_revisions r" in query:
            return [{"fact_revision_id": 700, "fact_id": 70, "entity_id": 5,
                     "variant_temperature": "HOT", "variant_size": None}]
        if "from fact_revision_requires" in query:
            return []
        if "from knowledge_cards c" in query:
            return [{"card_id": 9, "entity_id": None}]
        if "from card_facts cf" in query:
            return [{"card_id": 9, "fact_id": 60, "entity_id": 5,
                     "variant_temperature": None, "variant_size": None},
                    {"card_id": 9, "fact_id": 61, "entity_id": 6,
                     "variant_temperature": "ICE", "variant_size": None}]
        raise AssertionError(query)


@pytest.mark.asyncio
async def test_variant_check_uses_only_facts_of_the_same_entity():
    # 결정 J Minor — 다른 대상의 ICE 사실 때문에 HOT 사실이 영향에서 빠지면 안 된다
    result = await impact.affected_cards(_AffectedConn(), 3, [700], exclude_source_id=None)
    assert result.by_fact_revision == {700: (9,)}
