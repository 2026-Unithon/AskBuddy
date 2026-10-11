-- Phase A — 카드 행 쓰기가 블록 없는 판을 몰래 만들던 레거시 트리거를 없앤다(설계 A-D2, F2).
-- 이제 카드 판은 코드가 명시적으로 만든다(ingest/repository.insert_card, fact_cards, fact_edit).
-- 함수는 다른 트리거가 쓰지 않으면 함께 지운다.
drop trigger if exists trg_knowledge_cards_version_legacy_write on knowledge_cards;
drop function if exists askbuddy_version_legacy_card_write();
