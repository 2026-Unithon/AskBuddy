-- 계획 9A(2026-11-10): 게이지 80% 게이트를 버린 뒤 아무도 읽지 않는 칸
alter table store_members drop column if exists day_count;
alter table store_members drop column if exists progress_rate;
alter table store_members drop column if exists is_deployable;
alter table stores drop column if exists knowledge_coverage;
alter table stores drop column if exists deploy_threshold;
