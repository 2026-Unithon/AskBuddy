# 카카오 로그인 로컬 구현·검증 (2026-10-08)

기준: `docs/dev/plan/KAKAO_AUTH_PLAN.md`, `KAKAO_AUTH_DESIGN.md`.
작업 브랜치: `w/kakao-auth`. 커밋·푸시·운영 적용 없음. 기존 R 작업 변경은 보존.

## 구현

- FastAPI 카카오 Authorization Code + PKCE, 서명된 state 쿠키, 안전한 웹 복귀 경로.
- 카카오 계정 연결과 중복 가입 방지. 카카오 토큰은 저장하지 않음.
- 가입 직후 역할 선택, 이메일 로그인 경로 통합.
- access token 60분(메모리), refresh 90일 슬라이딩(HttpOnly 쿠키, DB에는 해시만).
- 토큰 회전·재사용 감지·로그아웃·직원 내보내기 시 세션 폐기. 사용자 행 잠금으로 회전과 폐기 직렬화.
- 초대 링크, 합류 요청, 점주 승인·거절·내보내기, 제거된 멤버 접근 차단.
- 개인 Push 구독 API, 합류 요청/승인 알림 및 서비스 워커 갱신 이벤트.
- 웹 로그인/콜백/역할 선택/초대/승인 대기/직원 관리 화면과 오류·재시도 처리.
- 신규 migration: `20261008130000_kakao_auth_join_sessions.sql`.

## 로컬 환경

- 웹: http://localhost:3000
- API: http://localhost:8000 (OAuth code가 URL에 있으므로 access log 비활성)
- Docker: `askbuddy-kakao-local`, 볼륨 `askbuddy-kakao-local-data`, PostgreSQL 17 + pgvector.
- PostgreSQL만 실행. Supabase Storage 등 전체 Supabase 서비스는 실행하지 않음.
- DB는 `127.0.0.1:54322`에만 바인딩. 새 로컬 DB에 현재 저장소 migration 43개 적용.
- 사용자가 설정한 `api/.env`의 실제 카카오 키를 사용. 시크릿 값은 문서에 기록하지 않음.

재시작:

```powershell
docker start askbuddy-kakao-local
# 터미널 1: api 폴더
.venv/Scripts/python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
# 터미널 2: web 폴더 (pnpm check로 빌드한 상태)
pnpm start --hostname 127.0.0.1
```

## 검증

- API 전체 최종 결과: **1971 passed, 4 xfailed, 131 subtests passed** (기존 Starlette deprecation warning 1건). `PYTHONUTF8=1`, `KAKAO_TEST_DB_URL`을 로컬 DB로 설정하고 `python -m pytest tests/ -q`.
- 실제 DB 통합 테스트: 가입/역할/갱신/로그아웃, 합류 중복 요청/승인/내보내기/타 매장 접근 차단, 링크 회수 후 기존 요청 승인, 카카오 콜백 계정 중복 방지, CSRF/구버전 엔드포인트 차단, refresh 재사용 시 폐기 유지, 알림 설정 조회와 매장 없는 직원의 개인 구독 격리. 생성 데이터는 트랜잭션 롤백.
- 매장 격리 AST 검사: auth/members/bootstrap/notifications 경로 통과. 현재 직원 조회 변경도 확인.
- 웹: `pnpm check` 통과 (lint, TypeScript, production build). 웹 단위 테스트 러너는 없으며 브라우저 확인과 구분.
- 실제 카카오: 사용자가 직접 로그인·동의 후 역할 선택 화면 도착을 확인. 직원 역할 선택 후 `/staff/pending` 표시 확인.
- 브라우저: 새로고침 세션 복원, API 중단 시 오류/재시도 화면, API 복구 후 재로그인 없는 복원 확인. 직원 계정의 점주 URL 접근 시 직원 화면 복귀, 무효 초대 링크 안내 확인.

## 남은 검증

- 실제 휴대폰 카카오톡 인앱 브라우저와 두 카카오 계정을 이용한 점주/직원 승인 전체 흐름.
- 실제 Push 전송·카카오톡 공유(별도 VAPID 및 공개 JavaScript 키 설정 필요).
- 두 탭 동시 갱신 및 실제 access 만료 시간 경과의 브라우저 검증.
- 전체 초대/직원 관리 UI의 모바일·실패 경로 순회. API 시나리오는 자동 검증함.
- 운영 환경변수·Redirect URI·migration 배포 및 운영 인수.

현재 직원 계정의 “아직 합류한 매장이 없어요”는 정상이다. 역할은 한 번만 선택하고, 직원은 점주의 초대 링크와 승인을 거쳐야 한다.
