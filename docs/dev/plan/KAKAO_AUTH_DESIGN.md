# 카카오 로그인 · 초대 링크 · 합류 승인 · 90일 세션 설계

2026-10-03 · 상태: **설계 초안, 검토 대기.** 구현 계획 [KAKAO_AUTH_PLAN.md](KAKAO_AUTH_PLAN.md). 구현은 [GitHub 이슈 #37](https://github.com/2026-Unithon/AskBuddy/issues/37)로 추적한다.
§1~§3(목적·범위·데이터)은 대화에서 합의했다. §4 이후(API·세션·화면·테스트)는 합의된 결정을 바탕으로
작성한 초안이라 검토가 필요하다. 검토할 지점은 §10에 모았다.

## 1. 배경과 목적

- 지금 인증은 이메일+비밀번호(bcrypt)와 자체 JWT(HS256, 24시간, 갱신 없음)다. 토큰은 웹 `localStorage`에 있다.
  그래서 사용자가 **매일 다시 로그인**한다.
- 알바 합류는 4자리 hex 초대코드(`CAFE-A3F2`, 65,536가지)를 손으로 입력하고, 입력 즉시 매장에 들어온다.
  코드는 대입 공격이 가능하고, 점주가 누가 들어왔는지 통제할 수 없다.
- 초대는 온보딩 완료 화면(`web/app/owner/complete`)에서 한 번 보이고 다시 찾아갈 곳이 없다.

목적(우선순위 순, 2026-10-03 차준혁 결정)
1. 점주·알바 가입 전환율 — **카카오를 기본 로그인**, 이메일은 보조
2. 카카오 알림 연계 — 이번에는 **계정 연결 고리만** 만든다
3. 알바 합류 마찰 감소 — 초대 링크 + 카카오

MVP §25는 "카카오 SSO"를 추후 범위로 두었다. 창업 트랙 전환에 따라 이번에 당긴다.
구현 전에 MVP §8·§18·§19·§21·§25와 TODO에 범위 변경을 먼저 반영한다(PLAN 0단계).

## 2. 범위

포함
- 카카오 로그인(서버 주도 Authorization Code + PKCE)
- 초대 링크(무작위 토큰, 코드 비노출), 링크 재생성
- 알바 합류 요청 → 점주 승인/거절 → 승인 후 접근
- 점주 직원 관리 화면(O08 구체화): 링크 복사·공유·재생성, 승인 대기, 직원 목록, 내보내기
- 90일 슬라이딩 세션(refresh token 회전, 회수 가능), 이메일 로그인에도 같이 적용
- 기존 4자리 초대코드 전부 무효화

제외
- 카카오 토큰 보관·"나에게 보내기"·알림톡·전화번호 수집(비즈 앱 필요)
- 기존 이메일 계정과 카카오 계정 자동 연결. 카카오 이메일은 선택 동의라 신뢰하지 않는다
- 카카오 "연결 끊기" 웹훅, 회원 탈퇴
- 한 계정의 다중 역할·다중 매장
- 애플·구글 로그인(스키마만 확장 가능하게 둔다)

## 3. 데이터

`store_members`를 참조하는 FK 다수가 `on delete cascade`라(`db/001_init_schema.sql` 261·276·302행 등),
멤버 행을 지우면 그 직원의 질문·학습 기록이 사라진다. `store_members`를 읽는 코드는 17개 파일 약 37곳이다.
그래서 **대기자는 별도 테이블**, **내보내기는 표시**로 처리한다.

### 3-1. 새 테이블

`user_identities` — 외부 로그인 연결
| 컬럼 | 비고 |
|---|---|
| `identity_id` bigint identity PK | |
| `user_id` | `users` FK, on delete cascade |
| `provider` | `check (provider in ('KAKAO'))` |
| `provider_user_id` varchar(64) | 카카오 회원번호(`/v2/user/me`의 `id`) |
| `created_at`, `last_login_at` | timestamptz |
| | `unique (provider, provider_user_id)`, `unique (user_id, provider)` |

카카오 프로필 원본·카카오 토큰은 저장하지 않는다.

`store_join_requests` — 합류 요청
| 컬럼 | 비고 |
|---|---|
| `request_id` bigint identity PK | |
| `store_id` | `stores` FK cascade |
| `user_id` | `users` FK cascade |
| `invite_id` | `invite_codes` FK, on delete set null |
| `status` | `PENDING` `APPROVED` `REJECTED` |
| `requested_at`, `decided_at`, `decided_by`(users FK set null) | |
| | `unique (store_id, user_id) where status = 'PENDING'` (partial) |

승인 전에는 `store_members` 행이 없다. 기존 37곳 쿼리가 대기자를 직원으로 보는 일이 구조적으로 없다.

`auth_refresh_tokens` — 세션
| 컬럼 | 비고 |
|---|---|
| `token_id` bigint identity PK | |
| `user_id` | `users` FK cascade |
| `token_hash` char(64) unique | SHA-256(hex). 원문은 저장하지 않는다 |
| `family_id` uuid | 한 로그인에서 이어진 회전 계열 |
| `expires_at` | 발급 + 90일 |
| `created_at`, `last_used_at`, `revoked_at` | |
| `replaced_by` | 회전된 다음 `token_id` |
| | index `(user_id) where revoked_at is null` |

### 3-2. 기존 테이블 변경

- `store_members`: `removed_at timestamptz`, `removed_by bigint references users(user_id) on delete set null` 추가.
  내보내기는 `removed_at`을 기록한다. 재초대·재승인은 `removed_at`을 비운다(`unique(store_id,user_id)` 유지).
- `invite_codes`: `revoked_at timestamptz` 추가. `code`에 22자 base64url 토큰(128비트)을 넣는다(varchar(30)에 들어감).
  매장당 활성 링크(`revoked_at is null and expires_at > now()`)는 하나다. 새 링크의 `expires_at`은 `'infinity'`.
  점주가 언제든 다시 복사할 수 있어야 하므로 토큰을 해시가 아니라 그대로 둔다. 화면·응답 어디에도 토큰만
  따로 보여주지 않고 링크 URL로만 전달한다. 유출 시 피해는 승인 관문이 막는다.
- `notification_events.event_type` check에 `JOIN_REQUESTED`·`JOIN_APPROVED` 추가, `destination` check를 `^/(owner|staff)/[A-Za-z0-9_/?=&.-]*$`로 넓힌다.
- migration에서 기존 코드 전부 `revoked_at = now()`. 데모 시드 `CAFE-DEMO`는 고정 토큰으로 교체(로컬 시연용).

모든 변경은 가산형이다. migration 직후에도 기존 API는 동작한다.

## 4. 인증 흐름과 API

### 4-1. 카카오 로그인 (서버 주도)

```
web [카카오로 시작] → GET {API}/auth/kakao/start?intent=…&invite=…&next=…
  → API: state·code_verifier 생성, 서명 쿠키 ab_oauth(10분, Path=/auth/kakao) 설정
  → 302 https://kauth.kakao.com/oauth/authorize
        ?client_id&redirect_uri&response_type=code&state&code_challenge&code_challenge_method=S256
  → 카카오 동의 → GET {API}/auth/kakao/callback?code&state   (취소 시 ?error=access_denied)
  → API: 쿠키 state == 쿼리 state 확인 → POST /oauth/token (client_secret, code_verifier)
         → GET kapi.kakao.com/v2/user/me → id, nickname
         → §4-2 규칙으로 계정 처리 → refresh 쿠키 설정 → ab_oauth 삭제
  → 302 {WEB}/auth/complete?next=…        (실패: {WEB}/auth/complete?error=<코드>)
  → web: POST {API}/auth/refresh → access token → 목적지로 이동
```

- 카카오 OIDC 메타데이터로 확인한 사실(2026-10-03): `code_challenge_methods_supported: ["S256"]`,
  `token_endpoint_auth_methods_supported: ["client_secret_post"]`.
- `ab_oauth`는 우리 `jwt_secret`으로 서명한 JWT(`aud=askbuddy-oauth`, 10분)다. 담는 값은
  `state`, `code_verifier`, `intent`, `invite_id`, `next`. 서버 테이블 없이 CSRF와 PKCE를 처리한다.
  제품 `get_claims`는 audience 없이 decode하므로 PyJWT가 `aud` 있는 토큰을 거부한다(이슈 #33에서 확인).
- 카카오 access token은 사용자 조회에만 쓰고 버린다.
- 동의항목은 `profile_nickname`(필수)만 요청한다. 이름은 닉네임으로 채운다.
- `next`는 `/owner/` 또는 `/staff/`로 시작하는 상대 경로만 허용한다(오픈 리다이렉트 방지). 아니면 버린다.

### 4-2. intent별 계정 처리

로그인 화면은 **하나**다(2026-10-03 결정, 사용자 제공 화면: 카카오 로그인 / 이메일로 시작하기 / "알바생은 사장님이 보낸 링크로 바로 들어와요").
역할 선택 화면을 먼저 두지 않는다. 기존 계정은 역할과 상관없이 바로 로그인하고, 새 계정은 가입 직후 역할을 한 번 고른다.

| intent | 연결된 계정 있음 | 연결된 계정 없음 |
|---|---|---|
| `LOGIN` (로그인 화면) | 역할과 상관없이 로그인 → bootstrap 목적지 | `users(role=NULL, name=닉네임)` + identity → `/auth/role`에서 "사장님이에요 / 알바생이에요" |
| `STAFF_JOIN` (초대 링크) | 역할 미정 → STAFF로 확정 + 합류 요청. STAFF → 이미 그 매장 직원이면 로그인, 다른 매장 직원이면 `ALREADY_IN_OTHER_STORE`, 아니면 합류 요청. OWNER → `ROLE_CONFLICT` | `users(STAFF)` + identity + 합류 요청 |

- `users.role`은 NULL을 허용한다(역할 미정). 역할 미정 토큰에는 `role` claim이 없고 매장 API는 전부 403이다.
- `POST /auth/role` `{role}`은 역할이 비어 있을 때 **한 번만** 성공한다(이후 409 `ROLE_ALREADY_SET`).
- 사장님을 고르면 `/owner/intent`(매장 만들기), 알바생을 고르면 `/staff/pending`("초대 링크를 받아 주세요").
- `STAFF_JOIN` 한 번으로 "로그인 / 가입 / 합류 요청"이 모두 처리된다.
- `STAFF_JOIN`의 초대 검증은 start에서 한 번, callback에서 한 번 더 한다(그 사이 재생성될 수 있음).
  무효면 `INVITE_INVALID`.
- 다른 매장 직원이 다른 매장 링크로 들어오면 `ALREADY_IN_OTHER_STORE`로 막는다(단일 매장 전제).
- 오류 코드는 웹 `/auth/complete`에서 사람이 읽을 문구로 바꾼다(MVP §28 문구 사전에 추가).

### 4-3. 이메일 경로 정렬

- `/auth/signup`, `/auth/login`, `/auth/stores`: 응답은 지금과 같고, 추가로 refresh 쿠키를 설정한다.
- `/auth/login`은 역할 일치 검사를 없앤다(단일 화면). `role` 필드는 받기만 하고 무시한다(구버전 웹 호환).
- `/auth/signup`의 `role`은 선택이다. 없으면 역할 미정 계정이 되고 `/auth/role`에서 고른다.
- `/auth/join`(이메일+초대코드 한 번에 가입·합류)은 **제거**한다. 이메일 알바는 가입·로그인한 뒤
  `POST /auth/join-requests`(§4-5)로 요청한다. 초대 없이 매장에 들어오는 우회 경로가 없다.
- `POST /auth/invites`(4자리 코드 발급)는 제거하고 §4-5로 대체한다.

### 4-4. 세션 API

- `POST /auth/refresh` — `ab_refresh` 쿠키를 읽는다.
  - 유효하면 새 refresh로 회전(이전 행 `revoked_at`·`replaced_by` 기록)하고 access token을 돌려준다.
  - **이미 회전된 토큰이 다시 오면 탈취로 보고 그 `family_id` 전체를 폐기**하고 401.
  - access token의 `store_id`는 서버가 정한다: 그 사용자의 활성 멤버십(`removed_at is null`).
    없으면 넣지 않는다(대기 중 알바, 매장 만들기 전 점주).
  - CSRF: 쿠키가 `SameSite=Lax`라 교차 사이트 POST에는 실리지 않는다. 추가로 `Origin`이
    `ALLOWED_ORIGINS`에 없으면 403.
  - 응답: `{ token, user: { user_id, name, role, store_id? } }`
- `POST /auth/logout` — 현재 refresh의 family 폐기, 쿠키 삭제. 쿠키가 없어도 204.
- 쿠키 `ab_refresh`: `HttpOnly; Secure; SameSite=Lax; Path=/auth; Max-Age=90일`, Domain 미지정(API 호스트 전용).
  `askbuddy.kr`와 `api.askbuddy.kr`는 같은 사이트라 `credentials: "include"` fetch에 실린다.
  로컬(`localhost:3000`↔`localhost:8000`)도 같은 사이트다. `Secure`는 설정값(`auth_cookie_secure`)으로 끈다.
- access token 수명은 60분(`access_token_expire_minutes`). 기존 `jwt_expire_minutes`(1440)는
  `api/scripts/dev_token.py`가 쓰므로 남기되 제품 로그인 응답에는 쓰지 않는다.
- 여러 탭이 동시에 refresh하면 한쪽이 이미 회전된 토큰을 보낸다. 회전 후 **30초 안**의 재사용은 탈취로 보지 않고
  401만 돌려준다(family 유지). 쿠키는 탭끼리 공유하므로 웹이 한 번 다시 시도하면 새 쿠키로 통과한다.

### 4-5. 초대·합류·직원 관리 API

공개(인증 없음)
- `GET /auth/invites/{token}` → `{ store_name }`. 무효·재생성됨은 같은 404(존재 여부 비노출).

로그인한 알바(store_id 없는 STAFF 토큰)
- `POST /auth/join-requests` `{ invite_token }` → `{ status: "PENDING" | "ALREADY_MEMBER", store_name }`.
  이미 로그인된 알바가 초대 링크를 열면 웹이 바로 부른다. 새로 만들면 점주에게 알림. 이미 PENDING이면 그대로.
  무효 링크 404 `INVITE_INVALID`, 점주 토큰 403 `ROLE_CONFLICT`, 다른 매장 활성 직원 409 `ALREADY_IN_OTHER_STORE`.
- `GET /auth/join-status` → `{ status: PENDING|REJECTED|APPROVED|REMOVED|NONE, store_name? }`. 가장 최근 요청 기준.
  `APPROVED`면 웹이 `/auth/refresh`로 store_id 있는 토큰을 다시 받는다.

점주(`/members`, 새 모듈 `api/app/members/`. 기존 `api/app/team/`은 내부 평가용이라 이름을 피한다)
- `GET /members/invite-link` → `{ url }`. 활성 링크가 없으면 만들어 돌려준다.
- `POST /members/invite-link/rotate` → 이전 링크 `revoked_at`, 새 링크 `{ url }`.
- `GET /members` → `{ pending: [{request_id, name, requested_at}], active: [{user_id, name, joined_at}] }`.
- `POST /members/requests/{request_id}/approve` — 한 트랜잭션에서 요청 `APPROVED` +
  `store_members` upsert(새 행 또는 `removed_at` 해제). 이미 처리된 요청은 409.
- `POST /members/requests/{request_id}/reject` — `REJECTED`.
- `POST /members/{user_id}/remove` — `removed_at` 기록 + 그 사용자의 refresh 전부 폐기. OWNER 본인은 400.
- 모든 쿼리는 JWT의 `store_id`를 쓰고, 점주 확인은 기존 `get_store_id` + `role == OWNER`.

알림
- 합류 요청이 생기면 점주에게 `notification_events`(`JOIN_REQUESTED`, destination `/owner/members`) +
  Web Push(설정된 경우). dedupe_key는 `join_request:{request_id}`.
- **승인되면 알바에게 즉시 알림**(2026-10-03 결정). 승인 트랜잭션 안에서 `store_members`를 만든 직후
  알바에게 `notification_events`(`JOIN_APPROVED`, destination `/staff/roadmap`)를 만든다. 이 순서라
  "수신자는 매장 멤버" FK를 만족한다. 커밋 뒤 Web Push를 보낸다.
  - migration: `event_type`에 `JOIN_APPROVED`, `destination` 제약을 `^/(owner|staff)/…`로 넓힌다.
  - `push_subscriptions`는 사용자 단위라 매장 없는 알바도 구독할 수 있다. 지금 구독 API는 점주+매장 전용이므로
    로그인 사용자 누구나 쓰는 `GET /notifications/push-key`, `POST /notifications/my-subscriptions`를 추가한다
    (user_id는 JWT, 매장 범위 없음).
- 폴링하지 않는다. 대기 화면은 ① 서비스 워커가 Push를 받으면 열린 화면에 메시지를 보내 즉시 다시 조회하고,
  ② 앱이 다시 보이거나 포커스를 받을 때 다시 조회한다. 알림을 누르면 `/staff/roadmap`이 새로 열리고,
  세션 복원 때 서버가 store_id 있는 토큰을 주므로 바로 쓸 수 있다.
- Web Push 한계: iOS는 **홈 화면에 추가한 앱**(iOS 16.4+)에서만 받는다. 카카오톡 인앱 브라우저는 받지 못한다.
  이 경우에도 앱을 열면 ②로 즉시 반영된다.

### 4-6. 접근 경계 변경

- `get_store_id`(`api/app/deps.py`)에 `removed_at is null` 조건 추가. 내보낸 직원은 남은 access token으로도
  다음 요청부터 403이다.
- `/app/bootstrap`: STAFF이고 store가 없으면 `default_destination`은 항상 `/staff/pending`이다
  (요청 없음·대기·거절·내보내짐은 그 화면이 상태별 문구로 나눈다). 멤버십 조회에 `removed_at is null`.
- `store_members`를 읽는 나머지 37곳은 PLAN 2단계에서 하나씩 분류한다. 직원 목록·수, 알림 수신자,
  학습 대상처럼 "현재 직원"을 뜻하는 곳에만 `removed_at is null`을 건다. 과거 기록 조인은 그대로 둔다.

## 5. Web

### 5-1. 세션

- access token은 **메모리에만** 둔다. `localStorage`(`askbuddy_state`)에서 `token`을 빼고 `STATE_VERSION`을 올린다.
- 앱 시작(hydrate) 시 `POST /auth/refresh`를 한 번 호출해 토큰을 받는다. 실패하면 비로그인 상태.
- `fetchJson`: `Authorization`이 붙은 요청이 401이면 refresh를 **한 번만**(동시 요청은 같은 Promise 공유) 시도하고
  원 요청을 재시도한다. refresh도 실패하면 기존 `SESSION_EXPIRED_EVENT`.
- 인증 관련 fetch(`/auth/refresh`, `/auth/logout`, 로그인·가입)는 `credentials: "include"`.
- 토큰 수명 관리는 lib 계층이 소유하고 화면 컴포넌트는 관여하지 않는다(`web-async-state-check`).
- 운영자 세션(`web/lib/ops-session.ts`, sessionStorage)은 손대지 않는다.

### 5-2. 화면

| 경로 | 내용 |
|---|---|
| `/` | **단일 로그인 화면**(사진 기준): [카카오 로그인](`LOGIN`), [이메일로 시작하기] → `/auth/email`, 안내 "알바생은 사장님이 보낸 링크로 바로 들어와요". 로그인돼 있으면 목적지로 이동 |
| `/auth/email` **신규** | 이메일 로그인·가입 탭(역할 없이) |
| `/auth/role` **신규** | 역할 미정 계정의 1회 선택: 사장님이에요 / 알바생이에요 |
| `/role`, `/owner/auth`, `/staff/auth` | `/`로 redirect(설치 앱의 시작 주소가 `/role`이라 경로 유지). PWA `start_url`은 `/`로 |
| `/join/[token]` **신규** | 링크 미리보기 "OO카페에 합류합니다". **로그인돼 있으면** 바로 `POST /auth/join-requests` → "합류 요청을 보냈어요" → `/staff/pending`. **아니면** [카카오로 시작하기](`STAFF_JOIN`: 로그인·가입·요청 한 번에) + 이메일 로그인/가입(접힘, 끝나면 같은 요청). 점주로 로그인돼 있으면 `ROLE_CONFLICT` 안내. 무효 링크는 안내 화면 |
| `/auth/complete` **신규** | 콜백 도착점. refresh → bootstrap → 목적지. `error`면 문구 + 돌아갈 버튼 |
| `/staff/pending` **신규** | 상태별: 요청 없음("사장님께 초대 링크를 받아 주세요")·대기(매장명)·거절·내보내짐. 대기 중에는 [승인되면 알림 받기](Push 권한, 사용자 동작 필요). 폴링 없음 — Push 수신 메시지·화면 복귀 때 재조회, 승인되면 refresh 후 로드맵 |
| `/owner/members` **신규** | 초대 링크 카드([복사][공유][새로 만들기]+확인 모달), 승인 대기, 함께 일하는 직원, [내보내기]+확인 모달 |
| `/owner/complete` | 기존 코드 표시를 초대 링크 카드 컴포넌트로 교체 |

- 공유(2026-10-03 결정): **카카오 JS SDK `Kakao.Share` 카드 메시지가 기본**("OO카페에서 초대했어요" + [합류하기]).
  SDK를 못 쓰면(키 없음·차단·카톡 미설치) Web Share API, 그것도 없으면 복사. SDK는 공유에만 쓰고 로그인은 서버 흐름이다.
  웹에는 공개 전제의 **JavaScript 키**(`NEXT_PUBLIC_KAKAO_JS_KEY`)만 둔다. REST 키·Client Secret은 API에만.
- `/join/[token]`은 서버에서 매장명을 조회해 **OG 태그**(제목 "OO카페에서 초대했어요", 설명, 이미지)를 만든다.
  어느 공유 경로든 카톡·문자 미리보기에 매장명이 나온다. 토큰 주소는 `noindex`.
- 가드: 역할이 다른 화면 주소를 열면 로그아웃하지 않고 bootstrap 목적지로 보낸다. 인증 화면 경로는 `/` 하나.
- `/owner/members` 진입: 합류 요청 알림, 온보딩 완료 화면. 상시 진입점(마이페이지)과 로그아웃 버튼은
  Figma 수령 후 프론트 연동 때 만든다(2026-10-03 결정). 이번 작업은 `/auth/logout` API와 `logoutSession()`까지만.
- 초대 링크는 카카오톡 인앱 브라우저에서 열리는 경우가 많다. 인앱 브라우저는 설치한 앱(PWA)·Safari와
  쿠키가 따로라 로그인 안 된 상태로 보인다. 그래서 링크 화면은 "카카오 한 번으로 로그인·가입·요청"을 기본으로 한다.
  링크에서 설치 앱이 바로 열리게 하는 것은 웹(PWA)만으로는 보장되지 않는다(네이티브 앱 범위).
- 모든 새 화면은 MVP §17-5 필수 상태(로딩·빈 상태·오류·재시도)를 갖춘다.
- 카카오 버튼은 카카오 디자인 가이드(노란 배경 `#FEE500`, 심볼, "카카오 로그인" 계열 문구)를 따른다.

## 6. 설정·운영

API 환경변수(EC2 env 파일, Git 제외)
| 이름 | 예 |
|---|---|
| `KAKAO_REST_API_KEY` | 카카오 앱 REST API 키 |
| `KAKAO_CLIENT_SECRET` | 카카오 앱 Client Secret(활성화) |
| `KAKAO_REDIRECT_URI` | `https://api.askbuddy.kr/auth/kakao/callback` |
| `WEB_BASE_URL` | `https://askbuddy.kr` |
| `AUTH_COOKIE_SECURE` | 운영 `true`, 로컬 `false` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` | `60` / `90` |

Web 환경변수(Vercel): `NEXT_PUBLIC_KAKAO_JS_KEY`(카카오 JavaScript 키, 공개), `NEXT_PUBLIC_SITE_URL`(`https://askbuddy.kr`, OG 절대 주소).

카카오 개발자 콘솔(사용자가 직접)
- 앱 생성, 플랫폼 Web 도메인 `https://askbuddy.kr`, `http://localhost:3000`
- 카카오 로그인 활성화, Redirect URI `https://api.askbuddy.kr/auth/kakao/callback`, `http://localhost:8000/auth/kakao/callback`
- 동의항목 `profile_nickname` 필수 동의, Client Secret 활성화

키가 비어 있으면 `/auth/kakao/start`는 웹 `/auth/complete?error=KAKAO_NOT_CONFIGURED`로 돌려보내고, 웹은 카카오 버튼을 숨긴다
(`GET /auth/providers` → `{ kakao: bool }`). 로컬 개발과 테스트가 카카오 키 없이 돈다.

## 7. 보안 점검표

- state 불일치·쿠키 없음·만료 → `OAUTH_STATE_INVALID`, 계정 생성 없음
- PKCE S256, client_secret은 서버에만
- 오픈 리다이렉트: `next` 화이트리스트
- 초대 토큰 128비트, 무효·재생성 링크는 같은 404
- refresh 원문 비저장(SHA-256), 회전·재사용 감지·family 폐기, 내보내기·로그아웃 시 폐기
- refresh 엔드포인트 Origin 검사
- 대기·내보낸 직원은 `get_store_id`에서 차단(매장 격리 경계 한 곳)
- access token을 `localStorage`에서 제거(XSS 노출 축소)

## 8. 테스트

API(unittest + 가짜 DB·가짜 카카오 클라이언트, 기존 `test_ops_auth.py` 방식)
- 카카오: start 리다이렉트 파라미터(PKCE·state), state 불일치·쿠키 없음, 취소, intent 3종 × 기존/신규 계정,
  `ROLE_CONFLICT`, `INVITE_INVALID`, `ALREADY_IN_OTHER_STORE`, `next` 화이트리스트, 키 미설정
- 세션: 회전, 재사용 감지 family 폐기, 만료, 로그아웃, Origin 거부, store_id 서버 결정
- 합류: 로그인 알바의 `POST /auth/join-requests`(생성·중복·무효 링크·점주 토큰·다른 매장), 승인 시 멤버 생성·재승인 시 `removed_at` 해제,
  승인 시 알바 알림(`JOIN_APPROVED`) 생성, 거절, 이미 처리 409, 다른 매장 요청 404
- 알바 Push 구독: 매장 없는 STAFF 토큰으로 `my-subscriptions` 저장 가능, 다른 사용자 구독 삭제 불가
- 내보내기: 이후 `get_store_id` 403, refresh 폐기, 본인 내보내기 400
- 초대 링크: 활성 하나, 재생성 후 이전 링크 404, 재생성 전에 만든 요청은 승인 가능
- 알바 이메일 가입(`/auth/signup` STAFF)은 매장 없는 계정, `/auth/join` 제거 확인
- 로컬 Supabase에서 migration 적용과 기존 코드 무효화 확인, `store-isolation-check`

Web
- `pnpm check`, `web-async-state-check`, `ui-state-walkthrough`(대기·거절·무효 링크·refresh 실패 경로 포함)
- 실제 카카오 로그인은 로컬에서 테스트 앱 키로 수동 확인. 자동 E2E는 통합 검증 단계 범위

## 9. 운영 반영 순서

PR 머지 → 자동 배포(migration·서버) → 카카오 콘솔 설정·EC2 env 추가 → 서버 재시작 →
운영 웹에서 점주 카카오 가입·초대 링크·알바 합류·승인·내보내기 확인.
배포 직후 기존 사용자는 refresh 쿠키가 없어 **한 번 다시 로그인**해야 한다. 기존 초대코드는 무효가 되므로
점주는 직원 관리 화면에서 새 링크를 공유해야 한다.

## 10. 검토가 필요한 지점

1. 점주 카카오 신규 가입은 이름을 닉네임으로 바로 만든다. 이름 확인 단계를 둘지
2. ~~`STAFF_LOGIN` 무계정 차단~~ → 결정: 알바도 계정 생성 가능, 매장 접근 없음(§4-2)
3. ~~15초 폴링~~ → 결정: 승인 즉시 알바에게 알림·Push(§4-5)
4. 배포 직후 전 사용자 1회 재로그인(기존 24시간 JWT를 refresh로 교환해 주는 이관 경로는 두지 않음)
5. 알바 승인 알림이 없다(알바가 대기 화면을 열어 둬야 바로 안다). Web Push 구독은 멤버만 가능
