-- =====================================================================
-- AskBuddy — 데모 시드
-- store_slug = 'demo-cafe'  (기존 FastAPI 문자열 store_id 와 호환)
-- 세 파트가 이 데이터를 기준으로 개발한다. 임의로 바꾸지 말 것.
-- 재실행: supabase db reset (마이그레이션 + 시드 재적용)
-- =====================================================================

-- 1. 사용자 -----------------------------------------------------------
insert into users (name, phone, role) values
  ('데모 사장님', '010-0000-0001', 'OWNER'),
  ('박지호',      '010-0000-0002', 'STAFF'),
  ('김민준',      '010-0000-0003', 'STAFF'),
  ('이서연',      '010-0000-0004', 'STAFF');

-- 2. 매장 -------------------------------------------------------------
insert into stores (owner_id, store_slug, store_name, business_type, deploy_threshold)
select user_id, 'demo-cafe', '카페 아무개', 'CAFE', 80
from users where name = '데모 사장님';

-- 3. 구성원 -----------------------------------------------------------
insert into store_members (store_id, user_id, member_role, day_count, progress_rate, is_deployable)
select s.store_id, u.user_id, 'OWNER', 0, 0, false
from stores s, users u where s.store_slug='demo-cafe' and u.name='데모 사장님';

insert into store_members (store_id, user_id, member_role, day_count, progress_rate, is_deployable)
select s.store_id, u.user_id, 'STAFF', v.day_cnt, v.rate, v.deployable
from stores s
join (values ('박지호', 7, 90.00, true),
             ('김민준', 3, 65.00, false),
             ('이서연', 1, 28.00, false)) as v(nm, day_cnt, rate, deployable) on true
join users u on u.name = v.nm
where s.store_slug = 'demo-cafe';

-- 4. 초대코드 ---------------------------------------------------------
insert into invite_codes (store_id, code, expires_at)
select store_id, 'CAFE-DEMO', now() + interval '365 days'
from stores where store_slug = 'demo-cafe';

-- 5. 업무 카테고리 ----------------------------------------------------
insert into task_categories (store_id, category_name, is_enabled, sort_order)
select s.store_id, v.nm, v.en, v.ord
from stores s
join (values ('오픈업무', true, 1),
             ('재고정리', true, 2),
             ('음료제작', true, 3),
             ('마감업무', true, 4),
             ('베이킹',  false, 5)) as v(nm, en, ord) on true
where s.store_slug = 'demo-cafe';

-- 6. 로드맵 5단계 -----------------------------------------------------
insert into roadmap_stages (store_id, stage_name, stage_order)
select s.store_id, v.nm, v.ord
from stores s
join (values ('가게 투어', 1),
             ('식자재 위치', 2),
             ('레시피 숙지', 3),
             ('오픈 업무', 4),
             ('마감 업무', 5)) as v(nm, ord) on true
where s.store_slug = 'demo-cafe';

-- 7. 체크리스트 항목 --------------------------------------------------
insert into roadmap_items (stage_id, item_name, item_order)
select g.stage_id, v.nm, v.ord
from roadmap_stages g
join stores s on s.store_id = g.store_id and s.store_slug = 'demo-cafe'
join (values
  ('가게 투어',   '매장 전체 둘러보기', 1),
  ('가게 투어',   '주요 장비 위치 파악', 2),
  ('가게 투어',   '비상구 및 소화기 위치', 3),
  ('식자재 위치', '냉장고 위치',        1),
  ('식자재 위치', '냉동고 위치',        2),
  ('식자재 위치', '식자재 보관 위치',   3),
  ('식자재 위치', '소모품 위치',        4),
  ('레시피 숙지', '아이스 아메리카노',  1),
  ('레시피 숙지', '카페라떼',           2),
  ('레시피 숙지', '시즌 메뉴 3종',      3),
  ('오픈 업무',   '커피머신 예열',      1),
  ('오픈 업무',   '냉장고 재고 확인',   2),
  ('오픈 업무',   'POS 시스템 켜기',    3),
  ('마감 업무',   '기기 세척',          1),
  ('마감 업무',   '재고 마감 체크',     2),
  ('마감 업무',   '정산 및 시건',       3)
) as v(stage_nm, nm, ord) on v.stage_nm = g.stage_name;

-- 8. 지식카드 3건 (하드코딩 — M1 프론트 개발용) ------------------------
insert into knowledge_cards (store_id, category_id, title, content, confidence, is_verified)
select s.store_id, c.category_id, v.title, v.content, v.conf, true
from stores s
join (values
  ('재고정리', '우유 보관 위치',
   '우유는 언더카운터 냉장고 2단 왼쪽 칸에 보관합니다. 오픈 전 유통기한을 반드시 확인하세요.', 87.00),
  ('재고정리', '시럽·소스류 위치',
   '시럽과 소스류는 에스프레소 머신 오른쪽 선반, 싱크대 위 첫 번째 칸에 있습니다.', 82.00),
  ('음료제작', '아이스 아메리카노 레시피',
   '아이스 아메리카노는 샷 2개가 기본입니다. 얼음은 컵의 8부까지 채웁니다.', 91.00)
) as v(cat, title, content, conf) on true
join task_categories c on c.store_id = s.store_id and c.category_name = v.cat
where s.store_slug = 'demo-cafe';

-- 9. 체크리스트 ↔ 카드 연결 -------------------------------------------
update roadmap_items i
set card_id = c.card_id
from knowledge_cards c
join stores s on s.store_id = c.store_id and s.store_slug = 'demo-cafe'
where i.item_name = '식자재 보관 위치' and c.title = '우유 보관 위치';

-- 10. 초기 진행도 (박지호: 2단계까지 완료) -----------------------------
insert into learning_progress (member_id, item_id, status, completed_at)
select m.member_id, i.item_id,
       case when g.stage_order = 1 then 'DONE'
            when g.stage_order = 2 then 'IN_PROGRESS'
            else 'LOCKED' end,
       case when g.stage_order = 1 then now() else null end
from store_members m
join users u on u.user_id = m.user_id and u.name = '박지호'
join stores s on s.store_id = m.store_id and s.store_slug = 'demo-cafe'
join roadmap_stages g on g.store_id = s.store_id
join roadmap_items i on i.stage_id = g.stage_id;

-- 11. 대기 질문 2건 (대시보드 개발용) ----------------------------------
insert into pending_questions (store_id, member_id, question_text, miss_reason, status)
select s.store_id, m.member_id, v.q, v.reason, 'WAITING'
from stores s
join store_members m on m.store_id = s.store_id
join users u on u.user_id = m.user_id
join (values ('이서연', '시럽 재고가 부족하면 어떻게 해야 해요?', 'no_match'),
             ('김민준', '음료 제조 시 얼음 양의 기준이 있나요?',   'no_anchor')
) as v(nm, q, reason) on v.nm = u.name
where s.store_slug = 'demo-cafe';

-- =====================================================================
-- 검증 쿼리
--   select count(*) from roadmap_items;      -- 16
--   select count(*) from knowledge_cards;    -- 3
--   select code from invite_codes;           -- CAFE-DEMO
--   select store_id from stores where store_slug='demo-cafe';
-- 주의: card_embeddings 는 시드에 없다. 워커가 임베딩을 채워야 검색이 동작한다.
-- =====================================================================
