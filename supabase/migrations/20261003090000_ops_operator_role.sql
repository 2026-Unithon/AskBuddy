-- 운영자 역할 추가 (이슈 #33).
-- 운영자는 어느 매장에도 소속되지 않으므로 store_members.member_role 은 OWNER/STAFF 그대로 둔다.
-- 가입 API(/auth/signup)는 계속 OWNER 만 만든다. 운영자는 api/scripts/create_operator.py 로만 만든다.
alter table users drop constraint if exists users_role_check;
alter table users add constraint users_role_check
  check (role in ('OWNER', 'STAFF', 'OPERATOR'));
