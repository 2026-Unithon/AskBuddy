-- 003 적용 전 백필 검증용 fixture.
-- 반드시 별도 테스트 DB에서 001 -> 002 다음, 003 전에만 실행한다.

with legacy_source as (
  insert into sources (
    store_id, uploaded_by, source_type, title, file_url,
    content_hash, status, processed_at
  )
  select
    s.store_id, s.owner_id, 'VOICE', '003 이전 자료',
    'sources/legacy/voice.m4a', repeat('c', 64), 'DONE', now()
  from stores s
  where s.store_slug = 'demo-cafe'
  returning source_id, store_id
)
insert into knowledge_cards (
  store_id, category_id, source_id, title, content, confidence, is_verified
)
select
  ls.store_id,
  c.category_id,
  ls.source_id,
  '003 이전 미승인 카드',
  '마이그레이션이 작업과 초안 버전으로 보존해야 하는 카드입니다.',
  55,
  false
from legacy_source ls
join task_categories c
  on c.store_id = ls.store_id and c.category_name = '재고정리';
