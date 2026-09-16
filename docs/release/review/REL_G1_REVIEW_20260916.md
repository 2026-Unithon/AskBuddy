# REL-G1 진입·서버 정본 구현 검토

2026-09-16 · branch `dev_mvp`

## 구현 결과

- `/app/bootstrap`의 기본 목적지를 실제 Web route인 `/owner/intent`, `/owner/upload`, `/owner/questions`, `/staff/auth`, `/staff/roadmap`으로 맞췄다.
- OWNER·STAFF layout 진입 시 bootstrap Query로 토큰·역할·매장 상태를 재검증한다.
- 비로그인 직접 링크는 원래 주소를 `next`로 보존하고 인증 화면으로 이동한다.
- 401·403·404 bootstrap 응답은 로컬 인증을 지우고 재로그인으로 보낸다. 네트워크·일시 장애는 로그아웃하지 않고 오류와 재시도 버튼을 보인다.
- 인증 확인 중 `null`을 반환하던 흰 화면을 명시적 확인 상태로 바꿨다.
- localStorage는 token·role·userId·storeId와 미완료 온보딩 선택값만 복원한다. 사용자명·매장명은 bootstrap Query 결과를 직접 읽는다.
- 서버 category 로딩·오류·정상 빈 결과를 mock category로 채우던 fallback을 제거했다.
- 사용되지 않던 `web/lib/mock.ts`를 삭제하고 데모 로그인 자동 입력은 `NEXT_PUBLIC_DEMO_MODE=true` 환경에만 남겼다.

## 검증

| 검증 | 결과 |
|---|---|
| API 전체 pytest | 451 passed, 84 subtests passed |
| Web lint + typecheck + production build | 통과, 23 routes 생성 |
| 비로그인 `/owner/upload` 직접 진입 | `/owner/auth?next=%2Fowner%2Fupload` 이동 확인 |
| 만료된 로컬 OWNER token | bootstrap 401 뒤 인증 화면 이동 확인 |
| 정상 OWNER 로그인 | bootstrap 200 뒤 원래 `/owner/upload` 복귀 확인 |
| API 중단 상태 | 흰 화면 대신 오류·`다시 시도` 표시 확인 |
| API 재시작 뒤 재시도 | 같은 URL에서 업로드 화면 복구 확인 |
| 역할이 다른 세션의 STAFF 직접 링크 | `/staff/auth?next=%2Fstaff%2Froadmap` 이동 확인 |
| 정상 STAFF 로그인 | bootstrap 이름·매장명과 roadmap 표시 확인 |
| 모바일 화면 | 390×844, 360×800에서 인증·오류·OWNER 업로드·STAFF roadmap 확인 |

## 남은 범위

- 전체 API 오류 분류와 모든 요청의 중앙 401 처리, timeout·취소·429·5xx 계약은 REL-G2다.
- navigation 배지의 중복 조회 제거와 query freshness 조정도 REL-G2다.
- OWNER 매장 생성 중간 실패를 재개하는 별도 복구 UI는 페이지별 온보딩 검토에서 다룬다.
