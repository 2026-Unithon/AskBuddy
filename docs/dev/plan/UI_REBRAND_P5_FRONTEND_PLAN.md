# P5 프론트 구현·검증

2026-10-08 · 상태: **구현·정적 검사·합성 API 브라우저 검증 완료. 실제 API·DB 종단 검증은 P7 검증 기록 참고.** 브랜치 `ui/rebrand-mobile`.

기준: [P5 확정 설계](UI_REBRAND_P5_CHECKLIST.md), [MVP 정본](../ASKBUDDY_MVP_CURRENT.md), `web/AGENTS.md`. U8에 따라 프론트는 직접 구현한다. 사용자 확인: 신규 달력·설정·직원 담당 화면도 기존 초록색 모바일 UI와 공통 컴포넌트를 사용한다.

## 구현 범위

- [x] `web/lib/checklist-api.ts`: 실제 `/checklist/*` 요청·응답 타입. 카드 담기와 직원 담당 요청 본문은 백엔드 `IdList`에 맞춰 `{ids}`로 보낸다
- [x] `web/lib/query.ts`: 매장·사용자·근무조·날짜별 query key와 Query 옵션. 직원 15초·점주 30초, 숨겨진 탭에서는 폴링하지 않는다
- [x] `/staff`: 오늘 할 일·근무조 선택·공통 묶음·실제 개수 진행 막대·질문창·남은 항목 제출 확인·완료 표시
- [x] 체크 줄 낙관적 변경·실패 시 해당 줄만 되돌림·저장 중 같은 줄 연타 방지. 다른 줄의 변경은 유지한다
- [x] 날짜 변경: 조회 응답이나 `BUSINESS_DATE_CHANGED`로 어제 창을 연다. 실패한 체크를 입력 초안에 반영하고 전체 줄을 중복 없이 제출한다. 어제 창은 닫기 없이 저장만 있으며 저장 실패 시 초안을 유지한다
- [x] `/owner`: 제출자 이름을 표시하지 않는 매장 진행·근무조별 완료·마지막 제출
- [x] `/owner/me`, `/staff/me`: 월 달력·날짜 상세·본인 기록 설정. 점주만 직원 기록 선택 가능. 제출 전 기록은 % 대신 체크 개수다
- [x] `/owner/shifts`: 근무조 추가·이름/시간 편집·보관·순서·프리셋·승인 카드 담기·영업일 시각·알바생 기록 조회 설정
- [x] `/owner/members`: 직원 담당 근무조 다중 선택. 비우면 전체
- [x] 점주 승인 카드 상세: 체크리스트 포함 여부·공통 또는 근무조 다중 선택. 마지막 근무조를 빼면 체크리스트에서 빠진다
- [x] 공통 `Sheet`: 선택적 닫기 제한, 키보드 포커스 유지·복원, 긴 콘텐츠 높이 제한
- [x] 서버 상태는 Query 캐시에서 읽는다. 로컬 상태에는 화면 선택 식별자와 사용자가 바꾼 입력 초안만 둔다. 설정·카드 연결·체크 변경 후 관련 Query를 invalidate한다

## 백엔드 보완

기존 API에는 현재 설정 조회가 없어 기본값을 표시하면 저장된 설정과 달라질 수 있었다. 기존 구성원 확인·매장 격리 경계를 사용해 읽기 경로만 추가했다.

- `GET /checklist/settings`: 점주만 현재 영업일 시작 시각·알바생 기록 조회 설정·매장 시간대 조회
- `GET /checklist/me`: 현재 구성원의 개인 기록 설정 조회
- `api/tests/test_checklist_settings_routes.py`: 저장된 값 반환, 직원의 점주 설정 접근 거절, 인증된 본인 설정 조회

## 검증 결과

- `cd web && pnpm check`: route typegen·lint·typecheck·프로덕션 build 통과
- `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/checklist`: 6개 파일, 위반 없음
- `python -m unittest discover -s tests -p 'test_checklist*.py'` (`api/`, 기존 백엔드 가상환경 사용): **51개 통과**
- `api/scripts/verify_ui_checklist.cjs`: 합성 API 브라우저 **33개 항목 통과**. 체크 실패 되돌림·재시도, 제출 실패/완료/새로고침 복원, 어제 창/닫기 제한/키보드 포커스/저장 실패 초안 보존, 날짜 변경·포커스 복귀, 조회 오류·재시도·빈 상태, 근무조 추가 실패 보존·순서·카드 담기, 직원 담당·카드 공통 연결, 개인 기록·기록 설정, 근무조 0개·연타·자동 제출을 확인했다
- `api/scripts/verify_ui_rebrand.cjs`: 기존 화면 회귀 **48개 항목 통과**. `/staff`의 과거 레시피 리다이렉트 기대값을 오늘 할 일 진입으로 갱신했다
- 두 브라우저 검사 모두 런타임 예외 없음. 390px·360px 가로 넘침 검사 통과. 달력·완료 화면 스크린샷을 확인하고 월 이동 버튼 폭을 수정했다
- `web-async-state-check` 금지 패턴 검사: 신규 체크리스트 코드에 직접 폴링·effect fetch·응답 localStorage 복사·오류 숨김·lint 억제 없음

위 최초 브라우저 검증은 실제 브라우저와 **합성 API**를 사용했다. 후속 P7에서는 공유 로컬 DB에 P5 migration을 적용하고, 별도 일회용 PostgreSQL에서 합성 매장 자료로 실제 FastAPI·DB 종단 검증을 실행했다. [P7 결과](../review/UI_REBRAND_P7_VALIDATION_20261008.md) 참고.

재현: `cd web && pnpm start --port 3011` 실행 후 Playwright가 설치된 환경에서 두 브라우저 스크립트를 실행한다. `NODE_PATH`는 필요한 경우 해당 환경의 설치 경로를 지정한다. P5 스크린샷은 기본 `/tmp/askbuddy-p5-ui/`에 저장하며 `P5_UI_ARTIFACT_DIR`로 바꿀 수 있다.
