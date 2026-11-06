# 카카오 로그인 운영 배포·실제 인증 확인 — 2026-10-08

## 배포

사용자가 커밋·푸시·main 반영·운영 배포를 명시적으로 승인했다.

- PR: https://github.com/2026-Unithon/AskBuddy/pull/52 (병합 완료).
- 운영 커밋: `b720f1fcd45e39b5aaf89cd03dc83aaa41400adf`.
- main CI: https://github.com/2026-Unithon/AskBuddy/actions/runs/37780092092 (성공).
- API 배포: https://github.com/2026-Unithon/AskBuddy/actions/runs/37780358841 (성공).
- Vercel 운영 배포도 같은 SHA로 성공. 실제 `https://askbuddy.kr/`에서 카카오 버튼을 확인했다.
- 기존 로컬 `w/kakao-auth` 작업 폴더와 별도 R 미커밋 변경은 유지했다. 검증한 최신 main 기반 트리만 `codex/kakao-production`으로 커밋했다.

최초 GitHub DB 검사에서 `pytest`가 설치되지 않아 실패했다. DB job의 검증용 설치 목록에 pytest를 추가했고, PR·main의 API/DB/브라우저 필수 검사 모두 통과했다. 제품 실행 의존성은 바꾸지 않았다.

## DB 및 EC2 확인

- 운영 DB 백업이 S3에 성공했다. 백업 객체 이름은 `db/20261008T125523Z-b720f1fcd45e.dump`다.
- dry-run 대상은 `20261008130000_kakao_auth_join_sessions.sql` 하나였고, 그 migration만 적용됐다.
- EC2 Session Manager에서 읽기 전용 DB transaction으로 적용 이력, 인증 테이블 3개, 변경 컬럼 4개, 인증 인덱스 4개를 확인했다.
- `users.role` nullable, `store_members.removed_at/removed_by`, `invite_codes.revoked_at` 반영을 확인했다.
- 서버 HEAD가 위 운영 커밋과 일치했다.
- 키·시크릿은 설정 여부만 확인했다. 운영 callback 주소와 `AUTH_COOKIE_SECURE=true`를 확인했고 검증 exit code는 0이었다.
- 검증용 SSM 세션은 종료했다. DB reset·seed·테스트용 계정 생성은 하지 않았다.

## 운영 HTTP 검사 — 19개 통과

- health 200, provider `kakao=true`, OAuth 시작 302.
- Kakao authorize host·운영 callback URI·PKCE S256·state 확인.
- OAuth 쿠키 Secure·HttpOnly·SameSite=Lax·10분 만료 및 no-store 확인.
- 변조된 콜백 state 거절, 콜백 no-store/no-referrer 확인.
- askbuddy.kr 및 www.askbuddy.kr에서 credentialed CORS 정상, 세션 없는 refresh는 401.
- 외부 Origin refresh는 403, 미인증 직원 관리 접근은 401.
- 없는 초대 링크는 404, 구버전 join·invite 생성 API는 404.

이 검사는 사용자 데이터 생성 없이 별도 HTTP 클라이언트로 수행했다. 실행 스크립트와 로그는 `output/check_kakao_production.py`, `output/kakao-production-check.log`에 있다.

## 실제 계정 브라우저 확인

1. 운영 시작 화면에서 카카오 로그인 버튼을 눌러 실제 카카오계정 로그인 화면에 연결됐다.
2. 사용자가 직접 로그인·동의한 뒤 "잘 나온당"이라고 응답했다.
3. 브라우저가 `https://askbuddy.kr/auth/role`로 돌아와 "어떤 분이세요?"와 두 역할 버튼을 표시하는 것을 직접 확인했다.
4. 새로고침 후에도 역할 선택 화면이 유지됐다. HttpOnly refresh 쿠키를 통한 세션 복원을 확인했다.
5. 역할 선택 전에 `/owner`로 접근하면 `/auth/role`로 돌아왔다. 미선택 계정의 보호 화면 접근을 차단했다.

계정의 역할은 사용자가 직접 고르도록 선택하지 않았고 로그인 상태를 유지했다. 화면 증거는 `output/kakao-production-role-success-20261008.jpg`다.

## 검증 범위

카카오 운영 로그인·콜백·신규 계정 역할 선택·새로고침 세션 복원은 확인 완료다. 실제 계정의 역할 확정 뒤 매장 생성, 두 계정의 초대→합류 요청→점주 승인, 운영 로그아웃, 실제 기기 Push는 이번 운영 브라우저에서 아직 수행하지 않았다. 관련 로직은 앞선 API·DB·합성 API 브라우저 검사에 포함된다. 전체 MVP 인수 완료를 의미하지 않는다.
