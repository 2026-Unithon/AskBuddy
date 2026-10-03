# 운영자 역할과 진단 화면 접근 설계

2026-10-02 · 상태: **구현됨, 운영 반영 전.** 구현 계획 [OPS_OPERATOR_ACCESS_PLAN.md](OPS_OPERATOR_ACCESS_PLAN.md). 구현은 [GitHub 이슈 #33](https://github.com/2026-Unithon/AskBuddy/issues/33)으로 추적한다.

## 1. 배경

- `GET /preflight`가 인증 없이 열려 있다. `?deep=1`은 호출할 때마다 OpenAI·Gemini를 실제로 부른다
  (`api/app/preflight.py`). 운영 도메인을 아는 누구나 반복 호출해 비용을 쓰게 할 수 있다.
- 응답에는 DB 호스트, CORS 허용 목록, 모델 이름, 매장·카드 수 같은 운영 정보가 들어 있다.
- 나중에 고객 문의(CS) 기능이 들어오면 매장 소속이 아닌 "서비스 운영자" 계정이 어차피 필요하다.
  그래서 운영자는 환경변수 단일 계정이 아니라 **DB 사용자 역할**로 둔다 (2026-10-02 차준혁 결정).

## 2. 범위

포함
- `users.role`에 `OPERATOR` 추가
- 운영자 로그인 `POST /ops/login`
- `/preflight`(기본·deep)를 운영자 전용으로 전환
- 진단 결과의 잘못된 안내 두 건 수정(§6)
- Web `/preflight`를 운영자 로그인 → 진단 화면 흐름으로 변경
- 운영자 계정 생성 스크립트

제외
- CS 기능, 운영자 전용 화면 추가, 운영자 권한 등급 구분
- 운영자의 매장 데이터 열람. CS 설계 때 범위·감사 기록과 함께 따로 정한다

## 3. 데이터

- migration 하나: `users_role_check`를 `('OWNER','STAFF','OPERATOR')`로 교체한다.
- `store_members.member_role`은 `OWNER`/`STAFF` 그대로 둔다. 운영자는 어느 매장에도 소속되지 않는다.
  그래서 기존 매장 API의 `get_store_id`(JWT `store_id` + 현재 membership 확인)를 통과할 수 없다.
- 운영자는 가입 API로 만들 수 없다. `/auth/signup`은 지금처럼 `OWNER`만 받는다.

## 4. API

### 4-1. `POST /ops/login`

- 요청: `{ email, password }`
- `users.role = 'OPERATOR'`이고 비밀번호가 맞을 때만 통과한다. 실패는 사유와 관계없이 같은 401로 응답한다.
- 계정이 없을 때도 bcrypt 비교를 한 번 수행해 응답 시간으로 계정 존재 여부를 알 수 없게 한다.
- 같은 IP+이메일 조합으로 실패가 반복되면 일정 시간 차단한다. 서버가 한 대라 프로세스 메모리에서 센다.
  서버를 여러 대로 늘리면 저장 위치를 다시 정한다.
- Caddy 뒤에서 uvicorn 을 `--proxy-headers` 없이 띄우면 IP 는 프록시 주소로 고정돼, 잠금은 사실상 이메일 단위다.
  운영자 이메일을 아는 사람은 누구나 그 계정을 15분간 잠글 수 있다. 나중에 `--proxy-headers` 를 켜면
  신뢰할 프록시만 `--forwarded-allow-ips` 로 지정하고 `'*'` 는 쓰지 않는다.
- 응답: `{ token, operator: { user_id, name, email } }`

### 4-2. 운영자 토큰

| claim | 값 |
|---|---|
| `user_id` | 운영자 user_id |
| `role` | `OPERATOR` |
| `aud` | `askbuddy-ops` |
| `exp` | 발급 후 60분 |
| `store_id` | 넣지 않음 |

- 제품 API의 `get_claims`는 audience를 지정하지 않고 decode한다. PyJWT는 이 경우 `aud`가 있는 토큰을
  `InvalidAudienceError`로 거부한다. 그래서 운영자 토큰으로 매장 API를 호출하면 401이 된다. 이 동작을 테스트로 고정한다.
- 운영자 의존성(`OperatorClaims`)은 `audience="askbuddy-ops"`로 decode하고, 요청마다 DB의 `users.role`이
  여전히 `OPERATOR`인지 다시 확인한다. 역할을 회수하면 남은 토큰도 즉시 막힌다.

### 4-3. `/preflight`

- 경로는 유지하고 `OperatorClaims`를 요구한다. 토큰 없음·만료·제품 토큰은 401, 역할 회수는 403.
- `/health`는 공개로 둔다. 응답은 기동 여부와 env 이름뿐이다.

## 5. Web `/preflight`

- 운영자 토큰이 없으면 로그인 폼, 있으면 기존 진단 화면을 보여 준다.
- 토큰은 `sessionStorage`에 둔다. 탭을 닫으면 사라지고, 제품 로그인 상태(`localStorage`)와 섞지 않는다.
- 401을 받으면 토큰을 지우고 로그인 폼으로 돌아간다. 로그아웃 버튼을 둔다.
- 진단 실패 안내의 "Railway의 ALLOWED_ORIGINS" 문구를 호스팅과 무관한 표현으로 바꾼다.
- 서버 상태는 TanStack Query로 조회하고, 화면 컴포넌트가 토큰 수명을 직접 관리하지 않는다(`web-async-state-check`).

## 6. 진단 결과 수정 두 건

### 6-1. 데이터베이스 항목의 잘못된 안내

- 현재 DB 점검은 연결과 테이블 조회를 한 덩어리로 처리한다. 테이블이 하나 없어도 "SUPABASE_DB_URL 확인"이라는
  연결 문제 안내가 나온다. 2026-10-02 운영 DB에 migration 17개가 미적용이었을 때 실제로 이렇게 오진됐다.
- 수정: 연결 확인과 스키마 확인을 분리한다. 없는 테이블은 "스키마" 항목에 이름과 함께 표시하고, 해결 방법으로
  migration 적용을 안내한다. 낡은 기준("테이블 24개여야 함")은 실제 필요한 테이블 존재 여부(`to_regclass`)로 바꾼다.

### 6-2. 검색 게이트 401

- 검색 점검이 자기 서버의 `/reg/retrieve`를 HTTP로 호출하는데, 이 경로는 보안 정리로 JWT가 필요해졌다.
  점검만 그 변경을 따라가지 못해 항상 `401 missing bearer token`이 나온다.
- 수정: HTTP를 거치지 않고 `retrieve_question`을 직접 호출한다.
  - 데모 매장(`demo-cafe`)이 없으면 실패가 아니라 "점검 생략(warn)"으로 표시한다. 운영 DB에는 시드가 없을 수 있다.
  - 임베딩 비용은 `UsageContext(cost_phase="OPERATING", cost_purpose="DEVELOPMENT", stage="QUERY")`로 기록한다.
    고객 월 운영비(D21)에 섞지 않는다.

## 7. 운영자 계정 생성

`api/scripts/create_operator.py --email <이메일> --name <이름>`
- 비밀번호는 `getpass`로 두 번 입력받는다. 인자·환경변수로 받지 않는다(셸 기록에 남지 않게).
- 같은 이메일이 이미 있으면 역할을 바꾸지 않고 실패한다. 기존 점주 계정을 운영자로 승격하지 않는다.
- 운영 서버에서 `docker compose exec api python scripts/create_operator.py ...`로 실행한다.

## 8. 계약 문서 반영

구현할 때 `docs/dev/ASKBUDDY_MVP_CURRENT.md`를 함께 고친다.
- §18-1 API 표: 인증에 `/ops/login`, 진단 줄에 "`/preflight` 운영자 전용"
- §19-1 매장 격리: 운영자 토큰은 매장 API에 쓸 수 없다는 규칙

## 9. 검증

- API 테스트
  - 운영자 로그인 성공, 틀린 비밀번호·OWNER 계정·없는 계정은 같은 401
  - 실패 반복 시 차단
  - 운영자 토큰으로 매장 API 호출 시 401, 제품 토큰으로 `/preflight` 호출 시 401
  - 역할 회수 뒤 남은 토큰은 403
  - DB 점검: 없는 테이블 이름 표시, 연결 실패와 구분
  - 검색 점검: 데모 매장 없으면 warn
- `store-isolation-check`(API·migration), `web-async-state-check`(Web)
- Web은 `pnpm check`와 브라우저 확인을 구분해 보고한다

## 10. 운영 반영 순서

1. PR 머지 → 자동 배포가 migration 적용과 서버 재배포를 수행 ([API 자동 배포](../../release/plan/API_AUTO_DEPLOY_DESIGN.md))
2. 운영 서버에서 운영자 계정 생성
3. `https://askbuddy.kr/preflight`에서 로그인 후 진단 확인
