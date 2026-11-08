-- 프로필 사진(2026-11-08 사용자: 연필 하나로 사진·이름·매장 이름). 비공개 avatars 버킷의 경로만 둔다.
-- 버킷은 api/scripts/init_storage.py 가 만든다. 브라우저는 서명 URL 로만 올리고 읽는다.
alter table users add column if not exists avatar_path text;
