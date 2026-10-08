# 리브랜딩 P7 검증 — 2026-10-08

브랜치 `ui/rebrand-mobile`. P0~P5의 후속 작업인 로컬 DB 적용·실제 HTTP/DB 종단 확인·모바일 화면 검증을 진행했다. 기존 U7에 따라 P6 카카오·합류와 별도 W 작업 F4는 포함하지 않는다.

## DB 적용과 격리

- 공유 **로컬** Supabase(`supabase_db_AskBuddy`, 54322)에 `20261006090000_checklist.sql`만 적용했다. migration 이력과 `store_shifts`, `member_shifts`, `checklist_cards`, `checklist_card_shifts`, `checklist_checks`, `checklist_check_events`, `checklist_submissions` 7개 테이블을 확인했다. 후속 W migration은 공유 DB에 적용하지 않았다.
- 전용 PostgreSQL 17.11(pgvector, 55439)에서 `verify_r_schema_rebuild.py`로 44개 migration을 재구축하고 W/R·체크리스트 DB 시나리오를 확인했다. 종료 코드 0. 격리·직원 범위·지연 제출·새 공개 버전·근무조 보관·개인 기록 설정을 포함한다.
- 브라우저 종단 검증은 별도 UUID DB와 합성 점주·직원·매장·카드·질문·알림을 사용했다. 실제 FastAPI와 production Next 서버를 연결했으며 HTTP 응답을 mock하지 않았다. 공유 DB의 실제 사용자 자료는 사용하지 않았다.

## 검증 결과

P7 실제 API 브라우저 **58개 항목 통과**, 런타임 예외 **0개**, 스크린샷 **37장**. 실제 DB 체크 이벤트·지연 제출·알림 읽음 저장도 통과했다. [실행 결과](p7_20261008/result.json).

- `pnpm --dir web check`: route typegen·lint·typecheck·production build 통과.
- 기존 합성 API 브라우저 회귀: P5 **33개**, 리브랜딩 **48개** 통과. 실패 되돌림·재시도·로딩·빈 상태·중복 클릭·초안 보존·새로고침·포커스 복귀를 확인했다.
- 실제 API/DB: 근무조 생성·자정 넘는 시간 편집·카드 연결·직원 담당·공통/담당 범위·체크·점주 현황·제출·새로고침 복원·기록 달력·개인 기록 설정·직원 기록 조회 숨김/복원을 확인했다.
- 실제 분 단위 영업일 전환을 기다린 뒤 어제 창에서 저장하고 `late` 제출과 체크 이벤트가 DB에 남는지 확인했다.
- 앱 내부 알림을 누르면 점주 질문 ID·직원 대화 세션 ID가 유지되고 DB에 읽음이 저장되는지 확인했다.
- 옛 직원 학습 상세/로드맵, 점주 업로드/검수 주소의 이동과 작업 ID 보존을 확인했다. 기존 v1 대화·질문 기록은 v2로 변환하지 않았다.
- 390×844·360×800 가로 넘침을 확인하고 [스크린샷 목록](p7_20261008/README.md)을 정리했다.
- 체크리스트 매장 격리 검사: 6개 파일, 위반 없음.

## 발견한 문제와 수정

할 일이 길어지면 스크롤 영역의 flex 배치가 진행 카드를 줄여 360×800에서 내용이 잘렸다. 공통 `HeroCard`에 `shrink-0`을 추가해 카드 높이를 유지했다. 점주·직원 화면의 두 뷰포트에서 진행 카드 자식이 카드 영역 안에 있는지 브라우저 검사로 확인했고, 기존 화면 회귀도 다시 통과했다.

검증 스크립트의 UI 기대값도 실제 계약에 맞췄다. 직원 알림은 제목이 아닌 ‘답변 확인’ 버튼으로 열며, 옛 검수 주소는 `/owner/cards?status=all&job_id=…`로 이동한다. 제품 경로를 검증 스크립트에 맞춰 변경하지 않았다.

## 재현과 한계

`api/scripts/verify_p7_integration.py`는 전용 localhost:55439의 `usage_verify`에서 UUID DB를 만들고, 모든 migration·합성 fixture를 넣어 API 8000·web 3011을 띄운다. 포트가 사용 중이면 시작하지 않는다. 실행 종료 시 두 서버와 UUID DB를 지운다. 사전 준비는 `pnpm --dir web check`, pgvector PostgreSQL 17, API Python 의존성, Playwright Chromium이다.

```sh
docker run --detach --name askbuddy-p7-verify --publish 127.0.0.1:55439:5432 --env POSTGRES_PASSWORD=synthetic-local-test --env POSTGRES_DB=usage_verify pgvector/pgvector:pg17
cd api
# Playwright가 별도 경로에 있으면 NODE_PATH를 지정한다.
python scripts/verify_p7_integration.py
docker rm -f askbuddy-p7-verify
```

`R_V2_ENABLED=true`는 일회용 검증 서버에만 적용했다. 외부 모델 추출·답변, 카카오 인증, 외부 기기의 Web Push 수신, 운영 DB migration·배포는 이번 검증 결과에 포함하지 않는다. 앱 내부 알림과 저장된 딥링크를 검증한 것이며 실제 Push 전송 확인은 별도다. 디자이너의 시각적 승인은 스크린샷을 제공한 다음 단계다.
