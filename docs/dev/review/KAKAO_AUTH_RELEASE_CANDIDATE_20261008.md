# 카카오 로그인 배포 후보 검증 — 2026-10-08

## 운영 확인 결과

- `https://api.askbuddy.kr/health`: 200.
- `/auth/providers`, `/auth/kakao/start`: 각각 404. 운영 웹 시작 화면에도 카카오 버튼이 없다.
- 최신 `origin/main`은 `215631be3d9bfa78d3d4ac74b39fccccf6065e36`. EC2 API도 앞선 환경변수 작업에서 같은 SHA를 확인했다.
- 환경변수 반영과 서비스 재생성은 앞선 작업에서 끝났지만 카카오 코드·migration·웹은 아직 배포하지 않았다.
- **실제 운영 카카오 로그인 성공은 미확인이다.** 아래 검사는 로컬 배포 후보에 대한 결과다.

## 검토 가능한 배포 후보

현재 `w/kakao-auth`는 main보다 24개 커밋 뒤이고 별도 R 작업의 미커밋 변경이 함께 있다. 현재 체크아웃·브랜치·실제 Git 인덱스를 바꾸지 않고 최신 main의 소스 사본에 카카오 파일만 합쳤다. Git worktree는 만들지 않았다.

- 소스 사본: `output/kakao-release-20261008/` (로컬 `.git/info/exclude`로 제외).
- 재현 가능한 패치: `output/kakao-release-20261008.patch`.
- 기준 SHA·파일 목록·패치 해시: `output/kakao-release-manifest.json`.
- 별도 R 변경과 `20261008120000_r_failed_user_turns.sql`은 포함하지 않는다.
- 새 migration은 `20261008130000_kakao_auth_join_sessions.sql` 하나다.
- `.env` 실값·인증정보·node_modules·검증 산출물은 패치에 포함하지 않는다.

최신 main과 결합하면서 다음을 보완했다.

1. 최신 체크리스트 라우터·설정·공용 fetch export·query key를 유지한다.
2. 설정의 로그아웃이 `/auth/logout` 성공 후 이동하도록 연결한다. 실패하면 화면에 남아 재시도한다.
3. `/owner/invite`의 옛 초대 코드 API를 초대 링크·합류 승인으로 교체하고 `/owner/complete`의 최신 redirect는 유지한다.
4. `/owner/members`에 초대·승인·내보내기를 연결한다. 기존 근무조 배정은 `/owner/member-shifts`로 보존하고 직원 관리에서 연결한다.
5. 승인·내보내기 뒤 체크리스트 캐시도 갱신한다. 퇴사자는 현재 직원 목록·근무조 변경에서 제외하고 과거 기록은 보존한다.
6. 기존 회원의 로그인 후 목적지는 최신 홈(`/owner`, `/staff`)으로 통일한다. 신규 점주는 매장 생성, 미가입 직원은 승인 대기로 이동한다.
7. CI 브라우저 fixture를 localStorage에서 `/auth/refresh` 세션 응답으로 이전한다. DB 재구축 CI에도 카카오 통합 검사를 연결한다.
8. 배포 workflow에 migration 적용 전 `--include-all --dry-run` 단계를 추가한다. 기존 DB 백업 단계는 유지한다.

## 검증 결과

- API 전체: **2,027 passed, 6 skipped, 4 xfailed, 131 subtests passed**. 6개 skip은 명시적 로컬 DB URL이 필요한 카카오 검사다.
- 카카오 실제 DB 검사: 새 전체 스키마에서 **6 passed**. 역할 선택·refresh·logout, 중복 합류·승인·초대 회전·퇴사자 격리, 모의 카카오 콜백, CSRF·레거시 경로 차단, refresh 재사용 폐기, 개인 Push 구독 격리를 확인했다. 카카오 공급자 응답은 합성 fixture다.
- 일회용 PostgreSQL 17.11: **전체 migration 45개 재구축** 및 기존 R/W/체크리스트 API·DB 통합 검사 통과. 운영 DB는 연결하지 않았고 검증 컨테이너는 종료했다.
- `store-isolation-check`: auth/members/bootstrap/notifications/checklist **24개 파일 위반 0건**.
- 계약 schema 15개·fixture 3개 최신.
- `pnpm check`: lint·타입 검사·프로덕션 빌드 통과. 웹 단위 테스트 러너는 없다.
- 실제 브라우저 + 합성 API: 질문 UI **44개**, 이력·복원 **36개**, 최신 화면 **48개**, 합계 **128개 검사 통과**. 로그아웃 후 새로고침, 이메일 오류·성공, 가입 후 역할 선택, 초대 링크 버튼, 기존 카드/레시피 동작, 모바일 폭 390/360을 포함한다.
- Windows 시간대 데이터 누락은 검증용 Python 환경에 `tzdata` 설치 후 해결했다. 제품 코드나 requirements는 바꾸지 않았다. Starlette deprecation warning 1개는 남아 있다.

## 실제 배포 전 남은 단계

계획의 Global Constraints에는 "커밋·푸시는 사용자가 한다"고 명시되어 있다. 현재 요청은 운영 확인이며 이 역할 변경은 아직 명시되지 않았다. 커밋·푸시·main 반영은 하지 않았다.

이 배포 후보를 main에 반영하고 DB → API → Web 순서로 배포해야 운영 검증을 이어갈 수 있다. 기존 초대 코드는 migration에서 무효화되며 점주가 새 링크를 만들어야 한다. 기존 localStorage 로그인은 새 세션 방식으로 바뀌어 다시 로그인해야 한다.

배포 시에는 백업 성공·예상 migration 확인·적용 후 스키마 읽기 검증·EC2 SHA와 health·Vercel 배포 상태를 확인한다. 카카오 개발자 콘솔의 운영 Redirect URI `https://api.askbuddy.kr/auth/kakao/callback` 등록은 아직 직접 확인하지 않았다. 배포 후 실제 계정의 로그인·동의는 사용자가 브라우저에서 수행하고, 콜백·역할 이동·새로고침 세션 유지·로그아웃을 확인해야 한다.

운영의 직원 초대→두 번째 계정 요청→점주 승인, 실제 기기 Push·모바일 브라우저 동작은 아직 미검증이다. 카카오 공유용 JavaScript 키는 로그인에 필수는 아니며 공유 기능 검증은 별도다.
