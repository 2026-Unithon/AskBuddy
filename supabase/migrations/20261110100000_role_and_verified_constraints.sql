-- 계획 9B(2026-11-10): 코드가 매 요청 확인하던 규칙을 DB 가 지키게 한다
-- 어긋난 행이 있으면 여기서 멈춘다. 고칠 값을 사람이 정해야 하므로 자동으로 맞추지 않는다
do $$
begin
  if exists (select 1 from store_members m join users u using (user_id) where u.role is distinct from m.member_role) then
    raise exception '역할이 어긋난 멤버가 있다. store_members.member_role 과 users.role 을 먼저 맞춘다';
  end if;
  if exists (select 1 from knowledge_cards where is_verified is distinct from (review_status = 'APPROVED')) then
    raise exception 'is_verified 와 review_status 가 어긋난 카드가 있다';
  end if;
end $$;

alter table users add constraint users_user_id_role_key unique (user_id, role);
alter table store_members add constraint store_members_role_matches_user
  foreign key (user_id, member_role) references users (user_id, role);
alter table knowledge_cards add constraint knowledge_cards_verified_matches_status
  check (is_verified = (review_status = 'APPROVED'));
