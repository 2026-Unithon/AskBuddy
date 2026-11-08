-- 계획 7: 검수 기록 행동에 미공개(UNPUBLISH)·수정 되돌리기(REVERT_EDIT)·검수 고르기(REVIEW_PICK)를 더한다. 가산 변경만.
alter table card_review_events drop constraint if exists card_review_events_action_check;
alter table card_review_events add constraint card_review_events_action_check
  check (action in (
    'APPROVE', 'EDIT_DRAFT', 'PUBLISH_EDIT',
    'EXCLUDE', 'RESTORE', 'MOVE_CATEGORY',
    'UNPUBLISH', 'REVERT_EDIT', 'REVIEW_PICK'
  ));
