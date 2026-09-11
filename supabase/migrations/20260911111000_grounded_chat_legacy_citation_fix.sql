begin;

-- 8단계 이전 citation에는 답변 당시 버전 정보가 없었다. 현재 버전을 과거 버전으로
-- 추정하면 감사 이력이 부정확해지므로 LEGACY 답변은 명시적으로 unknown(null)로 둔다.
update message_citations mc
set version_id = null
from chat_messages m
where m.message_id = mc.message_id
  and m.grounding_status = 'LEGACY'
  and mc.version_id is not null;

comment on column message_citations.version_id is
  '8단계 이후 답변 생성 당시 실제 사용한 공개 카드 버전. LEGACY 답변은 알 수 없어 null이다.';

commit;
