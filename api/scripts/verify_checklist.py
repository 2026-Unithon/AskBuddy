"""P5 체크리스트 종단 검증. verify_r_schema_rebuild 가 만든 일회용 DB 에서만 돈다(운영·개발 DB 금지).

라우트 함수를 직접 불러 권한·격리·범위·영업일·제출·개인 기록을 확인한다.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.checklist import router as cl
from app.checklist.schemas import CardLinks, CheckRequest, IdList, MySettings, Settings, ShiftCreate, SubmissionRequest
from app.db_session import ShortSession
from app.errors import ApiError

# 서울 2026-10-07 15:00 (UTC 06:00) — 영업일 10/7, 미들 시간
NOON = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 7)


async def _expect(code, coro):
    try:
        await coro
    except ApiError as exc:
        assert exc.code == code, (exc.code, code)
        return exc
    raise AssertionError(f"expected {code}")


async def verify(pool, db):
    session = ShortSession(pool)
    owner = await db.fetchval("insert into users(name,role) values('합성 체크 점주','OWNER') returning user_id")
    staff = await db.fetchval("insert into users(name,role) values('합성 체크 알바','STAFF') returning user_id")
    quiet = await db.fetchval("insert into users(name,role) values('합성 기록끔 알바','STAFF') returning user_id")
    sid = await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'합성 체크 매장','CAFE') returning store_id", owner)
    await db.execute("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER')", sid, owner)
    staff_mid = await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'STAFF') returning member_id", sid, staff)
    await db.execute("insert into store_members(store_id,user_id,member_role) values($1,$2,'STAFF')", sid, quiet)
    other_owner = await db.fetchval("insert into users(name,role) values('합성 다른 점주','OWNER') returning user_id")
    other = await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'합성 다른 매장','CAFE') returning store_id", other_owner)
    await db.execute("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER')", other, other_owner)

    async def card(store, title, content, status="APPROVED"):
        # 레거시 판 트리거가 없어졌다(Phase A) — 판 1 을 명시적으로 만들고, 승인 상태면 공개 포인터도 둔다.
        # 체크리스트는 공개 판의 본문 줄만 읽으므로 사실 블록은 필요 없다
        card_id = await db.fetchval("""insert into knowledge_cards(store_id,title,content,review_status)
            values($1,$2,$3,$4) returning card_id""", store, title, content, status)
        version_id = await db.fetchval("""insert into card_versions(store_id,card_id,version_no,title,content,change_source)
            values($1,$2,1,$3,$4,'EXTRACTION') returning version_id""", store, card_id, title, content)
        await db.execute("""update knowledge_cards set draft_version_id=$3::bigint,
            published_version_id=case when review_status='APPROVED' then $3::bigint end
            where store_id=$1 and card_id=$2""", store, card_id, version_id)
        return card_id

    common = await card(sid, '합성 공통', '물 채우기')
    opening = await card(sid, '합성 오픈', '머신 켜기\n원두 소분')
    closing = await card(sid, '합성 마감', '머신 청소')
    draft = await card(sid, '합성 초안', '보이면 안 됨', status='PENDING')
    foreign = await card(other, '합성 남의 카드', '남의 줄')

    o = dict(store_id=sid, user_id=owner, role='OWNER')
    s = dict(store_id=sid, user_id=staff, role='STAFF')
    q = dict(store_id=sid, user_id=quiet, role='STAFF')
    x = dict(store_id=other, user_id=other_owner, role='OWNER')

    # 권한·격리
    await _expect('OWNER_ONLY', cl.create_shift(ShiftCreate(name='합성'), session, s))
    await _expect('MEMBERSHIP_REQUIRED', cl.list_shifts(session, dict(store_id=sid, user_id=other_owner, role='OWNER')))
    print('PASS checklist owner-only and membership')

    shifts = (await cl.create_preset(session, o))['items']
    await _expect('SHIFTS_EXIST', cl.create_preset(session, o))
    open_id, middle_id, close_id = (sh['shift_id'] for sh in shifts)
    await _expect('SHIFT_NAME_TAKEN', cl.create_shift(ShiftCreate(name=' 오픈 '), session, o))
    await _expect('SHIFT_NOT_FOUND', cl.set_shift_cards(open_id, IdList(ids=[]), session, x))
    await _expect('CARD_NOT_FOUND', cl.set_shift_cards(open_id, IdList(ids=[foreign]), session, o))
    print('PASS checklist preset, duplicate name, cross-store 404')

    await cl.set_card_links(common, CardLinks(checklist=True, shift_ids=[]), session, o)
    await cl.set_shift_cards(open_id, IdList(ids=[opening, closing, draft]), session, o)
    await cl.set_shift_cards(close_id, IdList(ids=[closing]), session, o)
    await cl.set_shift_cards(open_id, IdList(ids=[opening, draft]), session, o)
    listed = {i['shift_id']: i for i in (await cl.list_shifts(session, o))['items']}
    assert listed[open_id]['card_ids'] == sorted([opening, draft]), listed[open_id]   # 초안도 포함
    assert listed[middle_id]['card_ids'] == [], listed[middle_id]
    print('PASS checklist shift list carries card_ids incl. drafts')
    links = await cl.get_card_links(closing, session, o)
    assert links == {'card_id': closing, 'checklist': True, 'shift_ids': [close_id]}, links
    await cl.set_shift_cards(close_id, IdList(ids=[]), session, o)
    assert (await cl.get_card_links(closing, session, o))['checklist'] is False
    print('PASS checklist removing last shift does not make card common')
    await cl.set_shift_cards(close_id, IdList(ids=[closing]), session, o)

    await cl.set_member_shifts(staff_mid, IdList(ids=[middle_id, close_id]), session, o)
    with patch.object(cl, '_now', return_value=NOON):
        member = await cl.require_member(session, s)
        view = await cl.today_view(session, member, now_utc=NOON, selected_shift_id=None, requested_date=None, include_all=True)
    names = [g['name'] for g in view['groups']]
    assert names == ['공통', '마감'], names     # 미들엔 카드 없음, 오픈은 담당 아님, 초안 숨김
    assert view['current_shift_id'] == middle_id and view['scope_counts'] == {'total': 2, 'done': 0}, view
    print('PASS checklist staff scope = common + assigned, drafts hidden')

    with patch.object(cl, '_now', return_value=NOON):
        version = view['groups'][0]['cards'][0]['card_version_id']
        await cl.put_check(CheckRequest(business_date=TODAY, card_version_id=version, line_no=1, checked=True), session, s)
        await cl.put_check(CheckRequest(business_date=TODAY, card_version_id=version, line_no=1, checked=True), session, s)
        opening_version = await db.fetchval('select published_version_id from knowledge_cards where store_id=$1 and card_id=$2', sid, opening)
        await _expect('CHECK_OUT_OF_SCOPE', cl.put_check(CheckRequest(business_date=TODAY, card_version_id=opening_version, line_no=1, checked=True), session, s))
        conflict = await _expect('BUSINESS_DATE_CHANGED', cl.put_check(CheckRequest(business_date=TODAY - timedelta(days=1), card_version_id=version, line_no=1, checked=True), session, s))
        assert conflict.details['previous_unsubmitted'] is True
    assert await db.fetchval('select count(*) from checklist_check_events where store_id=$1 and user_id=$2', sid, staff) == 1
    print('PASS checklist idempotent check, scope 409, stale date 409')

    # 내 기록 끈 사람: 매장 체크는 바뀌고 사람 흔적은 없다 (C7-1)
    await cl.update_me(MySettings(personal_records_enabled=False), session, q)
    with patch.object(cl, '_now', return_value=NOON):
        closing_version = await db.fetchval('select published_version_id from knowledge_cards where store_id=$1 and card_id=$2', sid, closing)
        await cl.put_check(CheckRequest(business_date=TODAY, card_version_id=closing_version, line_no=1, checked=True), session, q)
        sub = (await cl.submit(SubmissionRequest(business_date=TODAY), session, q))['submission']
    # 행이 실제로 써졌는지 먼저 확인해야 updated_by 가 비어 있다는 검사가 공허하지 않다
    assert await db.fetchval('select checked from checklist_checks where store_id=$1 and business_date=$2 and card_version_id=$3 and line_no=1', sid, TODAY, closing_version) is True
    assert await db.fetchval('select updated_by from checklist_checks where store_id=$1 and card_version_id=$2', sid, closing_version) is None
    assert await db.fetchval('select count(*) from checklist_check_events where store_id=$1 and user_id=$2', sid, quiet) == 0
    assert await db.fetchval('select personal from checklist_submissions where store_id=$1 and user_id=$2', sid, quiet) is False
    assert sub['total_lines'] == 4 and sub['scope_shift_ids'] is None, sub   # 담당 없음 → 전체
    assert sub['done_lines'] == 2, sub   # 알바가 체크한 공통 1줄 + 기록끈 알바가 체크한 마감 1줄
    print('PASS checklist personal records off leaves no trace but keeps store state')

    # 한 카드가 범위 안 근무조 둘에 걸려도 줄은 한 번만 센다 (오픈 카드 2줄을 미들·마감에 동시 연결)
    await cl.set_card_links(opening, CardLinks(checklist=True, shift_ids=[middle_id, close_id]), session, o)
    with patch.object(cl, '_now', return_value=NOON):
        member = await cl.require_member(session, s)
        linked = await cl.today_view(session, member, now_utc=NOON, selected_shift_id=None, requested_date=None, include_all=True)
    assert linked['scope_counts']['total'] == 4, linked['scope_counts']   # 2 + 오픈 카드 2줄(중복 4줄 아님)
    await cl.set_card_links(opening, CardLinks(checklist=True, shift_ids=[open_id]), session, o)

    with patch.object(cl, '_now', return_value=NOON):
        first = (await cl.submit(SubmissionRequest(business_date=TODAY), session, s))['submission']
        again = (await cl.submit(SubmissionRequest(business_date=TODAY), session, s))['submission']
    assert first == again and first['total_lines'] == 2 and first['done_lines'] == 2, first
    print('PASS checklist submission fixed and idempotent')

    # 범위를 다 체크하면 서버가 제출을 자동 기록한다 (C4). 미들만 맡은 새 직원 — 범위는 공통 카드뿐
    auto = await db.fetchval("insert into users(name,role) values('합성 자동제출 알바','STAFF') returning user_id")
    auto_mid = await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'STAFF') returning member_id", sid, auto)
    await cl.set_member_shifts(auto_mid, IdList(ids=[middle_id]), session, o)
    a = dict(store_id=sid, user_id=auto, role='STAFF')
    common_version = await db.fetchval('select published_version_id from knowledge_cards where store_id=$1 and card_id=$2', sid, common)
    with patch.object(cl, '_now', return_value=NOON):
        assert await db.fetchval('select count(*) from checklist_submissions where store_id=$1 and user_id=$2', sid, auto) == 0
        res = await cl.put_check(CheckRequest(business_date=TODAY, card_version_id=common_version, line_no=1, checked=True), session, a)
    assert res['submitted'] is True, res
    auto_sub = await db.fetchrow('select total_lines, done_lines, scope_shift_ids, late from checklist_submissions where store_id=$1 and user_id=$2 and business_date=$3', sid, auto, TODAY)
    assert auto_sub['total_lines'] == auto_sub['done_lines'] == 1 and list(auto_sub['scope_shift_ids']) == [middle_id] and auto_sub['late'] is False, dict(auto_sub)
    print('PASS checklist auto submission when scope fully checked')

    # 어제 창: 다음 날 오후, 어제 미제출인 점주는 late 저장 가능, 이미 제출한 알바는 409
    tomorrow = NOON + timedelta(days=1)
    with patch.object(cl, '_now', return_value=tomorrow):
        late = (await cl.submit(SubmissionRequest(business_date=TODAY, checks=[
            {'card_version_id': opening_version, 'line_no': 2, 'checked': True}]), session, o))['submission']
        await _expect('BUSINESS_DATE_CHANGED', cl.submit(SubmissionRequest(business_date=TODAY), session, s))
        await _expect('BUSINESS_DATE_CHANGED', cl.submit(SubmissionRequest(business_date=TODAY - timedelta(days=1)), session, o))
    assert late['late'] is True and late['scope_shift_ids'] is None
    print('PASS checklist late save only for previous unsubmitted day')

    # 새 공개 버전이면 그날 체크는 새로 시작
    # 레거시 트리거가 없으므로 새 판(2)을 명시적으로 만들고 초안·공개 포인터를 옮긴다
    new_common = await db.fetchval("""insert into card_versions(store_id,card_id,version_no,title,content,change_source)
        values($1,$2,2,'합성 공통',$3,'OWNER_EDIT') returning version_id""", sid, common, '물 채우기\n컵 채우기')
    await db.execute("""update knowledge_cards set content=$3, draft_version_id=$4, published_version_id=$4
        where store_id=$1 and card_id=$2""", sid, common, '물 채우기\n컵 채우기', new_common)
    with patch.object(cl, '_now', return_value=NOON):
        member = await cl.require_member(session, s)
        fresh = await cl.today_view(session, member, now_utc=NOON, selected_shift_id=None, requested_date=None, include_all=True)
    assert not any(line['checked'] for line in fresh['groups'][0]['cards'][0]['lines'])
    print('PASS checklist new published version restarts checks')

    # 근무조 보관 → 그 근무조에만 있던 카드는 어디에도 안 나온다
    await cl.delete_shift(close_id, session, o)
    assert (await cl.get_card_links(closing, session, o))['checklist'] is False   # 공통으로 둔갑하지 않는다 (C9)
    assert await db.fetchval('select count(*) from member_shifts where store_id=$1 and shift_id=$2', sid, close_id) == 0
    with patch.object(cl, '_now', return_value=NOON):
        member = await cl.require_member(session, o)
        owner_view = await cl.today_view(session, member, now_utc=NOON, selected_shift_id=None, requested_date=None, include_all=True)
    titles = [c['title'] for g in owner_view['groups'] for c in g['cards']]
    assert '합성 마감' not in titles, titles
    print('PASS checklist archived shift hides its cards')

    # 개인 기록: 알바 본인 보임, 점주가 알바생 기록 끄면 점주에겐 안 보이고 켜면 다시 보임 (C7-2)
    month = TODAY.strftime('%Y-%m')
    own = await cl.get_records(session, s, month=month, user_id=None)
    assert own['visible'] and own['days'][0]['percent'] == 100, own
    await _expect('RECORDS_FORBIDDEN', cl.get_records(session, s, month=month, user_id=owner))
    await cl.update_settings(Settings(staff_records_visible=False), session, o)
    hidden = await cl.get_records(session, o, month=month, user_id=staff)
    assert hidden['visible'] is False and hidden['days'] == []
    await cl.update_settings(Settings(staff_records_visible=True), session, o)
    shown = await cl.get_records(session, o, month=month, user_id=staff)
    assert shown['days'], shown
    day = await cl.get_record_day(TODAY, session, o, user_id=staff)
    assert [l['text'] for l in day['lines']] == ['물 채우기'], day
    quiet_records = await cl.get_records(session, q, month=month, user_id=None)
    assert quiet_records['days'] == [] and quiet_records['recording'] is False
    await _expect('MEMBER_NOT_FOUND', cl.get_records(session, o, month=month, user_id=other_owner))
    print('PASS checklist personal records visibility and owner toggle')

    with patch.object(cl, '_now', return_value=NOON):
        status = await cl.get_status(session, o)
    assert status['last_submission'] is not None and status['business_date'] == TODAY.isoformat(), status
    assert 'user_id' not in status['last_submission'], status['last_submission']
    print('PASS checklist owner status')
