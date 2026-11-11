-- 계획 9A(2026-11-10): 카드의 제목과 본문은 판(card_versions)에만 둔다
-- 판이 하나도 없는 옛 카드가 있으면 글을 잃지 않게 판 1 로 옮긴 뒤 지운다
insert into card_versions (store_id, card_id, version_no, title, content, change_source)
select c.store_id, c.card_id, 1, c.title, c.content, 'EXTRACTION'
from knowledge_cards c
where not exists (select 1 from card_versions v where v.store_id = c.store_id and v.card_id = c.card_id);

update knowledge_cards c set draft_version_id = v.version_id
from card_versions v
where c.draft_version_id is null and c.published_version_id is null
  and v.store_id = c.store_id and v.card_id = c.card_id and v.version_no = 1;

alter table knowledge_cards drop column if exists title;
alter table knowledge_cards drop column if exists content;
