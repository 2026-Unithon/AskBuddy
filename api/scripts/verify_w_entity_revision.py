"""실제 DB: W2 대상(entity)·사실 판(revision) 검증. 모델 호출 없음.

verify_r_schema_rebuild 가 만든 새 UUID DB(모든 migration 적용)의 연결과 DSN 만 받는다.
시나리오 함수를 과제마다 더하고 verify() 가 순서대로 부른다.

Task 1 (W2-1 대상):
  E1 공백·대소문자·규격 낱말만 다른 이름 → 한 대상, 대상 1행·별칭 1행
  E2 한 글자 다른 이름 → 대상 둘 + PENDING 후보 1행(EDIT1). 합치지 않는다
  E3 매장별 별칭 격리 — 같은 이름도 매장마다 다른 대상, 복합 FK 가 매장 교차를 막고,
     후보 계산이 다른 매장 별칭을 보지 않는다
  E4 다른 대상의 활성 별칭을 점주 별칭으로 달면 AliasTaken
  E5 대상 이력은 UPDATE/DELETE 불가
  E6 병합된 대상의 별칭은 살아남은 대상으로 따라간다 · 정규화 불가 이름은 대상 결정 불가

Task 2 (W2-2 원장 → 판·occurrence, process_source + 합성 모델 대역):
  R1 영상 순서 + PDF 수량 → 한 대상, 사실·판 4, occurrence 는 각 자료로, 충돌 0
  R2 HOT/ICE 분리 · 같은 값의 HOT/ICE 도 두 사실
  R3 수치 충돌 양쪽 보존 — 두 사실·두 판, OPEN NUMERIC 충돌 1, 검수 목록에 선택 칸 없음
  R4 같은 자료 재투입 → 표 행 수 불변 · 같은 내용의 새 자료 → occurrence 만 +1, MATCHED
  R5 사람 검토 사례 합성(주문 응대 원칙 + 주문응대 방법) → 한 대상, 사실 2, 충돌 0
  R6 점주 답변 사실 — 판 메타에 owner_answer_id, occurrence·자료 없음(결정 F), 다른 매장 답변 → 예외.
     새 사실·이미 있는 같은 사실 모두 fact_owner_answer_links 에 출처 1행, 재시도 멱등(결정 H)
  R7 불변 — 판·판 메타 UPDATE 예외, W 가 만든 판은 모두 메타·사실 정체와 짝
  R8 격리 — 다른 매장 id 로 연결하면 0건
  R9 평가 매장 초기화 STEPS 가 W2 표를 포함해 한 매장을 지운다(다른 매장은 그대로)

Task 3 (W2-3 수정은 새 revision, R3 과 같은 합성 매장):
  V1 20 ml 사실을 점주 정정(30) → 새 판 supersedes 옛 판, 옛 판·메타·원장 value 그대로,
     메타 change_kind·applied_at·created_by, 충돌 RESOLVED(두 사실 모두 남음). 선행 관계 복사
  V2 같은 기대 head 로 다시 → StaleFactRevision, 판 수 불변 · 다른 매장 id → LookupError
  V3 source_facts.corrected_value → import_legacy_correction 두 번 → 판 1개(멱등),
     applied_at=corrected_at · 값이 다시 갈라지면 같은 쌍에 새 OPEN
  V4 OWNER_ANSWER 정정 → 메타 owner_answer_id·연결 표 1행, occurrence·자료 없음(결정 F·H)
  V5 dismiss_conflict → DISMISSED, 다시 부르면 ValueError, 다른 매장 id → LookupError
     결정 I — 기각한 쌍은 문구·조건만 바뀐 정정으로 다시 열리지 않고, 값이 바뀌면 새 OPEN
  V6 공개본 불변 — 그 매장 knowledge_snapshots·card_versions·knowledge_cards 행 수·내용 해시 동일

Task 4 (W2-4 영향 카드·업로드 검수 제안, publish_cards 로 실제 발행):
  P1 자료 A → 카드 X 승인·발행, X 를 MANUAL·다른 카테고리로 옮김. 다른 대상 카드 Y·ICE 뿐인 카드 Z 도 발행
  P2 자료 B(같은 대상: 새 속성 1 + 같은 사실 1 + 충돌 값 1) → 머리 1행 CONFLICT,
     항목 SUPPLEMENT·IDENTICAL·CONFLICT 각 1, matched_cards 에 X 와 그 공개 판, 선택 칸 없음
  P3 영향 없는 카드 보존 — X·Y·Z 행 전체(to_jsonb, updated_at 포함)·공개 포인터·배정·카테고리,
     snapshot 행 수·current snapshot hash 가 B 전후 동일. Y 는 영향 목록에 없다
  P4 B 재처리 → 제안·항목 행 수·내용 불변
  P5 첫 자료만 있는 새 매장 → 모두 NEW
  P6 ICE 뿐인 승인 카드 Z 와 같은 대상의 HOT 사실 → Z 는 영향 없음, NEW
  P7 (결정 J) 자료 처리 → 같은 대상 다른 값 카드 승인 → 재처리: 머리 CONFLICT 로 올라가고 항목도
     CONFLICT·충돌 상대·영향 카드로 갱신 · DISMISSED 제안은 새 사실 재처리에도 머리·항목 그대로

Task 5 (W2-4 ③ 대상 병합·분리·재연결, 한 합성 매장 + 실제 발행):
  S1 우유(보관 위치 + 잘못 들어온 스팀 온도 65) → split_entity(스팀 65, "우유 거품", 별칭 스팀우유 이동) →
     새 대상·SYSTEM/OWNER 별칭, head 는 RELINK 판(supersedes 옛 판, 값 그대로), 옛 판·메타·occurrence·
     원장 연결 행 그대로, 옛 슬롯 충돌 OBSOLETE, 이력 SPLIT·RELINK_FACT·CREATE, 후보 CONFIRMED_DIFFERENT.
     relink_fact(70 → 우유 거품) → 새 슬롯에서 같은 쌍 OPEN, 같은 대상·낡은 head → ValueError·Stale
  S2 카페라떼/카페라테 후보 → merge_entities → 사실 이동, 별칭 카페라테 가 keep 에서 조회, merged MERGED,
     resolve_entity("카페라테") = keep, 같은 값 두 사실은 둘 다 남고 충돌 아님, 후보 CONFIRMED_SAME,
     decide_candidate DISMISSED·이력. 병합 뒤 새 자료는 keep 에 MATCHED·사실은 keep 대상의 카드에 실림
  S3 공개본 보존 — S1·S2 전후 카드 행·card_versions·card_facts·snapshot 수·current hash·업로드 제안 동일
  S4 다른 매장 entity_id 로 relink → LookupError·행 수 불변, 직접 쓰기는 복합 FK 실패,
     다른 매장 id 로 split·merge·후보 결정 → LookupError

업로드는 항상 사실 경로(대상·판 연결·검수 제안·사실 조립)로 간다. 플래그 켜기/끄기 비교 검증은 없다.
"""
import importlib
import json
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import asyncpg

import app.config
from app.config import Settings
from app.ingest import extract, fact_ledger, pipeline
from app.ingest import repository as repo
from app.ingest.entities import (AliasTaken, EntityUnresolvable, add_owner_alias,
                                 find_entity_by_alias, list_candidates, lock_store_knowledge,
                                 resolve_entity)
from app.ingest.extract import gemini
from app.ingest import fact_assembly
from app.ingest.extract import mock
from app.ingest.schemas import FactExtractionResult
from verify_w_partial_extraction import _new_source, _seed


def _checker(prefix):
    def check(name, ok):
        assert ok, name
        print(f"PASS W entity {prefix}", name)
    return check


async def _resolve(db, store, raw, payload=None):
    async with db.transaction():
        await lock_store_knowledge(db, store)
        return await resolve_entity(db, store, raw, actor_id=None,
                                    origin_payload=payload or {"verify": raw})


async def _count(db, sql, *args):
    return await db.fetchval(sql, *args)


async def _scenario_entities(db) -> None:
    user, store_a, _ = await _seed(db)
    _, store_b, _ = await _seed(db)

    # E1 — 한 대상
    check = _checker("E1")
    first = await _resolve(db, store_a, "음료Z")
    second = await _resolve(db, store_a, "음료 Z")
    third = await _resolve(db, store_a, "아이스 음료Z")
    check("음료Z·음료 Z·아이스 음료Z → 한 entity_id",
          first.created and not second.created and not third.created
          and first.entity_id == second.entity_id == third.entity_id)
    check("규격 낱말은 hint 로만 돌려준다", third.temperature_hint == "ICE"
          and first.temperature_hint is None)
    check("대상 1행·별칭 1행", await _count(
        db, "select count(*) from knowledge_entities where store_id=$1 and name_norm='음료z'",
        store_a) == 1 and await _count(
        db, "select count(*) from knowledge_entity_aliases where store_id=$1 and entity_id=$2",
        store_a, first.entity_id) == 1)
    row = await db.fetchrow(
        "select canonical_name, kind, status from knowledge_entities "
        "where store_id=$1 and entity_id=$2", store_a, first.entity_id)
    check("이름에 규격 낱말이 없다", tuple(row) == ("음료Z", "UNKNOWN", "ACTIVE"))
    event = await db.fetchrow(
        "select action, payload::text p from knowledge_entity_events "
        "where store_id=$1 and entity_id=$2", store_a, first.entity_id)
    check("생성 이력 CREATE 한 건(origin_payload)",
          event["action"] == "CREATE" and "음료Z" in event["p"])

    # E2 — 비슷한 이름은 후보만
    check = _checker("E2")
    latte = await _resolve(db, store_a, "카페라떼")
    latte2 = await _resolve(db, store_a, "카페라테")
    check("카페라떼·카페라테 → 대상 둘", latte.created and latte2.created
          and latte.entity_id != latte2.entity_id)
    check("후보 상대 id 를 돌려준다", latte2.candidate_ids == (latte.entity_id,)
          and latte.candidate_ids == ())
    pending = await list_candidates(db, store_a)
    low, high = sorted((latte.entity_id, latte2.entity_id))
    check("후보 1행 EDIT1·PENDING", len(pending) == 1
          and (pending[0]["entity_id_low"], pending[0]["entity_id_high"]) == (low, high)
          and pending[0]["reason"] == "EDIT1" and pending[0]["status"] == "PENDING"
          and pending[0]["decided_at"] is None)
    aliases = await db.fetch(
        "select entity_id, alias_norm from knowledge_entity_aliases "
        "where store_id=$1 and entity_id = any($2::bigint[]) order by entity_id",
        store_a, [latte.entity_id, latte2.entity_id])
    check("두 대상의 별칭은 섞이지 않는다", [tuple(a) for a in aliases]
          == sorted([(latte.entity_id, "카페라떼"), (latte2.entity_id, "카페라테")]))
    again = await _resolve(db, store_a, "카페라테")
    check("같은 이름 재결정은 후보를 늘리지 않는다", not again.created
          and len(await list_candidates(db, store_a)) == 1)

    # E3 — 매장별 별칭 격리
    check = _checker("E3")
    in_b = await _resolve(db, store_b, "음료Z")
    check("다른 매장의 같은 이름 → 새 대상", in_b.created and in_b.entity_id != first.entity_id)
    check("find_entity_by_alias 는 그 매장 id",
          await find_entity_by_alias(db, store_b, "음료z") == in_b.entity_id
          and await find_entity_by_alias(db, store_a, "음료z") == first.entity_id)
    try:
        await db.execute(
            "insert into knowledge_entity_aliases (store_id, entity_id, alias_norm, alias_raw, origin) "
            "values ($1, $2, '교차별칭', '교차별칭', 'OWNER')", store_b, first.entity_id)
        crossed = True
    except asyncpg.ForeignKeyViolationError:
        crossed = False
    check("B store_id 로 A 대상을 가리키는 별칭 → 복합 FK 실패", not crossed)
    try:
        await db.execute(
            "insert into knowledge_entity_candidates (store_id, entity_id_low, entity_id_high, reason) "
            "values ($1, $2, $3, 'EDIT1')", store_b,
            *sorted((first.entity_id, in_b.entity_id)))
        crossed = True
    except asyncpg.ForeignKeyViolationError:
        crossed = False
    check("매장을 가로지르는 후보 쌍 → 복합 FK 실패", not crossed)
    bean_b = await _resolve(db, store_b, "커피콩")
    bean_a = await _resolve(db, store_a, "커피콩 보관")
    check("A 의 후보 계산에 B 별칭이 나오지 않는다", bean_a.created and bean_a.candidate_ids == ()
          and await _count(
              db, "select count(*) from knowledge_entity_candidates where store_id=$1 "
              "and $2 in (entity_id_low, entity_id_high)", store_a, bean_a.entity_id) == 0)
    bean_b2 = await _resolve(db, store_b, "커피콩 보관")
    check("같은 매장이면 후보가 된다(대조군, CONTAINS)",
          bean_b2.candidate_ids == (bean_b.entity_id,)
          and [c["reason"] for c in await list_candidates(db, store_b)] == ["CONTAINS"])
    check("후보 목록은 매장 한정", all(
        c["entity_id_low"] != bean_b.entity_id for c in await list_candidates(db, store_a)))

    # E4 — 점주 별칭
    check = _checker("E4")
    try:
        await add_owner_alias(db, store_a, latte.entity_id, "카페 라테", actor_id=user)
        taken = False
    except AliasTaken:
        taken = True
    check("다른 대상의 활성 별칭 → AliasTaken", taken)
    alias_id = await add_owner_alias(db, store_a, latte.entity_id, "라떼 카페", actor_id=user)
    check("새 점주 별칭은 등록되고 이력 ALIAS_ADD", alias_id is not None and await _count(
        db, "select count(*) from knowledge_entity_events where store_id=$1 and entity_id=$2 "
        "and action='ALIAS_ADD'", store_a, latte.entity_id) == 1)
    check("같은 별칭 재등록은 같은 id, 이력 추가 없음",
          await add_owner_alias(db, store_a, latte.entity_id, "라떼카페", actor_id=user) == alias_id
          and await _count(db, "select count(*) from knowledge_entity_events where store_id=$1 "
                           "and entity_id=$2 and action='ALIAS_ADD'", store_a, latte.entity_id) == 1)
    via_alias = await _resolve(db, store_a, "라떼카페")
    check("점주 별칭으로 대상 결정", not via_alias.created and via_alias.entity_id == latte.entity_id)
    try:
        await add_owner_alias(db, store_b, latte.entity_id, "다른매장별칭", actor_id=user)
        other_store = False
    except ValueError:
        other_store = True
    check("다른 매장의 대상에는 별칭을 달지 못한다", other_store)

    # E5 — 이력 불변
    check = _checker("E5")
    for sql in ("update knowledge_entity_events set payload='{}'::jsonb "
                "where store_id=$1 and entity_id=$2",
                "delete from knowledge_entity_events where store_id=$1 and entity_id=$2"):
        try:
            async with db.transaction():
                await db.execute(sql, store_a, first.entity_id)
            blocked = False
        except asyncpg.RaiseError as exc:
            blocked = "불변" in str(exc)
        check(sql.split()[0].upper() + " → 트리거 예외", blocked)

    # E6 — 병합 사슬·결정 불가
    check = _checker("E6")
    keep = await _resolve(db, store_a, "원두A")
    gone = await _resolve(db, store_a, "원두B")
    # Task 5 병합 전이라 상태만 직접 바꾼다(검증 전용)
    await db.execute(
        "update knowledge_entities set status='MERGED', merged_into_entity_id=$3 "
        "where store_id=$1 and entity_id=$2", store_a, gone.entity_id, keep.entity_id)
    followed = await _resolve(db, store_a, "원두B")
    check("MERGED 대상의 별칭 → 살아남은 대상", not followed.created
          and followed.entity_id == keep.entity_id)
    try:
        await _resolve(db, store_a, "!!!")
        unresolvable = False
    except EntityUnresolvable:
        unresolvable = True
    check("문장부호뿐인 이름 → EntityUnresolvable, 행 없음", unresolvable and await _count(
        db, "select count(*) from knowledge_entity_aliases where store_id=$1 and alias_raw='!!!'",
        store_a) == 0)


# ── Task 2 (W2-2) ──────────────────────────────────────────────────────────

_W2_TABLES = ("knowledge_entities", "knowledge_entity_aliases", "knowledge_facts",
              "fact_revisions", "fact_revision_meta", "fact_occurrences",
              "source_fact_revision_links", "fact_conflicts", "fact_revision_requires",
              "fact_owner_answer_links")
_MODEL_SETTINGS = NS(gemini_api_key="synthetic", gemini_model="gemini-synthetic",
                     ingest_mode="real", extract_temperature=0.0, extract_locator_hints=False)


async def _w2_counts(db, store) -> dict[str, int]:
    return {t: await db.fetchval(f"select count(*) from {t} where store_id=$1", store)
            for t in _W2_TABLES}


def _fact(ref, subject, attribute, value, unit="", *, variant="", order=0, ts=0, requires=()):
    return dict(local_ref=ref, original_assertion=f"{subject} {attribute} {value}{unit}",
                subject=subject, attribute=attribute, value=value, unit=unit, variant=variant,
                order=order, requires=list(requires), confidence=.9,
                evidence=dict(timestamp_sec=ts))


class _Ingest:
    """process_source 를 합성 모델 대역으로 돌린다 (F21 본보기)."""

    def __init__(self, db, dsn):
        self.db, self.dsn, self.pool = db, dsn, None

    async def __aenter__(self):
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=2)
        return self

    async def __aexit__(self, *exc):
        await self.pool.close()

    async def run(self, store, user, source, facts, *, run_tag):
        db = self.db
        job_id = await db.fetchval(
            "insert into ingest_jobs (store_id, created_by, title, status, category_version, "
            "prompt_version) values ($1,$2,'W2 연결 검증','EXTRACTING',1,'v1') returning job_id",
            store, user)
        await db.execute("update sources set status='UPLOADED' where store_id=$1 and source_id=$2",
                         store, source)
        await db.execute("insert into ingest_job_sources(store_id,job_id,source_id,status) "
                         "values($1,$2,$3,'QUEUED')", store, job_id, source)
        category = next(iter(await repo.enabled_categories(db, store)))

        async def fake_call(prompt, media, schema=None, max_output_tokens=None):
            if schema is not None and issubclass(schema, FactExtractionResult):
                body = FactExtractionResult.model_validate({"assertions": facts})
                return gemini.CallResult(body.model_dump_json(), {}, "STOP")
            # 사실 조립 — 입력 대상 묶음을 규칙대로 배치한 합성 계획
            payload = json.loads(prompt.split(fact_assembly.PLAN_INPUT_MARKER, 1)[1])
            return gemini.CallResult(mock._planned(payload, [category]).model_dump_json(),
                                     {}, "STOP")

        settings = Settings(_env_file=None)
        with ExitStack() as stack:
            for obj, name, replacement in [
                (pipeline, "get_pool", lambda: self.pool),
                (pipeline, "_preprocess", AsyncMock(return_value=("합성 자료 본문", [], []))),
                (pipeline.shutil, "rmtree", lambda *a, **kw: None),
                (app.config, "get_settings", lambda: settings),
                (extract, "get_settings", lambda: NS(ingest_mode="real")),
                (gemini, "get_settings", lambda: _MODEL_SETTINGS),
                (gemini, "_call", fake_call),
            ]:
                stack.enter_context(patch.object(obj, name, replacement))
            await pipeline.process_source(store, source, job_id=job_id, run_tag=run_tag)
        state = await db.fetchrow("select status, error_message from sources "
                                  "where store_id=$1 and source_id=$2", store, source)
        assert state["status"] == "DONE", f"처리 실패: {state['status']} {state['error_message']}"


class _Rollback(Exception):
    """통과한 문장을 되돌리기 위한 표지."""


async def _blocked(db, sql, *args) -> str | None:
    """문장을 실행해 막히면 예외 문자열, 통과하면 None. 통과해도 되돌린다."""
    try:
        async with db.transaction():
            await db.execute(sql, *args)
            raise _Rollback()
    except _Rollback:
        return None
    except asyncpg.PostgresError as exc:
        return str(exc)


async def _scenario_ledger(db, dsn) -> None:
    video_facts = [
        _fact("f1", "음료Z", "제조 순서", "컵에 얼음을 채운다", order=1, ts=5),
        _fact("f2", "음료Z", "제조 순서", "에스프레소를 붓는다", order=2, ts=12, requires=["f1"]),
        _fact("f3", "음료Z", "제조 순서", "우유를 붓는다", order=3, ts=20, requires=["f2"]),
    ]
    scan_facts = [_fact("f1", "음료 Z", "시럽", "20", "ml")]

    async with _Ingest(db, dsn) as ingest:
        # R1 — 영상 순서 + PDF 수량 → 한 대상
        check = _checker("R1")
        user1, s1, _ = await _seed(db)
        video = await _new_source(db, s1, user1, "VIDEO")
        scan = await _new_source(db, s1, user1, "SCAN")
        await ingest.run(s1, user1, video, video_facts, run_tag=201)
        await ingest.run(s1, user1, scan, scan_facts, run_tag=202)
        counts1 = await _w2_counts(db, s1)
        check("대상 1개", counts1["knowledge_entities"] == 1)
        check("사실 4·판 4·판 메타 4", (counts1["knowledge_facts"], counts1["fact_revisions"],
                                   counts1["fact_revision_meta"]) == (4, 4, 4))
        occ = await db.fetch(
            "select source_id, locator_type, disposition, reason from fact_occurrences "
            "where store_id=$1 order by occurrence_id", s1)
        check("occurrence 는 각 자료로 — 영상 3(TIMESTAMP)·PDF 1",
              [(o["source_id"], o["locator_type"]) for o in occ]
              == [(video, "TIMESTAMP")] * 3 + [(scan, "WHOLE_SOURCE")])
        check("occurrence 는 모두 카드에 LINKED",
              all(o["disposition"] == "LINKED" for o in occ))
        check("충돌 0", counts1["fact_conflicts"] == 0)
        check("절차 선행 관계 2건(단계 2→1, 3→2)", counts1["fact_revision_requires"] == 2)
        entity1 = await db.fetchval("select entity_id from knowledge_entities where store_id=$1", s1)
        kinds = await db.fetch("select link_kind, entity_id from source_fact_revision_links "
                               "where store_id=$1", s1)
        check("연결 4건 모두 CREATED·같은 대상", len(kinds) == 4 and all(
            (k["link_kind"], k["entity_id"]) == ("CREATED", entity1) for k in kinds))
        syrup = await db.fetchrow(
            "select quantity_value, quantity_unit, original_assertion, subject from fact_revisions "
            "where store_id=$1 and predicate='시럽'", s1)
        check("PDF 수량은 수치·단위·원문 그대로",
              (str(syrup["quantity_value"]), syrup["quantity_unit"], syrup["original_assertion"],
               syrup["subject"]) == ("20", "ml", "음료 Z 시럽 20ml", "음료 Z"))
        cards = await db.fetch("select entity_id from knowledge_cards where store_id=$1", s1)
        check("새 카드에 대상 id — 대상마다 카드 하나",
              len(cards) == 1 and all(c["entity_id"] == entity1 for c in cards))

        # R8 에서 쓸 자료 없는 다른 매장
        user0, s0, _ = await _seed(db)

        # R8 — 격리: 다른 매장 id 로 A 의 자료·원장 id 를 넘기면 0건
        check = _checker("R8")
        scan_ids = [r["fact_id"] for r in await db.fetch(
            "select fact_id from source_facts where store_id=$1 and source_id=$2", s1, scan)]
        async with db.transaction():
            outcome = await fact_ledger.link_source_facts(db, s0, scan, scan_ids)
        check("다른 매장으로 연결 → 0건 처리",
              outcome == fact_ledger.LinkOutcome(0, 0, (), 0, 0)
              and all(v == 0 for v in (await _w2_counts(db, s0)).values())
              and await _w2_counts(db, s1) == counts1)
        link1 = await db.fetchrow("select fact_id, fact_revision_id, entity_id from "
                                  "source_fact_revision_links where store_id=$1 and "
                                  "source_fact_id=$2", s1, scan_ids[0])
        error = await _blocked(
            db, "insert into source_fact_revision_links (store_id, source_fact_id, fact_id, "
            "fact_revision_id, entity_id, link_kind) values ($1,$2,$3,$4,$5,'MATCHED')",
            s0, scan_ids[0], link1["fact_id"], link1["fact_revision_id"], link1["entity_id"])
        check("복합 FK 가 다른 매장 원장·사실·판을 가리키는 연결을 막는다",
              error is not None and "foreign key" in error)
        error = await _blocked(
            db, "insert into fact_conflicts (store_id, entity_id, slot_key, fact_id_low, "
            "fact_id_high, value_kind) values ($1,$2,'x',$3,$4,'TEXT')",
            s0, entity1, link1["fact_id"], link1["fact_id"] + 1)
        check("복합 FK 가 다른 매장 사실의 충돌 쌍을 막는다",
              error is not None and "foreign key" in error)
        check("다른 매장으로 카드 대상 조회 → None",
              await fact_ledger.card_entity_for(db, s0, scan_ids) is None
              and await fact_ledger.card_entity_for(db, s1, scan_ids) == entity1)

        # R4 — 같은 자료 재투입 · 같은 내용의 새 자료
        check = _checker("R4")
        await ingest.run(s1, user1, scan, scan_facts, run_tag=203)
        check("같은 자료 다시 처리 → W2 표 행 수 불변", await _w2_counts(db, s1) == counts1)
        scan2 = await _new_source(db, s1, user1, "SCAN")
        await ingest.run(s1, user1, scan2, scan_facts, run_tag=204)
        after = await _w2_counts(db, s1)
        check("같은 내용의 새 자료 → 사실·판 불변, occurrence·연결만 +1",
              (after["knowledge_facts"], after["fact_revisions"], after["fact_conflicts"])
              == (counts1["knowledge_facts"], counts1["fact_revisions"], 0)
              and after["fact_occurrences"] == counts1["fact_occurrences"] + 1
              and after["source_fact_revision_links"] == counts1["source_fact_revision_links"] + 1)
        link2 = await db.fetchrow(
            "select l.link_kind, l.fact_id from source_fact_revision_links l "
            "join source_facts f on f.store_id = l.store_id and f.fact_id = l.source_fact_id "
            "where l.store_id=$1 and f.source_id=$2", s1, scan2)
        first = await db.fetchval(
            "select l.fact_id from source_fact_revision_links l "
            "join source_facts f on f.store_id = l.store_id and f.fact_id = l.source_fact_id "
            "where l.store_id=$1 and f.source_id=$2", s1, scan)
        check("새 자료의 원장 사실은 MATCHED 로 같은 사실에", link2["link_kind"] == "MATCHED"
              and link2["fact_id"] == first)
        check("새 occurrence 는 새 자료를 가리킨다", await db.fetchval(
            "select count(*) from fact_occurrences where store_id=$1 and source_id=$2",
            s1, scan2) == 1)

        # R2 — HOT/ICE 분리
        check = _checker("R2")
        user2, s2, _ = await _seed(db)
        src2 = await _new_source(db, s2, user2, "SCAN")
        await ingest.run(s2, user2, src2, [
            _fact("f1", "음료Z", "물", "275", "ml", variant="HOT"),
            _fact("f2", "아이스 음료Z", "물", "225", "ml")], run_tag=221)
        c2 = await _w2_counts(db, s2)
        temps = [r["variant_temperature"] for r in await db.fetch(
            "select variant_temperature from fact_revisions where store_id=$1 "
            "order by variant_temperature", s2)]
        check("같은 대상, HOT/ICE 두 판", c2["knowledge_entities"] == 1 and temps == ["HOT", "ICE"])
        check("slot 다름·충돌 0", await db.fetchval(
            "select count(distinct slot_key) from knowledge_facts where store_id=$1", s2) == 2
            and c2["fact_conflicts"] == 0)
        user2b, s2b, _ = await _seed(db)
        src2b = await _new_source(db, s2b, user2b, "SCAN")
        await ingest.run(s2b, user2b, src2b, [
            _fact("f1", "음료Z", "물", "275", "ml", variant="HOT"),
            _fact("f2", "음료Z", "물", "275", "ml", variant="ICE")], run_tag=222)
        c2b = await _w2_counts(db, s2b)
        check("값이 같은 HOT 275·ICE 275 → 두 사실(합치지 않는다)·충돌 0",
              c2b["knowledge_facts"] == 2 and c2b["fact_conflicts"] == 0
              and await db.fetchval("select count(distinct identity_key) from knowledge_facts "
                                    "where store_id=$1", s2b) == 2)

        # R3 — 수치 충돌 양쪽 보존
        check = _checker("R3")
        user3, s3, _ = await _seed(db)
        src_a = await _new_source(db, s3, user3, "SCAN")
        src_b = await _new_source(db, s3, user3, "VOICE")
        await ingest.run(s3, user3, src_a, [_fact("f1", "음료Z", "시럽", "20", "ml")], run_tag=231)
        await ingest.run(s3, user3, src_b, [_fact("f1", "음료Z", "시럽", "30", "ml")], run_tag=232)
        c3 = await _w2_counts(db, s3)
        revs = await db.fetch("select quantity_value, original_assertion from fact_revisions "
                              "where store_id=$1 order by quantity_value", s3)
        check("사실 2·판 2, 둘 다 원문·값 그대로", (c3["knowledge_facts"], c3["fact_revisions"]) == (2, 2)
              and [(str(r[0]), r[1]) for r in revs]
              == [("20", "음료Z 시럽 20ml"), ("30", "음료Z 시럽 30ml")])
        conflict = await db.fetchrow("select status, value_kind from fact_conflicts "
                                     "where store_id=$1", s3)
        check("충돌 1행 OPEN·NUMERIC", c3["fact_conflicts"] == 1
              and tuple(conflict) == ("OPEN", "NUMERIC"))
        groups = await fact_ledger.list_open_conflicts(db, s3, entity_id=None)
        facts = groups[0]["facts"] if len(groups) == 1 else []
        evidence = [e for f in facts for e in f["evidence"]]
        check("검수 목록: 두 사실·두 출처·두 날짜", len(facts) == 2
              and {e["source_id"] for e in evidence} == {src_a, src_b}
              and all(e["source_created_at"] is not None for e in evidence)
              and sorted(str(f["quantity_value"]) for f in facts) == ["20", "30"])
        forbidden = {"preferred_fact_id", "selected", "selected_fact_id", "winner", "default",
                     "is_default", "chosen", "recommended"}
        check("선택·승자 칸이 없다", not (forbidden & set(groups[0]))
              and all(not (forbidden & set(f)) for f in facts))
        entity3 = await db.fetchval("select entity_id from knowledge_entities where store_id=$1", s3)
        check("대상으로 거르기·다른 매장은 빈 목록",
              len(await fact_ledger.list_open_conflicts(db, s3, entity_id=entity3)) == 1
              and await fact_ledger.list_open_conflicts(db, s3, entity_id=entity3 + 10_000) == []
              and await fact_ledger.list_open_conflicts(db, s0, entity_id=None) == [])
        per_fact = [await fact_ledger.open_conflicts_for(db, s3, f["fact_id"]) for f in facts]
        check("open_conflicts_for — 두 사실 모두 같은 충돌 1건",
              [len(p) for p in per_fact] == [1, 1]
              and per_fact[0][0]["conflict_id"] == per_fact[1][0]["conflict_id"]
              and await fact_ledger.open_conflicts_for(db, s0, facts[0]["fact_id"]) == [])

        # R5 — 사람 검토 사례 합성 재현
        check = _checker("R5")
        user5, s5, _ = await _seed(db)
        scan5 = await _new_source(db, s5, user5, "SCAN")
        voice5 = await _new_source(db, s5, user5, "VOICE")
        await ingest.run(s5, user5, scan5, [
            _fact("f1", "주문 응대", "원칙", "주문을 받으면 메뉴를 다시 읽어 확인한다")], run_tag=251)
        await ingest.run(s5, user5, voice5, [
            _fact("f1", "주문응대", "방법", "손님 눈을 보고 인사한 뒤 주문을 받는다")], run_tag=252)
        c5 = await _w2_counts(db, s5)
        check("한 대상, 사실 2(속성 다름), 충돌 0",
              (c5["knowledge_entities"], c5["knowledge_facts"], c5["fact_conflicts"]) == (1, 2, 0))

    # R6 — 점주 답변 사실 (결정 F: 메타에만 출처, occurrence·자료 없음)
    check = _checker("R6")

    async def owner_answer(store, user, key):
        member = await db.fetchval(
            "insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') "
            "on conflict (store_id, user_id) do update set member_role = excluded.member_role "
            "returning member_id", store, user)
        question = await db.fetchval(
            "insert into pending_questions(store_id,member_id,question_text,contract_version,"
            "semantic_key) values($1,$2,'합성 질문','v2',$3) returning question_id",
            store, member, key)
        return await db.fetchval(
            "insert into owner_answers(question_id,answered_by,answer_text) "
            "values($1,$2,'음료Z 얼음은 5개') returning answer_id", question, user)

    answer = await owner_answer(s1, user1, "w2-r6")
    other_answer = await owner_answer(s0, user0, "w2-r6-other")
    sources_before = await db.fetchval("select count(*) from sources where store_id=$1", s1)
    occ_before = await db.fetchval("select count(*) from fact_occurrences where store_id=$1", s1)
    kwargs = dict(subject="음료Z", attribute="얼음", value="5", unit="개", variant=None,
                  polarity="AFFIRM", conditions=[], exceptions=[], step_order=None,
                  original_assertion="음료Z 얼음은 5개", actor_id=user1)
    async with db.transaction():
        fact_id, revision_id = await fact_ledger.record_owner_answer_fact(
            db, s1, owner_answer_id=answer, **kwargs)
    meta = await db.fetchrow("select change_kind, owner_answer_id from fact_revision_meta "
                             "where store_id=$1 and fact_revision_id=$2", s1, revision_id)
    check("판 메타에 OWNER_ANSWER·owner_answer_id",
          tuple(meta) == ("OWNER_ANSWER", answer))
    rev = await db.fetchrow("select entity_id, created_by, fact_id from fact_revisions "
                            "where store_id=$1 and fact_revision_id=$2", s1, revision_id)
    check("같은 대상(음료Z)에 붙고 작성자는 점주", tuple(rev) == (entity1, user1, fact_id))
    check("자료·occurrence 를 만들지 않는다",
          await db.fetchval("select count(*) from sources where store_id=$1", s1) == sources_before
          and await db.fetchval("select count(*) from fact_occurrences where store_id=$1", s1)
          == occ_before
          and await db.fetchval("select count(*) from fact_occurrences where store_id=$1 "
                                "and fact_revision_id=$2", s1, revision_id) == 0)
    async with db.transaction():
        again = await fact_ledger.record_owner_answer_fact(db, s1, owner_answer_id=answer, **kwargs)
    check("같은 사실 재기록 → 같은 사실·같은 head, 새 판 없음",
          again == (fact_id, revision_id) and await db.fetchval(
              "select count(*) from fact_revisions where store_id=$1 and fact_id=$2",
              s1, fact_id) == 1)
    async def owner_links(fact):
        return [tuple(r) for r in await db.fetch(
            "select fact_id, fact_revision_id, owner_answer_id from fact_owner_answer_links "
            "where store_id=$1 and fact_id=$2 order by link_id", s1, fact)]

    check("새 사실 — 점주 답변 출처 연결 1행(결정 H)",
          await owner_links(fact_id) == [(fact_id, revision_id, answer)])

    # 결정 H — 이미 있는 같은 사실(R1 의 PDF 수량)에 이어지는 점주 답변도 출처가 남는다
    matched_answer = await owner_answer(s1, user1, "w2-r6-matched")
    syrup_fact = await db.fetchrow(
        "select k.fact_id, k.head_revision_id from knowledge_facts k "
        "join fact_revisions r on r.store_id = k.store_id and r.fact_revision_id = k.head_revision_id "
        "where k.store_id=$1 and r.predicate='시럽'", s1)
    revisions_before = await db.fetchval("select count(*) from fact_revisions where store_id=$1", s1)
    matched_kwargs = dict(kwargs, subject="음료Z", attribute="시럽", value="20", unit="ml",
                          original_assertion="음료Z 시럽은 20ml")
    for _ in range(2):   # 두 번째는 재시도 — 늘지 않아야 한다
        async with db.transaction():
            got = await fact_ledger.record_owner_answer_fact(
                db, s1, owner_answer_id=matched_answer, **matched_kwargs)
    check("같은 사실에 이어진 점주 답변 → 그 사실·head, 새 판 없음",
          got == (syrup_fact["fact_id"], syrup_fact["head_revision_id"])
          and await db.fetchval("select count(*) from fact_revisions where store_id=$1", s1)
          == revisions_before)
    check("같은 사실 경로도 출처 연결 1행, 재시도해도 1행",
          await owner_links(syrup_fact["fact_id"])
          == [(syrup_fact["fact_id"], syrup_fact["head_revision_id"], matched_answer)])
    check("같은 사실 경로도 occurrence·자료를 만들지 않는다",
          await db.fetchval("select count(*) from fact_occurrences where store_id=$1", s1)
          == occ_before
          and await db.fetchval("select count(*) from sources where store_id=$1", s1)
          == sources_before)
    groups_before = await db.fetchval("select count(*) from fact_owner_answer_links "
                                      "where store_id=$1", s1)
    try:
        async with db.transaction():
            await fact_ledger.record_owner_answer_fact(db, s1, owner_answer_id=other_answer,
                                                       **kwargs)
        crossed = True
    except ValueError:
        crossed = False
    check("다른 매장의 답변 id → 예외", not crossed)
    try:
        async with db.transaction():
            await fact_ledger.record_owner_answer_fact(db, s1, owner_answer_id=other_answer,
                                                       **matched_kwargs)
        crossed = True
    except ValueError:
        crossed = False
    check("같은 사실 경로도 다른 매장 답변 id → 예외, 연결 없음", not crossed
          and await db.fetchval("select count(*) from fact_owner_answer_links where store_id=$1",
                                s1) == groups_before)
    error = await _blocked(
        db, "insert into fact_owner_answer_links (store_id, fact_id, fact_revision_id, "
        "owner_answer_id) values ($1,$2,$3,$4)",
        s1, syrup_fact["fact_id"], syrup_fact["head_revision_id"], other_answer)
    check("DB 트리거가 다른 매장 답변의 출처 연결을 막는다", error is not None and "매장" in error)
    error = await _blocked(
        db, "insert into fact_revision_meta (fact_revision_id, store_id, fact_id, change_kind, "
        "identity_key, slot_key, owner_answer_id) values ($1,$2,$3,'OWNER_ANSWER','x','y',$4)",
        revision_id, s1, fact_id, other_answer)
    check("DB 트리거도 다른 매장 답변을 막는다", error is not None and "매장" in error)

    # R7 — 불변과 짝
    check = _checker("R7")
    error = await _blocked(db, "update fact_revisions set assertion='x' "
                               "where store_id=$1 and fact_revision_id=$2", s1, revision_id)
    check("W 가 만든 판 UPDATE → 트리거 예외", error is not None and "불변" in error)
    error = await _blocked(db, "update fact_revision_meta set reason='x' "
                               "where store_id=$1 and fact_revision_id=$2", s1, revision_id)
    check("판 메타 UPDATE → 트리거 예외", error is not None and "불변" in error)
    for store in (s1, s2, s2b, s3, s5):
        orphans = await db.fetchval(
            "select count(*) from fact_revisions r "
            "left join fact_revision_meta m on m.store_id = r.store_id "
            "  and m.fact_revision_id = r.fact_revision_id "
            "left join knowledge_facts k on k.store_id = r.store_id and k.fact_id = r.fact_id "
            "where r.store_id=$1 and (m.fact_revision_id is null or k.fact_id is null)", store)
        headless = await db.fetchval("select count(*) from knowledge_facts where store_id=$1 "
                                     "and head_revision_id is null", store)
        check(f"매장 {store}: 모든 판이 메타·사실 정체와 짝, head 포인터 채움",
              orphans == 0 and headless == 0)

    # R9 — 평가 매장 초기화 STEPS 가 W2 표까지 지운다
    check = _checker("R9")
    with patch("dotenv.load_dotenv", lambda *a, **kw: None):
        reset = importlib.import_module("reset_eval_store")
    keep = await _w2_counts(db, s1)
    async with db.transaction():
        for _, sql in reset.STEPS:
            if "$1" in sql:
                await db.execute(sql, s3)
            else:
                await db.execute(sql)
    check("대상 매장의 W2 표·자료가 비었다",
          all(v == 0 for v in (await _w2_counts(db, s3)).values())
          and await db.fetchval("select count(*) from sources where store_id=$1", s3) == 0)
    check("다른 매장은 그대로", await _w2_counts(db, s1) == keep)
    disabled = await db.fetchval(
        "select count(*) from pg_trigger where tgname = any($1::text[]) and tgenabled <> 'O'",
        ["trg_fact_revision_meta_immutable", "trg_fact_revision_immutable",
         "trg_entity_event_immutable"])
    check("불변 트리거는 다시 켜져 있다", disabled == 0)


# ── Task 3 (W2-3) ──────────────────────────────────────────────────────────

async def _new_owner_answer(db, store, user, key, text="합성 점주 답변"):
    member = await db.fetchval(
        "insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') "
        "on conflict (store_id, user_id) do update set member_role = excluded.member_role "
        "returning member_id", store, user)
    question = await db.fetchval(
        "insert into pending_questions(store_id,member_id,question_text,contract_version,"
        "semantic_key) values($1,$2,'합성 질문','v2',$3) returning question_id",
        store, member, key)
    return await db.fetchval(
        "insert into owner_answers(question_id,answered_by,answer_text) "
        "values($1,$2,$3) returning answer_id", question, user, text)


async def _published_fingerprint(db, store) -> dict:
    """공개본·카드 행 수와 전체 행 내용 해시. 정정 전후로 같아야 한다."""
    out = {}
    for table in ("knowledge_snapshots", "card_versions", "knowledge_cards"):
        row = await db.fetchrow(
            f"select count(*) n, md5(coalesce(string_agg(t::text, '|' order by t::text), '')) h "
            f"from {table} t where store_id=$1", store)
        out[table] = (row["n"], row["h"])
    return out


async def _rows_text(db, table, key, store) -> dict:
    return {r["k"]: r["t"] for r in await db.fetch(
        f"select {key} k, t::text t from {table} t where store_id=$1", store)}


async def _scenario_revisions(db, dsn) -> None:
    from app.ingest.fact_revisions import (FactChange, StaleFactRevision, dismiss_conflict,
                                           import_legacy_correction, revise_fact)

    # R3 과 같은 합성: 같은 대상·같은 속성에 20 ml(스캔)·30 ml(음성), 절차 3단계(영상)
    async with _Ingest(db, dsn) as ingest:
        user, s, _ = await _seed(db)
        scan = await _new_source(db, s, user, "SCAN")
        voice = await _new_source(db, s, user, "VOICE")
        video = await _new_source(db, s, user, "VIDEO")
        await ingest.run(s, user, scan, [_fact("f1", "음료Z", "시럽", "20", "ml")], run_tag=301)
        await ingest.run(s, user, voice, [_fact("f1", "음료Z", "시럽", "30", "ml")], run_tag=302)
        await ingest.run(s, user, video, [
            _fact("f1", "음료Z", "제조 순서", "컵에 얼음을 채운다", order=1, ts=5),
            _fact("f2", "음료Z", "제조 순서", "에스프레소를 붓는다", order=2, ts=12,
                  requires=["f1"])], run_tag=303)
    # V6 기준 — 합성 snapshot 한 행을 넣어 빈 표 비교가 되지 않게 한다
    await db.execute(
        "insert into knowledge_snapshots (store_id, knowledge_revision, snapshot_hash, "
        "glossary_version, renderer_version) values ($1, 1, $2, 'g-verify', 'r-verify')",
        s, "sha256:" + "a" * 64)
    published_before = await _published_fingerprint(db, s)
    revisions_before = await _rows_text(db, "fact_revisions", "fact_revision_id", s)
    meta_before = await _rows_text(db, "fact_revision_meta", "fact_revision_id", s)
    ledger_before = await _rows_text(db, "source_facts", "fact_id", s)
    occurrences_before = await _count(db, "select count(*) from fact_occurrences where store_id=$1", s)
    sources_before = await _count(db, "select count(*) from sources where store_id=$1", s)

    async def fact_of(source_id):
        return await db.fetchrow(
            "select l.source_fact_id, k.fact_id, k.head_revision_id, k.identity_key "
            "from source_fact_revision_links l "
            "join source_facts f on f.store_id = l.store_id and f.fact_id = l.source_fact_id "
            "join knowledge_facts k on k.store_id = l.store_id and k.fact_id = l.fact_id "
            "where l.store_id=$1 and f.source_id=$2 order by f.fact_id", s, source_id)

    async def revision_count(fact_id=None):
        if fact_id is None:
            return await _count(db, "select count(*) from fact_revisions where store_id=$1", s)
        return await _count(db, "select count(*) from fact_revisions where store_id=$1 "
                                "and fact_id=$2", s, fact_id)

    f20, f30 = await fact_of(scan), await fact_of(voice)
    conflict = await db.fetchrow("select conflict_id, status from fact_conflicts where store_id=$1",
                                 s)
    assert conflict["status"] == "OPEN", "합성 전제: 20·30 OPEN 충돌"

    # V1 — 점주 정정은 새 판
    check = _checker("V1")
    new20 = await revise_fact(
        db, s, fact_id=f20["fact_id"], expected_head_revision_id=f20["head_revision_id"],
        change=FactChange(value="30", original_assertion="시럽은 30ml 로 바꿨어요"),
        change_kind="OWNER_CORRECTION", actor_id=user)
    rev = await db.fetchrow(
        "select supersedes_revision_id, created_by, quantity_value, quantity_unit, "
        "original_assertion, assertion, subject, predicate, entity_id, fact_id "
        "from fact_revisions where store_id=$1 and fact_revision_id=$2", s, new20)
    old = await db.fetchrow("select entity_id from fact_revisions where store_id=$1 "
                            "and fact_revision_id=$2", s, f20["head_revision_id"])
    check("새 판은 옛 판을 잇고 작성자는 점주",
          (rev["supersedes_revision_id"], rev["created_by"], rev["fact_id"])
          == (f20["head_revision_id"], user, f20["fact_id"]))
    check("새 판 값 30 ml·원문은 점주 말·주어·속성·대상 그대로",
          (str(rev["quantity_value"]), rev["quantity_unit"], rev["original_assertion"],
           rev["assertion"], rev["subject"], rev["predicate"], rev["entity_id"])
          == ("30", "ml", "시럽은 30ml 로 바꿨어요", "시럽은 30ml 로 바꿨어요", "음료Z", "시럽",
              old["entity_id"]))
    after = await _rows_text(db, "fact_revisions", "fact_revision_id", s)
    check("옛 판은 한 글자도 바뀌지 않았다",
          all(after[k] == v for k, v in revisions_before.items()))
    meta_after = await _rows_text(db, "fact_revision_meta", "fact_revision_id", s)
    check("옛 판 메타도 그대로", all(meta_after[k] == v for k, v in meta_before.items()))
    ledger = await db.fetchrow("select value, corrected_value from source_facts "
                               "where store_id=$1 and fact_id=$2", s, f20["source_fact_id"])
    check("원장 source_facts.value='20' 그대로·corrected_value 비어 있음",
          tuple(ledger) == ("20", None))
    meta = await db.fetchrow(
        "select change_kind, applied_at, created_at, owner_answer_id, legacy_source_fact_id "
        "from fact_revision_meta where store_id=$1 and fact_revision_id=$2", s, new20)
    check("메타 OWNER_CORRECTION·applied_at 채움·점주 답변/legacy 없음",
          meta["change_kind"] == "OWNER_CORRECTION" and meta["applied_at"] is not None
          and meta["owner_answer_id"] is None and meta["legacy_source_fact_id"] is None)
    head = await db.fetchrow("select head_revision_id, identity_key from knowledge_facts "
                             "where store_id=$1 and fact_id=$2", s, f20["fact_id"])
    check("head 는 새 판, identity 는 30 ml 사실과 같아졌다",
          head["head_revision_id"] == new20 and head["identity_key"] == f30["identity_key"])
    settled = await db.fetchrow(
        "select status, resolution, decided_by, decided_at from fact_conflicts "
        "where store_id=$1 and conflict_id=$2", s, conflict["conflict_id"])
    resolution = settled["resolution"]
    resolution = json.loads(resolution) if isinstance(resolution, str) else resolution
    check("충돌 RESOLVED·by CORRECTION·새 판 id·결정자",
          settled["status"] == "RESOLVED" and settled["decided_at"] is not None
          and resolution == {"by": "CORRECTION", "fact_revision_id": new20}
          and settled["decided_by"] == user)
    check("두 사실 모두 남는다", await _count(
        db, "select count(*) from knowledge_facts where store_id=$1 and fact_id = any($2::bigint[])",
        s, [f20["fact_id"], f30["fact_id"]]) == 2
        and await fact_ledger.list_open_conflicts(db, s, entity_id=None) == [])
    check("정정은 occurrence·자료를 만들지 않는다", await _count(
        db, "select count(*) from fact_occurrences where store_id=$1", s) == occurrences_before)
    step2 = await db.fetchrow(
        "select k.fact_id, k.head_revision_id from knowledge_facts k "
        "join fact_revisions r on r.store_id = k.store_id and r.fact_revision_id = k.head_revision_id "
        "where k.store_id=$1 and r.step_order = 2", s)
    step1_rev = await db.fetchval(
        "select requires_revision_id from fact_revision_requires where store_id=$1 "
        "and fact_revision_id=$2", s, step2["head_revision_id"])
    new_step2 = await revise_fact(
        db, s, fact_id=step2["fact_id"], expected_head_revision_id=step2["head_revision_id"],
        change=FactChange(value="샷을 두 번 붓는다", original_assertion="샷은 두 번 부어요"),
        change_kind="OWNER_CORRECTION", actor_id=user)
    copied = [r["requires_revision_id"] for r in await db.fetch(
        "select requires_revision_id from fact_revision_requires where store_id=$1 "
        "and fact_revision_id=$2", s, new_step2)]
    check("head 의 선행 관계를 새 판으로 복사, 옛 판의 선행 관계도 그대로",
          step1_rev is not None and copied == [step1_rev] and await _count(
              db, "select count(*) from fact_revision_requires where store_id=$1 "
              "and fact_revision_id=$2", s, step2["head_revision_id"]) == 1)
    step2_rev = await db.fetchrow("select step_order, value_text, quantity_value from "
                                  "fact_revisions where store_id=$1 and fact_revision_id=$2",
                                  s, new_step2)
    check("값만 바꾸면 단계는 그대로·서술값", tuple(step2_rev) == (2, "샷을 두 번 붓는다", None))

    # V2 — 같은 기대 head 로 다시 → Stale
    check = _checker("V2")
    count = await revision_count()
    try:
        await revise_fact(
            db, s, fact_id=f20["fact_id"], expected_head_revision_id=f20["head_revision_id"],
            change=FactChange(value="40", original_assertion="40ml 예요"),
            change_kind="OWNER_CORRECTION", actor_id=user)
        stale = False
    except StaleFactRevision:
        stale = True
    check("옛 head 로 정정 → StaleFactRevision, 판 수 불변", stale and await revision_count() == count)
    try:
        await revise_fact(db, s + 10_000, fact_id=f20["fact_id"], expected_head_revision_id=new20,
                          change=FactChange(value="40", original_assertion="40ml 예요"),
                          change_kind="OWNER_CORRECTION", actor_id=user)
        missing = False
    except LookupError:
        missing = True
    check("다른 매장 id 로 정정 → LookupError, 판 수 불변",
          missing and await revision_count() == count)

    # V3 — legacy corrected_value 이관 (멱등)
    check = _checker("V3")
    await db.execute("update source_facts set corrected_value='35', corrected_by=$3 "
                     "where store_id=$1 and fact_id=$2", s, f30["source_fact_id"], user)
    corrected_at = await db.fetchval("select corrected_at from source_facts where store_id=$1 "
                                     "and fact_id=$2", s, f30["source_fact_id"])
    first = await import_legacy_correction(db, s, source_fact_id=f30["source_fact_id"])
    second = await import_legacy_correction(db, s, source_fact_id=f30["source_fact_id"])
    check("두 번 불러도 같은 판 1개", first is not None and first == second
          and await revision_count(f30["fact_id"]) == 2)
    legacy = await db.fetchrow(
        "select m.change_kind, m.applied_at, m.reason, m.legacy_source_fact_id, r.created_by, "
        "r.supersedes_revision_id, r.original_assertion, r.quantity_value, r.quantity_unit "
        "from fact_revision_meta m join fact_revisions r on r.store_id = m.store_id "
        "  and r.fact_revision_id = m.fact_revision_id "
        "where m.store_id=$1 and m.fact_revision_id=$2", s, first)
    check("LEGACY_CORRECTION·applied_at=corrected_at·created_by=corrected_by",
          (legacy["change_kind"], legacy["applied_at"], legacy["created_by"],
           legacy["legacy_source_fact_id"], legacy["reason"])
          == ("LEGACY_CORRECTION", corrected_at, user, f30["source_fact_id"],
              "source_facts.corrected_value 이관"))
    check("값 35 ml·원문=corrected_value·옛 head 를 잇는다",
          (str(legacy["quantity_value"]), legacy["quantity_unit"], legacy["original_assertion"],
           legacy["supersedes_revision_id"]) == ("35", "ml", "35", f30["head_revision_id"]))
    check("원장 value 30·corrected_value 35 그대로", tuple(await db.fetchrow(
        "select value, corrected_value from source_facts where store_id=$1 and fact_id=$2",
        s, f30["source_fact_id"])) == ("30", "35"))
    check("corrected_value 없는 원장 → None", await import_legacy_correction(
        db, s, source_fact_id=f20["source_fact_id"]) is None)
    check("다른 매장 id → None, 판 불변", await import_legacy_correction(
        db, s + 10_000, source_fact_id=f30["source_fact_id"]) is None
        and await revision_count(f30["fact_id"]) == 2)
    reopened = await db.fetch(
        "select status from fact_conflicts where store_id=$1 order by conflict_id", s)
    check("값이 다시 갈라지면(30·35) 같은 쌍에 새 OPEN, 옛 RESOLVED 행은 그대로",
          [r["status"] for r in reopened] == ["RESOLVED", "OPEN"])

    # V4 — 점주 답변 정정 (결정 F·H: 메타·연결 표에 출처, occurrence·자료 없음)
    check = _checker("V4")
    answer = await _new_owner_answer(db, s, user, "w2-v4", "시럽은 25ml 예요")
    _, other_store, _ = await _seed(db)
    other_answer = await _new_owner_answer(db, other_store, user, "w2-v4-other")
    count = await revision_count()
    try:
        await revise_fact(db, s, fact_id=f20["fact_id"], expected_head_revision_id=new20,
                          change=FactChange(value="25", original_assertion="시럽은 25ml 예요"),
                          change_kind="OWNER_ANSWER", actor_id=user, owner_answer_id=other_answer)
        crossed = True
    except ValueError:
        crossed = False
    check("다른 매장의 점주 답변 → ValueError, 판 수 불변",
          not crossed and await revision_count() == count)
    by_answer = await revise_fact(
        db, s, fact_id=f20["fact_id"], expected_head_revision_id=new20,
        change=FactChange(value="25", original_assertion="시럽은 25ml 예요"),
        change_kind="OWNER_ANSWER", actor_id=user, owner_answer_id=answer)
    meta = await db.fetchrow("select change_kind, owner_answer_id from fact_revision_meta "
                             "where store_id=$1 and fact_revision_id=$2", s, by_answer)
    check("메타에 OWNER_ANSWER·owner_answer_id", tuple(meta) == ("OWNER_ANSWER", answer))
    check("점주 답변 출처 연결 1행(새 판)", [tuple(r) for r in await db.fetch(
        "select fact_id, fact_revision_id, owner_answer_id from fact_owner_answer_links "
        "where store_id=$1 and owner_answer_id=$2", s, answer)]
        == [(f20["fact_id"], by_answer, answer)])
    check("occurrence·자료 없음(source 없음)",
          await _count(db, "select count(*) from fact_occurrences where store_id=$1 "
                           "and fact_revision_id=$2", s, by_answer) == 0
          and await _count(db, "select count(*) from fact_occurrences where store_id=$1", s)
          == occurrences_before
          and await _count(db, "select count(*) from sources where store_id=$1", s)
          == sources_before)
    check("supersedes 사슬 20→30→25", await db.fetchval(
        "select supersedes_revision_id from fact_revisions where store_id=$1 "
        "and fact_revision_id=$2", s, by_answer) == new20)

    # V5 — 충돌 기각
    check = _checker("V5")
    open_id = await db.fetchval("select conflict_id from fact_conflicts where store_id=$1 "
                                "and status='OPEN' order by conflict_id limit 1", s)
    try:
        await dismiss_conflict(db, s + 10_000, open_id, actor_id=user, note="x")
        other = False
    except LookupError:
        other = True
    check("다른 매장 id 로 기각 → LookupError, 상태 그대로", other and await db.fetchval(
        "select status from fact_conflicts where store_id=$1 and conflict_id=$2", s, open_id)
        == "OPEN")
    await dismiss_conflict(db, s, open_id, actor_id=user, note="둘 다 맞는 값")
    dismissed = await db.fetchrow("select status, decided_by, decided_at, resolution "
                                  "from fact_conflicts where store_id=$1 and conflict_id=$2",
                                  s, open_id)
    note = dismissed["resolution"]
    note = json.loads(note) if isinstance(note, str) else note
    check("DISMISSED·결정자·시각·note", dismissed["status"] == "DISMISSED"
          and dismissed["decided_by"] == user and dismissed["decided_at"] is not None
          and note.get("note") == "둘 다 맞는 값")
    try:
        await dismiss_conflict(db, s, open_id, actor_id=user, note="again")
        again = False
    except ValueError:
        again = True
    check("다시 기각 → ValueError", again)
    check("기각해도 두 사실은 남는다", await _count(
        db, "select count(*) from knowledge_facts where store_id=$1", s) == 4)
    check("기각 당시 두 사실의 head 판 id 를 남긴다", note == {
        "note": "둘 다 맞는 값", "dismissed_revision_ids": {
            str(min(f20["fact_id"], f30["fact_id"])): by_answer if f20["fact_id"] < f30["fact_id"]
            else first,
            str(max(f20["fact_id"], f30["fact_id"])): first if f20["fact_id"] < f30["fact_id"]
            else by_answer}})

    # 결정 I — 기각한 쌍은 값이 바뀔 때만 새 OPEN
    async def pair_statuses():
        return [r["status"] for r in await db.fetch(
            "select status from fact_conflicts where store_id=$1 and fact_id_low=$2 "
            "and fact_id_high=$3 order by conflict_id",
            s, *sorted((f20["fact_id"], f30["fact_id"])))]

    async def head_of(fact_id):
        return await db.fetchval("select head_revision_id from knowledge_facts where store_id=$1 "
                                 "and fact_id=$2", s, fact_id)

    statuses = await pair_statuses()
    worded = await revise_fact(
        db, s, fact_id=f20["fact_id"], expected_head_revision_id=await head_of(f20["fact_id"]),
        change=FactChange(original_assertion="시럽은 25 ml 넣어요"),
        change_kind="OWNER_CORRECTION", actor_id=user)
    check("문구만 바꾼 정정(값 25 그대로) → 기각 유지, 새 OPEN 없음",
          worded is not None and await pair_statuses() == statuses)
    for fact in (f20, f30):   # 두 사실 모두 같은 조건으로 — 새 slot 에서 다시 만나지만 값은 그대로
        await revise_fact(
            db, s, fact_id=fact["fact_id"], expected_head_revision_id=await head_of(fact["fact_id"]),
            change=FactChange(conditions=("바쁠 때",), original_assertion="바쁠 때 기준이에요"),
            change_kind="OWNER_CORRECTION", actor_id=user)
    same_slot = await _count(db, "select count(distinct slot_key) from knowledge_facts "
                                 "where store_id=$1 and fact_id = any($2::bigint[])",
                             s, [f20["fact_id"], f30["fact_id"]])
    check("조건만 바꾼 정정(두 사실 같은 새 slot, 값 그대로) → 기각 유지, 새 OPEN 없음",
          same_slot == 1 and await pair_statuses() == statuses
          and await fact_ledger.list_open_conflicts(db, s, entity_id=None) == [])
    await revise_fact(
        db, s, fact_id=f20["fact_id"], expected_head_revision_id=await head_of(f20["fact_id"]),
        change=FactChange(value="26", original_assertion="시럽은 26ml 예요"),
        change_kind="OWNER_CORRECTION", actor_id=user)
    check("값을 바꾼 정정(25→26) → 같은 쌍에 새 OPEN, 기각 행은 그대로",
          await pair_statuses() == statuses + ["OPEN"]
          and len(await fact_ledger.list_open_conflicts(db, s, entity_id=None)) == 1)

    # V6 — 공개본 불변
    check = _checker("V6")
    published_after = await _published_fingerprint(db, s)
    check("knowledge_snapshots·card_versions·knowledge_cards 행 수·내용 해시 동일",
          published_after == published_before
          and published_before["knowledge_snapshots"][0] == 1
          and published_before["card_versions"][0] > 0)
    ledger_after = await _rows_text(db, "source_facts", "fact_id", s)
    check("원장 source_facts 는 legacy 입력(corrected_*)을 넣은 행 말고 그대로", all(
        ledger_after[k] == v for k, v in ledger_before.items() if k != f30["source_fact_id"]))


# ── Task 4 (W2-4) ──────────────────────────────────────────────────────────

_VECTOR = [1.0] + [0.0] * 1535


async def _proposal_rows(db, store) -> dict:
    """제안 머리·항목 행 전체 텍스트(재처리 전후 비교용)."""
    return {
        "heads": await _rows_text(db, "upload_change_proposals", "proposal_id", store),
        "items": {f"{r['p']}:{r['f']}": r["t"] for r in await db.fetch(
            "select proposal_id p, fact_revision_id f, t::text t "
            "from upload_change_proposal_facts t where store_id=$1", store)},
    }


async def _card_rows(db, store, card_ids) -> dict:
    return {r["card_id"]: r["j"] for r in await db.fetch(
        "select card_id, to_jsonb(k)::text j from knowledge_cards k "
        "where store_id=$1 and card_id = any($2::bigint[])", store, list(card_ids))}


async def _scenario_proposals(db, dsn) -> None:
    from app.contracts.usage import UsageContext
    from app.publish.approval import CardChange, publish_cards

    async def fake_embedder(texts, *, context, sink=None):
        return [list(_VECTOR) for _ in texts]

    async def source_card(store, source):
        return await db.fetchval("select card_id from knowledge_cards where store_id=$1 "
                                 "and source_id=$2 order by card_id limit 1", store, source)

    async with _Ingest(db, dsn) as ingest:
        # P1 — 자료 A → 카드 X 승인·발행, MANUAL 로 옮김 · 다른 대상 카드 Y · ICE 뿐인 카드 Z
        check = _checker("P1")
        user, s, _ = await _seed(db)
        member = await db.fetchval(
            "insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') "
            "returning member_id", s, user)
        src_a = await _new_source(db, s, user, "SCAN")
        src_y = await _new_source(db, s, user, "SCAN")
        src_z = await _new_source(db, s, user, "SCAN")
        await ingest.run(s, user, src_a, [_fact("f1", "음료Q", "시럽", "20", "ml"),
                                          _fact("f2", "음료Q", "얼음", "100", "g")],
                         run_tag=401)
        await ingest.run(s, user, src_y, [_fact("f1", "음료W", "시럽", "15", "ml")],
                         run_tag=402)
        await ingest.run(s, user, src_z, [_fact("f1", "음료V", "시럽", "12", "ml",
                                                variant="ICE")],
                         run_tag=403)
        first = await db.fetch("select relation_type, matched_cards::text m "
                               "from upload_change_proposals where store_id=$1", s)
        check("승인 카드가 없을 때 처리한 자료 3개 → 제안 3행 모두 NEW·빈 matched_cards",
              len(first) == 3 and all((r["relation_type"], r["m"]) == ("NEW", "[]")
                                      for r in first))
        x, y, z = [await source_card(s, src) for src in (src_a, src_y, src_z)]
        drafts = {r["card_id"]: r["draft_version_id"] for r in await db.fetch(
            "select card_id, draft_version_id from knowledge_cards where store_id=$1 "
            "and card_id = any($2::bigint[])", s, [x, y, z])}
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            with patch("app.reg.index_preparation.recorded_embeddings", fake_embedder):
                published = await publish_cards(
                    pool, store_id=s, member_id=member, actor_user_id=user,
                    changes=[CardChange(c, drafts[c], drafts[c]) for c in (x, y, z)],
                    idempotency_key="w2-p1-publish",
                    usage_context=UsageContext(
                        store_id=str(s), cost_phase="OPERATING", cost_purpose="PRODUCT",
                        stage="EMBED", operation_id="w2-p1", logical_call_id="w2-p1:embed"))
        finally:
            await pool.close()
        check("X·Y·Z 발행", published.status == "PUBLISHED")
        moved = await db.fetchval(
            "insert into task_categories(store_id,category_name) values($1,'W2 옮긴 곳') "
            "returning category_id", s)
        await db.execute("update knowledge_cards set assignment_type='MANUAL', category_id=$3 "
                         "where store_id=$1 and card_id=$2", s, x, moved)
        rows_before = await _card_rows(db, s, (x, y, z))
        x_row = await db.fetchrow(
            "select review_status, published_version_id, assignment_type, category_id "
            "from knowledge_cards where store_id=$1 and card_id=$2", s, x)
        check("X 는 APPROVED·공개 판·MANUAL·옮긴 카테고리",
              x_row["review_status"] == "APPROVED" and x_row["published_version_id"] is not None
              and (x_row["assignment_type"], x_row["category_id"]) == ("MANUAL", moved))

        async def snapshot_state():
            return (await _count(db, "select count(*) from knowledge_snapshots where store_id=$1", s),
                    await db.fetchval(
                        "select ks.snapshot_hash from knowledge_publications kp "
                        "join knowledge_snapshots ks on ks.snapshot_id = kp.current_snapshot_id "
                        "where kp.store_id=$1", s))
        snap_before = await snapshot_state()
        check("current snapshot 이 있다", snap_before[0] >= 1 and snap_before[1] is not None)

        # P2 — 자료 B: 같은 사실 1 + 충돌 값 1 + 새 속성 1
        check = _checker("P2")
        src_b = await _new_source(db, s, user, "VOICE")
        b_facts = [_fact("f1", "음료Q", "시럽", "20", "ml"),
                   _fact("f2", "음료Q", "얼음", "150", "g"),
                   _fact("f3", "음료Q", "우유", "200", "ml")]
        await ingest.run(s, user, src_b, b_facts, run_tag=404)
        heads = await db.fetch(
            "select proposal_id, entity_id, job_id, relation_type, status, matched_cards "
            "from upload_change_proposals where store_id=$1 and source_id=$2", s, src_b)
        check("머리 1행 CONFLICT·PENDING_REVIEW·작업 id",
              len(heads) == 1 and heads[0]["relation_type"] == "CONFLICT"
              and heads[0]["status"] == "PENDING_REVIEW" and heads[0]["job_id"] is not None)
        matched = json.loads(heads[0]["matched_cards"])
        check("matched_cards = [X 와 그 공개 판]", matched == [{
            "card_id": x, "published_version_id": x_row["published_version_id"],
            "review_status": "APPROVED"}])
        items = await db.fetch(
            "select i.relation_type, r.predicate, i.fact_id, i.conflict_fact_ids, "
            "i.affected_card_ids from upload_change_proposal_facts i "
            "join fact_revisions r on r.store_id = i.store_id "
            "  and r.fact_revision_id = i.fact_revision_id "
            "where i.store_id=$1 and i.proposal_id=$2 order by r.predicate",
            s, heads[0]["proposal_id"])
        by_predicate = {i["predicate"]: i for i in items}
        check("항목 3 — 시럽 IDENTICAL·얼음 CONFLICT·우유 SUPPLEMENT",
              {k: v["relation_type"] for k, v in by_predicate.items()}
              == {"시럽": "IDENTICAL", "얼음": "CONFLICT", "우유": "SUPPLEMENT"})
        ice_a = await db.fetchval(
            "select l.fact_id from source_fact_revision_links l join source_facts sf "
            "on sf.store_id=l.store_id and sf.fact_id=l.source_fact_id "
            "where l.store_id=$1 and sf.source_id=$2 and sf.attribute='얼음'", s, src_a)
        check("CONFLICT 항목의 충돌 상대 = A 의 얼음 사실",
              list(by_predicate["얼음"]["conflict_fact_ids"]) == [ice_a])
        check("항목의 영향 카드 = X 만 (B 자기 카드·Y·Z 없음)",
              all(list(i["affected_card_ids"]) == [x] for i in items))
        columns = {r["column_name"] for r in await db.fetch(
            "select column_name from information_schema.columns "
            "where table_name in ('upload_change_proposals','upload_change_proposal_facts')")}
        check("제안 표에 선택·승자 칸 없음",
              not any(w in c for c in columns for w in ("prefer", "winner", "selected", "default")))

        # P3 — 영향 없는 카드·공개본 보존
        check = _checker("P3")
        check("X·Y·Z 행 전체(to_jsonb, updated_at 포함) B 전후 동일",
              await _card_rows(db, s, (x, y, z)) == rows_before)
        check("snapshot 새 행 없음·current snapshot hash 동일", await snapshot_state() == snap_before)
        x_after = await db.fetchrow(
            "select published_version_id, assignment_type, category_id "
            "from knowledge_cards where store_id=$1 and card_id=$2", s, x)
        check("X 공개 판·MANUAL·카테고리 그대로",
              (x_after["published_version_id"], x_after["assignment_type"],
               x_after["category_id"]) == (x_row["published_version_id"], "MANUAL", moved))
        check("점주 답변 제안 표는 쓰지 않는다", await _count(
            db, "select count(*) from knowledge_change_proposals where store_id=$1", s) == 0)

        # P4 — B 재처리 → 제안·항목 불변
        check = _checker("P4")
        props_before = await _proposal_rows(db, s)
        await ingest.run(s, user, src_b, b_facts, run_tag=405)
        check("제안·항목 행 수·내용(updated_at 포함) 불변",
              await _proposal_rows(db, s) == props_before)
        check("재처리 뒤에도 X·Y·Z 행 그대로", await _card_rows(db, s, (x, y, z)) == rows_before)

        # P6 — ICE 뿐인 승인 카드 Z 와 같은 대상의 HOT 사실
        # Phase A(A-D4): 공개된 자동 사실 카드는 새 사실을 붙인 새 초안을 받는다. 여기서는 영향
        # 계산의 규격 규칙만 보려고 Z 를 수동 배정으로 옮겨 카드 쓰기를 막는다(불변식 12)
        check = _checker("P6")
        await db.execute("update knowledge_cards set assignment_type='MANUAL' "
                         "where store_id=$1 and card_id=$2", s, z)
        z_before = (await _card_rows(db, s, (z,)))[z]
        src_hot = await _new_source(db, s, user, "KAKAO")
        await ingest.run(s, user, src_hot, [_fact("f1", "음료V", "시럽", "10", "ml",
                                                  variant="HOT")],
                         run_tag=406)
        hot = await db.fetchrow(
            "select p.relation_type, p.matched_cards::text m, i.relation_type item, "
            "i.affected_card_ids from upload_change_proposals p "
            "join upload_change_proposal_facts i on i.store_id=p.store_id "
            "  and i.proposal_id=p.proposal_id "
            "where p.store_id=$1 and p.source_id=$2", s, src_hot)
        check("Z 는 영향 없음 → NEW·빈 matched_cards",
              (hot["relation_type"], hot["m"], hot["item"]) == ("NEW", "[]", "NEW")
              and z not in list(hot["affected_card_ids"]))
        check("Z 행 그대로", (await _card_rows(db, s, (z,)))[z] == z_before)

        # P7 (결정 J) — 자료 처리 → 같은 대상 다른 값 카드 승인 → 자료 재처리
        check = _checker("P7")
        user7, s7, _ = await _seed(db)
        member7 = await db.fetchval(
            "insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') "
            "returning member_id", s7, user7)
        first7 = await _new_source(db, s7, user7, "SCAN")
        other7 = await _new_source(db, s7, user7, "VOICE")
        first_facts = [_fact("f1", "음료K", "시럽", "30", "ml")]
        # 대상마다 카드가 하나다. 먼저 처리한 자료(40 ml)가 카드를 만들고 두 자료의 사실이 거기 실린다.
        # 자료는 자기가 만든 카드에 제안하지 않으므로, 30 ml 자료의 재처리가 그 카드에 CONFLICT 를 낸다
        await ingest.run(s7, user7, other7, [_fact("f1", "음료K", "시럽", "40", "ml")],
                         run_tag=410)
        await ingest.run(s7, user7, first7, first_facts, run_tag=409)
        before7 = await db.fetch(
            "select p.source_id, p.relation_type head, i.relation_type item "
            "from upload_change_proposals p join upload_change_proposal_facts i "
            "on i.store_id=p.store_id and i.proposal_id=p.proposal_id where p.store_id=$1", s7)
        check("승인 전 두 자료 제안 모두 NEW", len(before7) == 2 and all(
            (r["head"], r["item"]) == ("NEW", "NEW") for r in before7))
        card7 = await source_card(s7, other7)
        draft7 = await db.fetchval("select draft_version_id from knowledge_cards "
                                   "where store_id=$1 and card_id=$2", s7, card7)
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            with patch("app.reg.index_preparation.recorded_embeddings", fake_embedder):
                published7 = await publish_cards(
                    pool, store_id=s7, member_id=member7, actor_user_id=user7,
                    changes=[CardChange(card7, draft7, draft7)], idempotency_key="w2-p7-publish",
                    usage_context=UsageContext(
                        store_id=str(s7), cost_phase="OPERATING", cost_purpose="PRODUCT",
                        stage="EMBED", operation_id="w2-p7", logical_call_id="w2-p7:embed"))
        finally:
            await pool.close()
        check("40 ml 카드 발행", published7.status == "PUBLISHED")
        # 결정된 제안 — 40 ml 자료의 제안을 점주가 기각했다
        await db.execute(
            "update upload_change_proposals set status='DISMISSED', decided_by=$3, "
            "decided_at=now() where store_id=$1 and source_id=$2", s7, other7, user7)
        dismissed_before = await _proposal_rows(db, s7)
        await ingest.run(s7, user7, first7, first_facts, run_tag=411)
        head7 = await db.fetchrow(
            "select proposal_id, relation_type, status, matched_cards "
            "from upload_change_proposals where store_id=$1 and source_id=$2", s7, first7)
        check("재처리 → 머리 NEW → CONFLICT, matched_cards 에 승인 카드",
              (head7["relation_type"], head7["status"]) == ("CONFLICT", "PENDING_REVIEW")
              and [m["card_id"] for m in json.loads(head7["matched_cards"])] == [card7])
        forty = await db.fetchval(
            "select l.fact_id from source_fact_revision_links l join source_facts sf "
            "on sf.store_id=l.store_id and sf.fact_id=l.source_fact_id "
            "where l.store_id=$1 and sf.source_id=$2", s7, other7)
        items7 = await db.fetch(
            "select relation_type, conflict_fact_ids, affected_card_ids "
            "from upload_change_proposal_facts where store_id=$1 and proposal_id=$2",
            s7, head7["proposal_id"])
        check("항목도 CONFLICT · 충돌 상대 = 40 ml 사실 · 영향 카드 = 승인 카드",
              len(items7) == 1 and items7[0]["relation_type"] == "CONFLICT"
              and list(items7[0]["conflict_fact_ids"]) == [forty]
              and list(items7[0]["affected_card_ids"]) == [card7])
        # 기각된 자료를 새 사실과 함께 재처리 → 기각 제안은 항목도 머리도 그대로
        await ingest.run(s7, user7, other7, [_fact("f1", "음료K", "시럽", "40", "ml"),
                                             _fact("f2", "음료K", "우유", "150", "ml")],
                         run_tag=412)
        dismissed_id = await db.fetchval(
            "select proposal_id from upload_change_proposals where store_id=$1 and source_id=$2",
            s7, other7)
        after_rows = await _proposal_rows(db, s7)
        check("DISMISSED 제안 — 새 사실을 더한 재처리에도 머리·항목 행 그대로",
              after_rows["heads"][dismissed_id] == dismissed_before["heads"][dismissed_id]
              and {k: v for k, v in after_rows["items"].items()
                   if k.startswith(f"{dismissed_id}:")}
              == {k: v for k, v in dismissed_before["items"].items()
                  if k.startswith(f"{dismissed_id}:")}
              and await _count(db, "select count(*) from source_fact_revision_links l "
                                   "join source_facts sf on sf.store_id=l.store_id "
                                   "and sf.fact_id=l.source_fact_id "
                                   "where l.store_id=$1 and sf.source_id=$2", s7, other7) == 2)

        # P5 — 첫 자료만 있는 새 매장
        check = _checker("P5")
        user5, s5, _ = await _seed(db)
        first5 = await _new_source(db, s5, user5, "SCAN")
        await ingest.run(s5, user5, first5, b_facts, run_tag=407)
        rows5 = await db.fetch(
            "select p.relation_type head, p.matched_cards::text m, i.relation_type item "
            "from upload_change_proposals p join upload_change_proposal_facts i "
            "on i.store_id=p.store_id and i.proposal_id=p.proposal_id where p.store_id=$1", s5)
        check("머리·항목 모두 NEW", len(rows5) == 3 and all(
            (r["head"], r["m"], r["item"]) == ("NEW", "[]", "NEW") for r in rows5))
        check("새 매장 제안은 첫 자료의 1행뿐", await _count(
            db, "select count(*) from upload_change_proposals where store_id=$1", s5) == 1)
        async with db.transaction():
            from app.ingest.impact import affected_cards, record_upload_proposals
            crossed = await record_upload_proposals(db, s5, src_b, job_id=None)
            revs = [r["fact_revision_id"] for r in await db.fetch(
                "select fact_revision_id from upload_change_proposal_facts where store_id=$1", s)]
            leak = await affected_cards(db, s5, revs, exclude_source_id=None)
        check("다른 매장 자료·판 id → 제안 0·영향 카드 없음",
              crossed == 0 and leak.card_ids == ())

        # 평가 매장 초기화 STEPS 가 제안 표까지 지운다 (다른 매장 제안은 그대로)
        with patch("dotenv.load_dotenv", lambda *a, **kw: None):
            reset = importlib.import_module("reset_eval_store")
        keep = await _proposal_rows(db, s)
        async with db.transaction():
            for _, sql in reset.STEPS:
                await (db.execute(sql, s5) if "$1" in sql else db.execute(sql))
        check("초기화 STEPS → 새 매장 제안·항목 0행, 다른 매장 제안 그대로",
              await _count(db, "select count(*) from upload_change_proposals "
                               "where store_id=$1", s5) == 0
              and await _count(db, "select count(*) from upload_change_proposal_facts "
                                   "where store_id=$1", s5) == 0
              and await _proposal_rows(db, s) == keep)


# ── Task 5 (W2-4 ③) ────────────────────────────────────────────────────────

async def _scenario_entity_admin(db, dsn) -> None:
    from app.contracts.usage import UsageContext
    from app.ingest.entity_admin import (decide_candidate, merge_entities, relink_fact,
                                         split_entity)
    from app.ingest.fact_revisions import StaleFactRevision
    from app.publish.approval import CardChange, publish_cards

    async def fake_embedder(texts, *, context, sink=None):
        return [list(_VECTOR) for _ in texts]

    async def fact_by(store, subject, attribute, value):
        """원장 사실 → (source_fact_id, knowledge_facts 행)."""
        return await db.fetchrow(
            "select l.source_fact_id, l.entity_id as link_entity_id, k.fact_id, k.entity_id, "
            "k.head_revision_id, k.identity_key, k.slot_key "
            "from source_facts f "
            "join source_fact_revision_links l on l.store_id = f.store_id "
            "  and l.source_fact_id = f.fact_id "
            "join knowledge_facts k on k.store_id = l.store_id and k.fact_id = l.fact_id "
            "where f.store_id=$1 and f.subject=$2 and f.attribute=$3 and f.value=$4 "
            "order by f.fact_id limit 1", store, subject, attribute, value)

    async def events(store, action):
        return await db.fetch(
            "select entity_id, other_entity_id, fact_id, fact_revision_id, actor_id, payload "
            "from knowledge_entity_events where store_id=$1 and action=$2 order by event_id",
            store, action)

    async def raises(exc_type, coro):
        try:
            await coro
        except exc_type:
            return True
        return False

    def payload(row):
        value = row["payload"]
        return json.loads(value) if isinstance(value, str) else value

    async with _Ingest(db, dsn) as ingest:
        user, s, _ = await _seed(db)
        member = await db.fetchval(
            "insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') "
            "returning member_id", s, user)
        # 합성: 우유(보관 위치 + 잘못 들어온 스팀 온도 65), 다른 자료의 스팀 온도 70 → OPEN 충돌
        src_milk = await _new_source(db, s, user, "SCAN")
        src_steam = await _new_source(db, s, user, "VOICE")
        await ingest.run(s, user, src_milk, [_fact("f1", "우유", "보관 위치", "냉장고 2칸"),
                                             _fact("f2", "우유", "스팀 온도", "65", "도")],
                         run_tag=501)
        await ingest.run(s, user, src_steam, [_fact("f1", "우유", "스팀 온도", "70", "도")],
                         run_tag=502)
        # 합성: 카페라떼·카페라테 → 대상 둘 + 후보(E2 와 같은 경우). 같은 값 시럽 20 ml 가 양쪽에 있다
        src_latte = await _new_source(db, s, user, "SCAN")
        src_latte2 = await _new_source(db, s, user, "VOICE")
        await ingest.run(s, user, src_latte, [_fact("f1", "카페라떼", "시럽", "20", "ml")],
                         run_tag=503)
        await ingest.run(s, user, src_latte2, [_fact("f1", "카페라테", "시럽", "20", "ml"),
                                               _fact("f2", "카페라테", "우유", "200", "ml")],
                         run_tag=504)

        # S3 기준 — 우유 자료 카드를 실제 발행해 공개본을 만든다
        card_ids = [r["card_id"] for r in await db.fetch(
            "select card_id from knowledge_cards where store_id=$1 order by card_id", s)]
        milk_card = await db.fetchval("select card_id from knowledge_cards where store_id=$1 "
                                      "and source_id=$2 order by card_id limit 1", s, src_milk)
        draft = await db.fetchval("select draft_version_id from knowledge_cards "
                                  "where store_id=$1 and card_id=$2", s, milk_card)
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            with patch("app.reg.index_preparation.recorded_embeddings", fake_embedder):
                published = await publish_cards(
                    pool, store_id=s, member_id=member, actor_user_id=user,
                    changes=[CardChange(milk_card, draft, draft)],
                    idempotency_key="w2-s3-publish",
                    usage_context=UsageContext(
                        store_id=str(s), cost_phase="OPERATING", cost_purpose="PRODUCT",
                        stage="EMBED", operation_id="w2-s3", logical_call_id="w2-s3:embed"))
        finally:
            await pool.close()
        assert published.status == "PUBLISHED", "합성 전제: 우유 카드 발행"

    async def public_state():
        return {
            "cards": await _card_rows(db, s, card_ids),
            "versions": await _rows_text(db, "card_versions", "version_id", s),
            "snapshots": await _count(db, "select count(*) from knowledge_snapshots "
                                          "where store_id=$1", s),
            "current_hash": await db.fetchval(
                "select ks.snapshot_hash from knowledge_publications kp "
                "join knowledge_snapshots ks on ks.snapshot_id = kp.current_snapshot_id "
                "where kp.store_id=$1", s),
            "card_facts": await _count(db, "select count(*) from card_facts where store_id=$1", s),
            "proposals": await _proposal_rows(db, s),
        }
    public_before = await public_state()
    revisions_before = await _rows_text(db, "fact_revisions", "fact_revision_id", s)
    meta_before = await _rows_text(db, "fact_revision_meta", "fact_revision_id", s)
    occurrences_before = await _rows_text(db, "fact_occurrences", "occurrence_id", s)
    links_before = await _rows_text(db, "source_fact_revision_links", "source_fact_id", s)

    # S1 — 대상 분리
    check = _checker("S1")
    storage = await fact_by(s, "우유", "보관 위치", "냉장고 2칸")
    steam65 = await fact_by(s, "우유", "스팀 온도", "65")
    steam70 = await fact_by(s, "우유", "스팀 온도", "70")
    milk = storage["entity_id"]
    check("합성 전제 — 세 사실 모두 우유 대상, 65·70 OPEN 충돌",
          steam65["entity_id"] == steam70["entity_id"] == milk and await _count(
              db, "select count(*) from fact_conflicts where store_id=$1 and status='OPEN' "
              "and fact_id_low=$2 and fact_id_high=$3", s,
              *sorted((steam65["fact_id"], steam70["fact_id"]))) == 1)
    await add_owner_alias(db, s, milk, "스팀 우유", actor_id=user)
    check("분리할 사실이 그 대상 것이 아니면 ValueError·쓰기 없음", await raises(
        ValueError, split_entity(db, s, entity_id=milk, fact_ids=[steam65["fact_id"], 10 ** 9],
                                 new_canonical_name="우유 거품", move_alias_norms=[],
                                 actor_id=user))
        and await _count(db, "select count(*) from knowledge_entities where store_id=$1 "
                             "and name_norm='우유거품'", s) == 0)
    new = await split_entity(db, s, entity_id=milk, fact_ids=[steam65["fact_id"]],
                             new_canonical_name="우유 거품", move_alias_norms=["스팀우유"],
                             actor_id=user)
    row = await db.fetchrow("select canonical_name, name_norm, status from knowledge_entities "
                            "where store_id=$1 and entity_id=$2", s, new)
    check("새 대상 우유 거품·ACTIVE", new != milk
          and tuple(row) == ("우유 거품", "우유거품", "ACTIVE"))
    aliases = {(r["entity_id"], r["alias_norm"], r["origin"], r["retired_at"] is None)
               for r in await db.fetch(
                   "select entity_id, alias_norm, origin, retired_at from knowledge_entity_aliases "
                   "where store_id=$1 and alias_norm in ('우유거품','스팀우유')", s)}
    check("별칭 — 새 이름 SYSTEM, 옮긴 스팀우유는 원 대상에서 retire 후 새 대상 OWNER",
          aliases == {(new, "우유거품", "SYSTEM", True), (milk, "스팀우유", "OWNER", False),
                      (new, "스팀우유", "OWNER", True)})
    moved = await fact_by(s, "우유", "스팀 온도", "65")
    head = await db.fetchrow(
        "select r.entity_id, r.supersedes_revision_id, r.original_assertion, r.assertion, "
        "r.quantity_value, r.quantity_unit, r.subject, r.predicate, r.created_by, "
        "m.change_kind, m.reason, m.slot_key, m.identity_key "
        "from fact_revisions r join fact_revision_meta m on m.store_id=r.store_id "
        "  and m.fact_revision_id=r.fact_revision_id "
        "where r.store_id=$1 and r.fact_revision_id=$2", s, moved["head_revision_id"])
    old = await db.fetchrow(
        "select entity_id, original_assertion, assertion, quantity_value, quantity_unit, "
        "subject, predicate from fact_revisions where store_id=$1 and fact_revision_id=$2",
        s, steam65["head_revision_id"])
    check("사실의 head 는 RELINK 판 — supersedes 옛 판, entity 만 바뀜",
          moved["fact_id"] == steam65["fact_id"] and moved["entity_id"] == new
          and moved["head_revision_id"] != steam65["head_revision_id"]
          and head["entity_id"] == new
          and head["supersedes_revision_id"] == steam65["head_revision_id"]
          and head["change_kind"] == "RELINK" and "대상 분리" in head["reason"]
          and head["created_by"] == user and old["entity_id"] == milk
          and tuple(head[k] for k in ("original_assertion", "assertion", "quantity_value",
                                      "quantity_unit", "subject", "predicate"))
          == tuple(old[k] for k in ("original_assertion", "assertion", "quantity_value",
                                    "quantity_unit", "subject", "predicate")))
    check("knowledge_facts 의 slot·identity 가 새 판 메타와 같다",
          (moved["slot_key"], moved["identity_key"]) == (head["slot_key"], head["identity_key"])
          and moved["slot_key"] != steam65["slot_key"])
    revisions_now = await _rows_text(db, "fact_revisions", "fact_revision_id", s)
    check("옛 판·옛 메타·occurrence·원장 연결 행 그대로 (새 판 1개만 늘었다)",
          {k: v for k, v in revisions_now.items() if k in revisions_before} == revisions_before
          and len(revisions_now) == len(revisions_before) + 1
          and {k: v for k, v in (await _rows_text(db, "fact_revision_meta", "fact_revision_id",
                                                  s)).items() if k in meta_before} == meta_before
          and await _rows_text(db, "fact_occurrences", "occurrence_id", s) == occurrences_before
          and await _rows_text(db, "source_fact_revision_links", "source_fact_id", s)
          == links_before)
    check("분리하지 않은 사실은 원 대상·head 그대로",
          tuple(await fact_by(s, "우유", "보관 위치", "냉장고 2칸")) == tuple(storage))
    conflict = await db.fetchrow(
        "select status, resolution, decided_by from fact_conflicts where store_id=$1 "
        "and fact_id_low=$2 and fact_id_high=$3 order by conflict_id",
        s, *sorted((steam65["fact_id"], steam70["fact_id"])))
    resolution = json.loads(conflict["resolution"]) if isinstance(conflict["resolution"], str) \
        else conflict["resolution"]
    check("옛 슬롯 OPEN 충돌 → OBSOLETE (by RELINK, 새 판 id), 두 사실 모두 남음",
          conflict["status"] == "OBSOLETE" and conflict["decided_by"] == user
          and resolution == {"by": "RELINK", "fact_revision_id": moved["head_revision_id"]}
          and await _count(db, "select count(*) from knowledge_facts where store_id=$1 "
                               "and fact_id = any($2::bigint[])",
                           s, [steam65["fact_id"], steam70["fact_id"]]) == 2)
    split_events = await events(s, "SPLIT")
    relinks = await events(s, "RELINK_FACT")
    check("이력 SPLIT(fact_ids·옮긴 별칭)·RELINK_FACT(from→to, 사실, 새 판)·CREATE",
          len(split_events) == 1
          and (split_events[0]["entity_id"], split_events[0]["other_entity_id"]) == (milk, new)
          and payload(split_events[0])["fact_ids"] == [steam65["fact_id"]]
          and payload(split_events[0])["moved_aliases"] == ["스팀우유"]
          and [(r["entity_id"], r["other_entity_id"], r["fact_id"], r["fact_revision_id"])
               for r in relinks]
          == [(milk, new, steam65["fact_id"], moved["head_revision_id"])]
          and payload(relinks[0])["from_revision_id"] == steam65["head_revision_id"]
          and len([e for e in await events(s, "CREATE") if e["entity_id"] == new]) == 1
          and len(await events(s, "ALIAS_RETIRE")) == 1)
    candidate = await db.fetchrow(
        "select reason, status, decided_by, decided_at from knowledge_entity_candidates "
        "where store_id=$1 and entity_id_low=$2 and entity_id_high=$3", s, *sorted((milk, new)))
    check("후보 쌍 SPLIT·CONFIRMED_DIFFERENT",
          candidate is not None and (candidate["reason"], candidate["status"],
                                     candidate["decided_by"]) == ("SPLIT", "CONFIRMED_DIFFERENT",
                                                                  user)
          and candidate["decided_at"] is not None)
    check("별칭 조회 — 스팀 우유 → 새 대상, 우유 → 원 대상",
          (await _resolve(db, s, "스팀 우유")).entity_id == new
          and (await _resolve(db, s, "우유")).entity_id == milk)
    check("card_entity_for 는 사실의 지금 대상, 원장 연결 행은 연결 당시 대상(이력)",
          await fact_ledger.card_entity_for(db, s, [steam65["source_fact_id"]]) == new
          and moved["link_entity_id"] == milk)

    # 재연결 — 70 사실도 새 대상으로 옮기면 새 슬롯에서 충돌을 다시 계산한다
    before_count = len(revisions_now)
    check("같은 대상으로 재연결 → ValueError, 판 수 불변", await raises(
        ValueError, relink_fact(db, s, fact_id=steam70["fact_id"],
                                expected_head_revision_id=steam70["head_revision_id"],
                                to_entity_id=milk, actor_id=user, reason="같은 곳"))
        and await _count(db, "select count(*) from fact_revisions where store_id=$1", s)
        == before_count)
    relinked = await relink_fact(db, s, fact_id=steam70["fact_id"],
                                 expected_head_revision_id=steam70["head_revision_id"],
                                 to_entity_id=new, actor_id=user, reason="스팀 온도는 거품 대상")
    reopened = await db.fetch(
        "select entity_id, status from fact_conflicts where store_id=$1 "
        "and fact_id_low=$2 and fact_id_high=$3 order by conflict_id",
        s, *sorted((steam65["fact_id"], steam70["fact_id"])))
    check("relink_fact → 새 대상 슬롯에서 같은 쌍 OPEN(새 대상), 옛 OBSOLETE 행 그대로",
          [(r["entity_id"], r["status"]) for r in reopened]
          == [(milk, "OBSOLETE"), (new, "OPEN")])
    check("같은 기대 head 로 다시 → StaleFactRevision, 판 수 불변", await raises(
        StaleFactRevision, relink_fact(db, s, fact_id=steam70["fact_id"],
                                       expected_head_revision_id=steam70["head_revision_id"],
                                       to_entity_id=milk, actor_id=user, reason="되돌림"))
        and await _count(db, "select count(*) from fact_revisions where store_id=$1", s)
        == before_count + 1)
    check("재연결 이력 사유가 payload 에 남는다",
          payload((await events(s, "RELINK_FACT"))[-1])
          == {"reason": "스팀 온도는 거품 대상", "from_revision_id": steam70["head_revision_id"]}
          and (await events(s, "RELINK_FACT"))[-1]["fact_revision_id"] == relinked)

    # S2 — 병합 (E2 와 같은 카페라떼/카페라테 후보)
    check = _checker("S2")
    latte = await fact_by(s, "카페라떼", "시럽", "20")
    latte2_syrup = await fact_by(s, "카페라테", "시럽", "20")
    latte2_milk = await fact_by(s, "카페라테", "우유", "200")
    keep, gone = latte["entity_id"], latte2_syrup["entity_id"]
    pending = [c for c in await list_candidates(db, s)
               if {c["entity_id_low"], c["entity_id_high"]} == {keep, gone}]
    check("합성 전제 — 두 대상, PENDING EDIT1 후보 1, 같은 값 시럽 사실 둘",
          keep != gone and len(pending) == 1 and pending[0]["reason"] == "EDIT1"
          and latte["fact_id"] != latte2_syrup["fact_id"])
    moved_count = await merge_entities(db, s, keep_entity_id=keep, merged_entity_id=gone,
                                       actor_id=user, candidate_id=pending[0]["candidate_id"])
    gone_row = await db.fetchrow("select status, merged_into_entity_id from knowledge_entities "
                                 "where store_id=$1 and entity_id=$2", s, gone)
    check("옮긴 사실 2, merged 는 MERGED·merged_into=keep",
          moved_count == 2 and tuple(gone_row) == ("MERGED", keep))
    after = [await fact_by(s, "카페라테", "시럽", "20"), await fact_by(s, "카페라테", "우유", "200")]
    kinds = [await db.fetchval("select change_kind from fact_revision_meta where store_id=$1 "
                               "and fact_revision_id=$2", s, f["head_revision_id"]) for f in after]
    check("사실 이동 — 두 사실 모두 keep, head 는 RELINK 판",
          all(f["entity_id"] == keep for f in after) and kinds == ["RELINK", "RELINK"]
          and [f["head_revision_id"] for f in after]
          != [latte2_syrup["head_revision_id"], latte2_milk["head_revision_id"]])
    check("별칭 카페라테 → keep (OWNER), 옛 별칭 retire",
          await find_entity_by_alias(db, s, "카페라테") == keep
          and await _count(db, "select count(*) from knowledge_entity_aliases where store_id=$1 "
                               "and alias_norm='카페라테' and entity_id=$2 and origin='OWNER' "
                               "and retired_at is null", s, keep) == 1
          and await _count(db, "select count(*) from knowledge_entity_aliases where store_id=$1 "
                               "and entity_id=$2 and retired_at is null", s, gone) == 0)
    resolved = await _resolve(db, s, "카페라테")
    check("이후 resolve_entity('카페라테') → keep, 새 대상 없음",
          resolved.entity_id == keep and not resolved.created)
    same = [latte["fact_id"], after[0]["fact_id"]]
    check("같은 값이 된 두 사실 — 둘 다 남고 같은 identity, 충돌 아님 (A-4)",
          after[0]["identity_key"] == (await fact_by(s, "카페라떼", "시럽", "20"))["identity_key"]
          and await _count(db, "select count(*) from fact_conflicts where store_id=$1 "
                               "and status='OPEN' and fact_id_low=$2 and fact_id_high=$3",
                           s, *sorted(same)) == 0)
    decided = await db.fetchrow("select status, decided_by from knowledge_entity_candidates "
                                "where store_id=$1 and candidate_id=$2",
                                s, pending[0]["candidate_id"])
    merge_events = await events(s, "MERGE")
    check("후보 CONFIRMED_SAME·이력 MERGE(fact_ids·옮긴 별칭·후보)",
          tuple(decided) == ("CONFIRMED_SAME", user) and len(merge_events) == 1
          and (merge_events[0]["entity_id"], merge_events[0]["other_entity_id"]) == (keep, gone)
          and payload(merge_events[0]) == {
              "fact_ids": sorted([latte2_syrup["fact_id"], latte2_milk["fact_id"]]),
              "moved_aliases": ["카페라테"], "candidate_id": pending[0]["candidate_id"]})
    check("MERGED 대상으로 재연결·다시 병합 → ValueError", await raises(
        ValueError, relink_fact(db, s, fact_id=latte["fact_id"],
                                expected_head_revision_id=latte["head_revision_id"],
                                to_entity_id=gone, actor_id=user, reason="병합된 곳"))
        and await raises(ValueError, merge_entities(db, s, keep_entity_id=keep,
                                                     merged_entity_id=gone, actor_id=user,
                                                     candidate_id=None)))
    # 후보 결정(다른 대상·기각) — merge 밖 경로
    bean = await _resolve(db, s, "원두")
    bean2 = await _resolve(db, s, "원두 보관")
    bean_pair = [c for c in await list_candidates(db, s)
                 if {c["entity_id_low"], c["entity_id_high"]} == {bean.entity_id, bean2.entity_id}]
    await decide_candidate(db, s, bean_pair[0]["candidate_id"], decision="DISMISSED",
                           actor_id=user)
    check("decide_candidate → DISMISSED·이력 CANDIDATE_DECIDED, 다시 → ValueError",
          await db.fetchval("select status from knowledge_entity_candidates where store_id=$1 "
                            "and candidate_id=$2", s, bean_pair[0]["candidate_id"]) == "DISMISSED"
          and payload((await events(s, "CANDIDATE_DECIDED"))[-1])
          == {"candidate_id": bean_pair[0]["candidate_id"], "decision": "DISMISSED"}
          and await raises(ValueError, decide_candidate(
              db, s, bean_pair[0]["candidate_id"], decision="CONFIRMED_DIFFERENT",
              actor_id=user)))

    # S3 — 공개본 보존
    check = _checker("S3")
    public_after = await public_state()
    check("카드 행(to_jsonb)·card_versions·card_facts 동일",
          public_after["cards"] == public_before["cards"]
          and public_after["versions"] == public_before["versions"]
          and public_after["card_facts"] == public_before["card_facts"])
    check("snapshot 수·current snapshot hash 동일",
          public_after["snapshots"] == public_before["snapshots"] >= 1
          and public_after["current_hash"] == public_before["current_hash"] is not None)
    check("업로드 제안 머리·항목 동일(자동 변경 없음)",
          public_after["proposals"] == public_before["proposals"]
          and len(public_before["proposals"]["heads"]) >= 1)
    check("우유 카드 entity_id 는 그대로(재배치는 W3)",
          await db.fetchval("select entity_id from knowledge_cards where store_id=$1 "
                            "and card_id=$2", s, milk_card) == milk)

    # 병합 뒤 새 자료 — 카페라테 이름은 keep 으로 이어지고 새 카드도 keep
    async with _Ingest(db, dsn) as ingest:
        src_after = await _new_source(db, s, user, "SCAN")
        await ingest.run(s, user, src_after, [_fact("f1", "카페라테", "시럽", "20", "ml")],
                         run_tag=505)
    link = await fact_by(s, "카페라테", "시럽", "20")
    new_link = await db.fetchrow(
        "select l.entity_id, l.link_kind, l.fact_id from source_fact_revision_links l "
        "join source_facts f on f.store_id=l.store_id and f.fact_id=l.source_fact_id "
        "where l.store_id=$1 and f.source_id=$2", s, src_after)
    check("병합 뒤 새 자료 카페라테 → keep 에 MATCHED(가장 작은 fact_id), 사실은 keep 대상의 카드에 실림",
          link is not None and tuple(new_link) == (keep, "MATCHED", latte["fact_id"])
          and await db.fetchval(
              "select c.entity_id from fact_occurrences o join knowledge_cards c "
              "on c.store_id = o.store_id and c.card_id = o.card_id "
              "where o.store_id=$1 and o.source_id=$2 and o.disposition='LINKED'",
              s, src_after) == keep)

    # S4 — 다른 매장의 대상·후보·사실
    check = _checker("S4")
    _, t, _ = await _seed(db)
    foreign = await _resolve(db, t, "우유")
    counts = await _w2_counts(db, s)
    storage_now = await fact_by(s, "우유", "보관 위치", "냉장고 2칸")
    check("다른 매장 entity_id 로 relink → LookupError, 행 수 불변", await raises(
        LookupError, relink_fact(db, s, fact_id=storage_now["fact_id"],
                                 expected_head_revision_id=storage_now["head_revision_id"],
                                 to_entity_id=foreign.entity_id, actor_id=user, reason="교차"))
        and await _w2_counts(db, s) == counts)
    check("다른 매장 id 로 사실 relink → LookupError", await raises(
        LookupError, relink_fact(db, t, fact_id=storage_now["fact_id"],
                                 expected_head_revision_id=storage_now["head_revision_id"],
                                 to_entity_id=foreign.entity_id, actor_id=user, reason="교차")))
    blocked = await _blocked(db, "update knowledge_facts set entity_id=$3 "
                                 "where store_id=$1 and fact_id=$2",
                             s, storage_now["fact_id"], foreign.entity_id)
    check("직접 써도 복합 FK 가 매장 교차를 막는다", blocked is not None and "foreign key" in blocked)
    check("다른 매장에서 split·merge·후보 결정 → LookupError",
          await raises(LookupError, split_entity(db, t, entity_id=milk,
                                                 fact_ids=[storage_now["fact_id"]],
                                                 new_canonical_name="교차 대상",
                                                 move_alias_norms=[], actor_id=user))
          and await raises(LookupError, merge_entities(db, t, keep_entity_id=foreign.entity_id,
                                                        merged_entity_id=milk, actor_id=user,
                                                        candidate_id=None))
          and await raises(LookupError, decide_candidate(db, t, bean_pair[0]["candidate_id"],
                                                          decision="DISMISSED", actor_id=user))
          and await _w2_counts(db, s) == counts
          and await _count(db, "select count(*) from knowledge_entities where store_id=$1", t)
          == 1)


async def verify(db, dsn):
    # 설정은 함수 안에서 읽으므로 patch 가 먹는다 (F21). 후보 상한은 기본값 5
    settings = Settings(_env_file=None)
    with patch.object(app.config, "get_settings", lambda: settings):
        await _scenario_entities(db)
        await _scenario_ledger(db, dsn)
        await _scenario_revisions(db, dsn)
        await _scenario_proposals(db, dsn)
        await _scenario_entity_admin(db, dsn)
    print("PASS W entity revision all scenarios")
