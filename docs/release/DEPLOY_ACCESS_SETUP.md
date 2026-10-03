# 새 운영 환경 접근 설정

2026-10-02 · 대상: 새 서버에 API를 올리고 Web·DB·도메인과 연결하는 사람.

서버(VM)를 만들고 Docker·Caddy를 설치하는 절차는 이 문서 범위가 아니다. 여기서는 **이미 떠 있는 서버를
서비스의 다른 부분과 어떻게 연결하는가**만 다룬다. 비밀값은 이 문서와 저장소에 적지 않는다.

## 1. 연결 구조

```
브라우저 ──https──▶ askbuddy.kr        (Vercel, Web)
브라우저 ──https──▶ api.askbuddy.kr    (서버의 Caddy :443 → api 컨테이너 :8000)
                                         ├─▶ Supabase Postgres (Session pooler)
                                         ├─▶ Supabase Storage
                                         └─▶ OpenAI · Gemini · Web Push
브라우저 ──서명 URL──▶ Supabase Storage  (파일 바이너리는 API를 거치지 않는다)
```

- 브라우저는 Vercel을 거치지 않고 API를 **직접** 호출한다(`web/lib/api.ts`의 `NEXT_PUBLIC_API_URL`).
  그래서 API에도 HTTPS와 CORS 허용이 필요하다.
- DB 위치는 서버를 옮겨도 바꾸지 않는다. 서버를 옮길 때 바뀌는 것은 §8에 정리했다.

## 2. 준비물

| 항목 | 어디서 얻나 | 비고 |
|---|---|---|
| 서버 고정 IP | 클라우드 콘솔 (AWS는 Elastic IP) | 해제하면 같은 IP를 되찾을 수 없다 |
| Supabase **Session pooler** 연결 문자열 | Supabase → 프로젝트 → **Connect** → Session pooler | §4 |
| Supabase URL, service role key | Supabase → Project Settings → API | 서버에만 둔다 |
| `JWT_SECRET` | **이전 운영 환경 값** | 바꾸면 모든 사용자가 다시 로그인해야 한다 |
| OpenAI·Gemini·Anthropic 키 | 각 콘솔 | 서버에만 둔다 |
| VAPID 공개키·개인키·subject | 이전 운영 환경 값 | 바꾸면 기존 Web Push 구독이 무효가 된다 |
| 기능 플래그 값 | 이전 운영 환경 값 또는 담당자 합의 | §5-4 |

## 3. DNS

도메인 등록업체(현재 가비아)의 DNS 관리에서 설정한다.

| 호스트 | 타입 | 값 | 용도 |
|---|---|---|---|
| `@` | A | Vercel Domains 화면이 안내하는 값 | Web |
| `www` | CNAME | Vercel Domains 화면이 안내하는 값 | Web |
| `api` | A | 서버 고정 IP | API |

- 가비아의 **웹 파킹·포워딩**이 켜져 있으면 DNS 설정을 덮어쓰므로 끈다. 기본 `@` 레코드가 있으면 지운다.
- 반영 확인: `dig +short api.askbuddy.kr` 가 서버 IP를 돌려줘야 한다.
- 서버를 옮기기 하루 전에 `api` 레코드 TTL을 300초로 낮춰 두면 전환이 빠르다.

## 4. Supabase

### 4-1. 연결 문자열

- **Session pooler**(포트 5432)를 쓴다.
  - Direct connection(`db.<ref>.supabase.co`)은 IPv6 전용이라 IPv6가 없는 서버에서 연결되지 않는다.
  - Transaction pooler(포트 6543)는 asyncpg prepared statement와 충돌한다. 쓰려면 코드 변경이 필요하다.
- 대시보드의 문자열을 **손으로 고치지 말고 그대로 복사**한다. 풀러 호스트의 `aws-0`/`aws-1`이나 리전이 하나만 달라도
  `tenant/user postgres.<ref> not found`로 연결이 거부된다.
- 비밀번호에 `@ # / %` 같은 문자가 있으면 연결 문자열이 깨진다. 영문·숫자만으로 재설정하는 것이 가장 간단하다.

### 4-2. 스키마(migration) 적용

새 환경을 띄우기 전에 운영 DB에 `supabase/migrations/` 가 모두 적용됐는지 확인한다.
API는 빠진 테이블이 있어도 일단 기동하고, 해당 기능을 쓸 때 실패한다.

```bash
# 저장소 루트에서. 연결 문자열은 셸 기록에 남지 않게 맨 앞에 공백을 하나 둔다
 supabase migration list --db-url "<Session pooler 연결 문자열>"
```

- Remote 칸이 비어 있는 migration이 미적용분이다. 목록을 확인한 뒤 적용한다.
  ```bash
   supabase db push --db-url "<Session pooler 연결 문자열>"
  ```
- Remote 칸이 **전부** 비어 있으면 기존 데이터가 없는 다른 프로젝트에 연결된 것이다. 적용하기 전에 연결 대상을 다시 확인한다.
- 운영 DB 변경이므로 적용 전 백업(`pg_dump`) 여부를 정한다.

### 4-3. Storage

- 비공개 버킷 `sources`가 있어야 한다. 경로 규칙은 `{store_id}/{voice|video|kakao|scan}/{uuid}.{ext}`이다.
- 없으면 `api/scripts/init_storage.py`로 만든다.

### 4-4. 무료 플랜 주의

일정 기간 접속이 없으면 프로젝트가 일시정지된다. 서버가 오래 꺼져 있었다면 먼저 대시보드에서 **Paused** 여부를 확인하고 Restore한다.

## 5. API 환경변수

서버에서 저장소 **밖**의 파일(예: `~/askbuddy.env`, 권한 600)에 두고 compose의 `env_file`로 넘긴다.
**값 뒤에 `#` 주석을 붙이지 않는다.** dotenv가 주석을 값의 일부로 읽을 수 있다.
전체 목록과 기본값은 `api/app/config.py`가 정본이다.

### 5-1. 접근 관련 — 반드시 운영값으로

| 변수 | 운영값 | 틀리면 |
|---|---|---|
| `ENV` | `production` | |
| `ALLOWED_ORIGINS` | `https://askbuddy.kr,https://www.askbuddy.kr` | 브라우저가 CORS로 막아 "서버에 연결할 수 없습니다" |
| `SUPABASE_DB_URL` | §4-1 Session pooler 문자열 | 기동 직후 종료 반복 |
| `SUPABASE_URL` | `https://<ref>.supabase.co` | 업로드 URL 발급·Storage 실패 |
| `SUPABASE_SERVICE_KEY` | service role key | 같음 |
| `STORAGE_BUCKET` | `sources` | 같음 |
| `JWT_SECRET` | 이전 운영값 (32바이트 이상) | 기존 로그인 전부 만료. 기본값 `dev-only-...`을 운영에 두지 않는다 |
| `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` | 운영 키 | 임베딩·추출·답변 실패 |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | 이전 운영값 | 셋 중 하나라도 비면 Web Push 없이 앱 내부 알림만 동작 |

- `ALLOWED_ORIGINS`는 브라우저 주소창의 origin과 **정확히** 같아야 한다. `www` 유무가 다르면 다른 origin이고, 끝에 `/`를 붙이지 않는다.
  Vercel 기본 주소(`*.vercel.app`)로도 테스트하려면 쉼표로 추가한다.
- `VAPID_SUBJECT`를 https 주소로 쓴다면 운영 도메인으로 맞춘다.

### 5-2. 동작 모드

| 변수 | 운영값 | 비고 |
|---|---|---|
| `INGEST_MODE` | `real` | 코드 기본값이 `mock`이다. 빠뜨리면 업로드가 실제 추출을 하지 않는다 |
| `ANSWER_MODE` | `grounded_llm` | |
| `GEMINI_MODEL`, `STT_MODEL`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` | `api/.env.example` 값 | 확정 결정 값. 바꾸지 않는다 |
| `RETRIEVAL_THRESHOLD`, `CONFIDENCE_THRESHOLD` | `api/.env.example` 값 | 같음 |

### 5-3. 연결 풀

`DB_POOL_MIN_SIZE`(기본 1)·`DB_POOL_MAX_SIZE`(기본 10). 서버 한 대 기준으로 기본값을 쓴다.
서버를 여러 대로 늘리면 대수 × 최대값이 Supabase 연결 한도를 넘지 않는지 확인한다.

### 5-4. 기능 플래그

모두 기본값이 꺼짐(`false`)이다. 이전 운영 환경의 값을 그대로 옮기고, 새로 켜거나 끄는 것은 담당자 합의 후에 한다.

| 변수 | 켜면 |
|---|---|
| `R_V2_ENABLED` | 새 답변 API(`/learn/v2/*`) 활성화. 꺼져 있으면 503 `V2_UNAVAILABLE` |
| `W_OWNER_ANSWER_WORKER_ENABLED` | 점주 답변을 지식에 반영하는 worker 실행. 꺼져 있으면 반영 상태가 `PENDING`에 머문다 |
| `W_ENTITY_REVISION_ENABLED`, `W_UPLOAD_PROPOSALS_ENABLED` | 업로드 사실 연결·검수 제안. 뒤의 것은 앞의 것이 켜져 있어야 기동된다 |
| `R_RERANKER_ENABLED`, `R_REVIEWED_SEMANTICS_ENABLED`, `R_GENERAL_SEMANTICS_ENABLED` | 답변 경로 실험 기능 |

### 5-5. 반영

env 파일을 바꾼 뒤에는 **컨테이너를 다시 만든다.** `docker compose restart`는 바뀐 env 파일을 다시 읽지 않는다.

```bash
cd ~/deploy && docker compose up -d --force-recreate api
```

§12-5 서버 전환을 마친 뒤에는 위치가 바뀌므로 아래 명령을 쓴다.

```bash
cd ~/askbuddy/deploy && docker compose up -d --force-recreate api
```

## 6. Caddy (API HTTPS)

```
api.askbuddy.kr {
    reverse_proxy api:8000
}
```

- 인증서는 Caddy가 Let's Encrypt에서 자동 발급·갱신한다. 서버 방화벽에서 **80·443**이 열려 있어야 한다.
- DNS가 반영되기 전에 기동하면 발급이 실패하지만, 반영된 뒤 Caddy가 다시 시도한다.
- api 컨테이너의 8000번은 외부에 열지 않는다. HTTPS를 거치지 않는 경로가 생긴다.
- 도메인을 바꾼 뒤에는 `docker compose up -d --force-recreate caddy`.

## 7. Vercel (Web)

1. **Settings → Domains**에 `askbuddy.kr`, `www.askbuddy.kr` 추가. 안내된 값을 §3 DNS에 넣는다.
2. **Settings → Environment Variables**: `NEXT_PUBLIC_API_URL=https://api.askbuddy.kr`
   - Web 환경변수는 이것 하나다. `NEXT_PUBLIC_SUPABASE_*`나 LLM 키를 추가하지 않는다.
   - `NEXT_PUBLIC_DEMO_MODE`는 데모 자격 증명 노출용이다. 실제 사용자 환경에서는 켜지 않는다.
3. **Redeploy.** `NEXT_PUBLIC_*`는 빌드할 때 코드에 들어가므로 값만 바꾸고 다시 배포하지 않으면 반영되지 않는다.

로컬 Web으로 운영 API를 시험할 때는 `web/.env.local`의 같은 변수를 바꾸고 `pnpm dev`를 다시 켠다.

## 8. 서버를 다른 곳으로 옮길 때 바뀌는 것

| 항목 | 바뀌나 |
|---|---|
| 코드, Dockerfile, compose, Caddyfile | 그대로 |
| API env 파일 | 그대로 복사 |
| DNS `api` A 레코드 | **새 서버 IP로 변경** |
| 서버 방화벽(80·443) | 새 클라우드에서 다시 설정 |
| HTTPS 인증서 | 새 서버의 Caddy가 자동 발급 |
| Vercel `NEXT_PUBLIC_API_URL` | 도메인을 쓰면 그대로 |
| Supabase | 그대로 |
| 자동 배포 | 자동 배포를 쓰면 새 서버로 옮긴 뒤 `api-production`의 `EC2_INSTANCE_ID`와 배포 역할 정책의 인스턴스 ARN을 바꾼다 (§12) |

전환 순서: 새 서버 기동 → `/health` 확인 → 처리 중인 업로드가 없는지 확인 → DNS 변경 → **옛 서버 즉시 중지**.
두 서버가 동시에 떠 있으면 서버 내부 worker와 주기 작업이 양쪽에서 함께 돈다. 현재 코드는 서버가 한 대라고 가정한다.

## 9. 연결 확인 순서

아래 순서대로 확인하면 어느 구간이 끊겼는지 바로 좁혀진다.

```bash
# 1) DNS
dig +short api.askbuddy.kr

# 2) HTTPS와 API 기동
curl https://api.askbuddy.kr/health

# 3) DB·Storage·키 연결 상태 (LLM 실호출 없음). 운영자 토큰이 필요하다. 없으면 401이다
#    운영자 계정: docker compose exec api python scripts/create_operator.py --email <운영자-이메일> --name <이름>
#    토큰: POST /ops/login 의 응답 token
curl -X POST https://api.askbuddy.kr/ops/login -H "Content-Type: application/json" \
  -d '{"email":"<운영자-이메일>","password":"<비밀번호>"}'
curl -H "Authorization: Bearer <token>" https://api.askbuddy.kr/preflight

# 4) CORS. Origin에는 브라우저 주소창의 origin을 넣는다
curl -i -X OPTIONS https://api.askbuddy.kr/auth/signup \
  -H "Origin: https://askbuddy.kr" \
  -H "Access-Control-Request-Method: POST"
```

- 3)의 응답에서 `blocking`이 비어 있어야 한다. 스키마·시드·색인 항목이 `dead`면 §4-2를 확인한다.
- 4)의 응답 헤더에 `access-control-allow-origin: https://askbuddy.kr`이 있어야 한다. 400이면 `ALLOWED_ORIGINS` 문제다.
- 마지막으로 브라우저에서 로그인 → 질문 → 업로드를 한 번씩 해 본다. `https://askbuddy.kr/preflight`에 운영자 계정으로 로그인해도 같은 진단을 볼 수 있다.

## 10. 자주 나는 오류

| 증상 | 원인 | 조치 |
|---|---|---|
| API가 기동 직후 종료를 반복, 로그 끝에 `tenant/user postgres.<ref> not found` | 풀러 호스트·리전·프로젝트 ID 불일치, 또는 프로젝트 일시정지 | §4-1 문자열을 대시보드에서 다시 복사, §4-4 확인 |
| `password authentication failed` | 주소는 맞고 DB 비밀번호가 틀림 | 비밀번호 재설정 후 문자열 갱신 |
| 로그에 `UndefinedTableError` | 운영 DB에 migration 미적용 | §4-2 |
| Web에 "서버에 연결할 수 없습니다", API 로그에 해당 요청이 없음 | 요청이 서버에 도착하지 않음 | 개발자도구 Network의 Request URL 확인. 옛 주소면 §7 Redeploy, 맞는 주소면 Console의 CORS·DNS·인증서 오류 확인 |
| Console에 `blocked by CORS policy` | `ALLOWED_ORIGINS`와 브라우저 origin 불일치 | §5-1 수정 후 §5-5 |
| Console에 `Mixed Content` | `NEXT_PUBLIC_API_URL`이 `http://` | https 주소로 바꾸고 Redeploy |
| env를 고쳤는데 그대로 | `restart`로는 env를 다시 읽지 않음 | §5-5 `--force-recreate` |
| 점주 답변이 "반영 중"에서 넘어가지 않음 | `W_OWNER_ANSWER_WORKER_ENABLED` 꺼짐 | §5-4. 켜는 것은 담당자 합의 후 |

## 11. 남은 위험

- ~~`GET /preflight?deep=1`이 인증 없이 열려 있고 호출할 때마다 실제 LLM을 부른다.~~ 해결(이슈 #33): 운영자 로그인(`POST /ops/login`)과 운영자 토큰을 요구한다.
- ~~`docs/dev`의 일부 문서와 Web `/preflight` 화면의 안내 문구가 Railway를 운영 환경으로 가리킨다.~~ Web `/preflight` 화면은 해결(이슈 #33). `docs/dev`의 일부 문서는 남아 있다.
- AWS 무료 이용 기간이 끝나기 전에 다음 서버 위치를 정해야 한다. 옮길 때는 §8을 따른다.

## 12. 자동 배포

`main`에 머지되고 `R validation`이 성공하면 백업 → migration → 서버 배포 → health 확인이 자동으로 돈다.
GitHub Actions가 AWS에 **OIDC**로 접속하므로 저장소에 AWS 키를 두지 않는다. 서버에는 SSH를 열지 않고 SSM으로 명령한다.

### 12-1. S3 백업 버킷

1. S3 → Create bucket → 이름 `askbuddy-db-backups-<계정ID>` · 리전 `ap-northeast-2`
2. Block all public access 켜짐, Default encryption SSE-S3
3. 버킷 → Management → Create lifecycle rule → Prefix `db/` → Expire current versions after 30 days

### 12-2. GitHub OIDC 공급자

계정에 한 번만 만든다. IAM → Identity providers → Add provider → OpenID Connect

- Provider URL `https://token.actions.githubusercontent.com`
- Audience `sts.amazonaws.com`

### 12-3. 배포 역할 `askbuddy-github-deploy`

IAM → Roles → Create role → Web identity → 위 공급자, audience `sts.amazonaws.com` → 만든 뒤 Trust relationships를 아래로 교체한다.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::<계정ID>:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:2026-Unithon/AskBuddy:environment:api-production"
      }
    }
  }]
}
```

인라인 권한 정책:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ec2:ap-northeast-2:<계정ID>:instance/<인스턴스ID>",
        "arn:aws:ssm:ap-northeast-2::document/AWS-RunShellScript"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations", "ssm:CancelCommand"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::askbuddy-db-backups-<계정ID>/db/*"
    }
  ]
}
```

### 12-4. GitHub `api-production` 환경

저장소 Settings → Environments → New environment `api-production`

- Deployment branches: Selected branches → `main`
- Variables: `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`=`ap-northeast-2`, `EC2_INSTANCE_ID`, `DB_BACKUP_BUCKET`, `API_HEALTH_URL`=`https://api.askbuddy.kr/health`
- Secrets: `PROD_DB_URL` (Session pooler 연결 문자열)

### 12-5. 서버 1회 전환

기존 `~/deploy`에서 저장소의 `deploy/`로 옮긴다.

**순서.** `deploy/` 는 main 에 병합돼야 서버가 받아 올 수 있다. 그래서 아래 순서로 한다.

1. §12-4(`api-production` 변수·시크릿)를 **비워 둔 채** main 에 병합한다. Deploy API workflow 는 첫 단계(AWS 인증)에서 실패하고 백업·migration·서버는 건드리지 않는다.
2. 이 절의 전환을 한다. 옛 `~/deploy` 의 Caddy 가 80/443 을 잡고 있으므로 전환 전에 자동 배포가 돌면 안 된다.
3. §12-1~12-4 를 설정하고 Actions 에서 Deploy API 를 수동 실행(workflow_dispatch)해 처음부터 끝까지 확인한다.

사전 확인(서버, ubuntu 사용자).

```bash
git -C ~/askbuddy remote get-url origin   # https://github.com/2026-Unithon/AskBuddy.git (공개 저장소라 https 는 키가 필요 없다)
ls -l ~/askbuddy.env                      # 있어야 하고 권한은 600 (chmod 600 ~/askbuddy.env). 옛 스택이 다른 곳의 env 를 읽었다면 먼저 여기로 복사한다
id ubuntu                                 # groups 에 docker 포함
df -h /                                   # 여유 5GB 이상. 빌드 캐시가 루트 디스크를 채우면 SSM Agent 도 연결하지 못한다
```

`~/askbuddy` 가 저장소 clone 이 아니면 `git clone https://github.com/2026-Unithon/AskBuddy.git ~/askbuddy` 로 만든다.

전환. 중단 시간을 줄이려고 빌드를 먼저 끝내 둔다.

```bash
sudo su - ubuntu
cd ~/askbuddy && git fetch origin && git checkout --force origin/main
cd ~/askbuddy/deploy && docker compose build
cd ~/deploy && docker compose down
cd ~/askbuddy/deploy && docker compose up -d
docker compose logs -f caddy   # certificate obtained 확인
```

볼륨 이름이 바뀌어 HTTPS 인증서를 한 번 새로 받는다. 확인 후 `mv ~/deploy ~/deploy.old-<날짜>` 로 치워 두고, 며칠 문제가 없으면 지운다.
되돌릴 때는 `cd ~/askbuddy/deploy && docker compose down` 후 옛 폴더에서 `docker compose up -d`.

### 12-6. 동작 방식과 실패 대응

동작 순서와 실패 시 처리는 [설계 §3·§6](plan/API_AUTO_DEPLOY_DESIGN.md)을 따른다.
백업은 배포 역할이 아니라 **관리자 계정**으로 내려받는다.

```bash
aws s3 cp s3://<버킷>/db/<파일>.dump ./restore.dump
```

migration 규칙. `supabase db push` 는 원격에 적용된 최신 migration 보다 오래된 로컬 migration 이 있으면 거부한다.
순서가 뒤바뀐 채 병합된 migration 은 배포의 migration 단계에서 실패하며, 이때 서버는 이전 코드 그대로라 안전하다.
migration 파일의 타임스탬프를 최신으로 바꿔 다시 병합해 고친다.
