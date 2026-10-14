# 카카오 운영 환경변수 반영 (2026-10-08)

사용자 요청: EC2 `i-0a83bc49c38c9f36c`에 SSM 접속하여 카카오 환경변수를 변경하고 접속 실패 원인을 확인.

## 접속 진단

- 로컬 기본 AWS CLI는 AskBuddy와 다른 계정의 `mvpilot-admin`으로 인증됨. 해당 자격으로 StartSession은 `TargetNotConnected`.
- AskBuddy 전용 CLI 로그인 시 브라우저에서 `Authentication failed / 잘못된 요청`. 구체적인 OAuth 오류 원인은 확정하지 않음. 로컬 CLI 설정을 덮어쓰지 않음.
- 사용자가 AWS 콘솔에서 `799183605792 / askbuddy`로 직접 로그인한 후 Session Manager 접속 성공. 인스턴스는 Online, Ubuntu.
- CloudShell 환경 생성은 오류로 사용 불가. 콘솔 Session Manager를 사용했고 `sudo su - ubuntu` 실행 성공.

## 반영 결과

- 운영 파일: `/home/ubuntu/askbuddy.env`
- 백업: `/home/ubuntu/askbuddy.env.kakao-20261008T084944Z.bak`
- 파일 권한: 600 유지. 기존 변수 보존 후 아래 다섯 키만 추가·갱신.
- `KAKAO_REST_API_KEY`, `KAKAO_CLIENT_SECRET`: 로컬에서 로그인 검증한 동일 앱의 값. 숨김 입력으로 전달했고 원문을 출력하지 않음.
- `KAKAO_REDIRECT_URI=https://api.askbuddy.kr/auth/kakao/callback`
- `WEB_BASE_URL=https://askbuddy.kr`
- `AUTH_COOKIE_SECURE=true`
- 기존 `ALLOWED_ORIGINS=https://askbuddy.kr,https://www.askbuddy.kr` 유지.
- `docker compose config --quiet` 통과.
- `/home/ubuntu/askbuddy/deploy`에서 `docker compose up -d --no-build --no-deps --force-recreate api` 실행.
- 새 API 컨테이너의 키 존재 여부, 세 가지 공개 설정값 확인. 내부 및 외부 `/health` 200.
- 작업 완료 후 생성한 SSM 세션 종료.

## 운영 카카오 로그인이 아직 안 되는 이유

현재 서버 체크아웃은 `215631b`. 실행 중인 Settings에 `kakao_rest_api_key` 필드가 없고 `/auth/providers`는 404. OpenAPI의 인증 경로는 기존 signup/login/join/stores/invites뿐이다.

이번에는 환경변수만 반영했다. 카카오 코드·웹·DB migration은 배포하지 않았고 커밋·푸시도 하지 않았다. 운영 사용에는 검증한 코드와 migration 배포, 카카오 콘솔의 운영 Redirect URI 등록 확인이 남아 있다.
