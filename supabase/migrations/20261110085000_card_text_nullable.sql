-- 계획 9A 1단계(2026-11-11): 새 코드는 카드 제목·본문을 판(card_versions)에만 쓴다.
-- 칸을 지우는 20261110093000 보다 먼저 배포되므로, 그 사이 새 코드의 카드 insert 가 NOT NULL 에 걸리지 않게 푼다.
-- 옛 코드는 계속 값을 넣으므로 이 변경으로 깨지지 않는다. 칸 삭제는 다음 배포(20261110093000)가 한다
alter table knowledge_cards alter column title drop not null;
alter table knowledge_cards alter column content drop not null;
