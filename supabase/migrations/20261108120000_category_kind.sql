-- 계획 7 Task 2: 카테고리 종류(레시피/할 일/정보). 가산 변경만.
-- kind 는 분류 AI 판단(입구 분류 source_logic)으로 처음 채우고, 사장님이 바꾸면 kind_source='OWNER' 로 덮지 않는다.
-- 비어 있으면 화면·근무조 기본값은 이름 규칙(레시피·음료·메뉴·제조·제작)으로 본다.
alter table task_categories add column if not exists kind varchar(10);
alter table task_categories add column if not exists kind_source varchar(10);
alter table task_categories drop constraint if exists task_categories_kind_check;
alter table task_categories add constraint task_categories_kind_check
  check (kind is null or kind in ('RECIPE', 'TASK', 'INFO'));
alter table task_categories drop constraint if exists task_categories_kind_source_check;
alter table task_categories add constraint task_categories_kind_source_check
  check (kind_source is null or kind_source in ('AI', 'OWNER'));
