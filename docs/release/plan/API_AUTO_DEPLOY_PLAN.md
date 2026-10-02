# API 자동 배포 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** main push가 `R validation`을 통과하면 운영 DB 백업 → migration 적용 → EC2 서버 재배포 → health 확인이 자동으로 실행되게 한다.

**Architecture:** GitHub Actions `workflow_run`이 OIDC로 AWS 배포 역할을 받는다. 백업은 runner에서 Postgres 17 컨테이너로 떠서 S3 비공개 버킷에 올린다. migration은 Supabase CLI로 적용한다. 서버 배포는 SSM 명령으로 서버 저장소를 테스트된 커밋에 맞춘 뒤 `deploy/remote_deploy.sh`를 실행한다. 셸 로직은 스크립트 파일로 분리하고, `aws`·`docker`를 가짜 명령으로 바꿔 끼운 bash 테스트로 검증한다.

**Tech Stack:** GitHub Actions, aws-actions/configure-aws-credentials@v4, supabase/setup-cli@v1, AWS SSM·S3, Docker Compose, Caddy 2, bash, shellcheck, actionlint

**Spec:** [API_AUTO_DEPLOY_DESIGN.md](API_AUTO_DEPLOY_DESIGN.md)

## Global Constraints

- GitHub 환경 이름은 `api-production`이다. 기존 `Production`, `Preview`, `askbuddy / production`을 쓰지 않는다.
- 트리거 workflow 이름은 정확히 `R validation`이다.
- 배포 커밋은 `github.event.workflow_run.head_sha`. 수동 실행은 `github.sha`이고 `refs/heads/main`에서만 허용한다.
- 동시성 그룹은 `deploy-api-production`, `cancel-in-progress: false`.
- 리전 `ap-northeast-2`. Supabase CLI 버전 `2.115.0`. 백업 도구 이미지 `postgres:17`.
- 백업 키 형식: `db/<UTC YYYYMMDDTHHMMSSZ>-<커밋 앞 12자>.dump`, 업로드 시 `--sse AES256`.
- 백업 파일을 artifact로 올리지 않는다. 저장소가 공개라 외부에서 내려받을 수 있다.
- SSM 대기 최대 900초, 확인 간격 10초. health 확인은 10초 간격 최대 12회.
- `PROD_DB_URL`을 로그에 출력하지 않는다. 스크립트에서 `set -x`를 쓰지 않는다.
- 서버 저장소 경로 `/home/ubuntu/askbuddy`, env 파일 `/home/ubuntu/askbuddy.env`, 실행 사용자 `ubuntu`.
- 셸 스크립트 주석은 한국어로 쓴다(CLAUDE.md).
- **커밋은 사용자가 지시할 때만 한다.** 각 Task 끝의 "변경 확인" 단계는 `git status`로 범위만 확인한다.

## Review Focus

1. **테스트 도중 main이 더 나아간 경우**: 테스트를 통과한 `head_sha`만 배포하고, 그 뒤 커밋을 섞지 않아야 한다. → Task 4 workflow의 `DEPLOY_SHA`와 checkout `ref`, Task 2 SHA 형식 검사 테스트
2. **SSM 명령이 끝나지 않는 경우**(`Pending`/`InProgress` 지속, 호출 직후 `InvocationDoesNotExist`): 15분 뒤 명령을 취소하고 실패해야 한다. → Task 2 시간 초과·조회 오류 테스트
3. **PR·포크·실패한 테스트에서 온 `workflow_run`**: 배포하지 않아야 한다. → Task 4 `if` 조건과 actionlint, 수동 확인 항목
4. **DB 주소 노출**: 백업 실패 시에도 주소가 로그에 남지 않아야 한다. → Task 3 "주소 미출력" 테스트
5. **빈 백업 파일**: `pg_dump`가 0바이트를 남기면 migration으로 넘어가지 않아야 한다. → Task 3 빈 파일 테스트

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `deploy/compose.yml` | 운영 서버의 api·caddy 컨테이너 정의. 프로젝트 이름 `askbuddy` 고정 |
| `deploy/Caddyfile` | `api.askbuddy.kr` HTTPS 종단과 api 프록시 |
| `deploy/remote_deploy.sh` | 서버에서 실행. 현재 체크아웃으로 컨테이너 재빌드 |
| `.github/scripts/ssm_deploy.sh` | runner에서 실행. SSM 명령 전송·대기·출력 |
| `.github/scripts/backup_db.sh` | runner에서 실행. 운영 DB 덤프 → S3 |
| `.github/scripts/tests/lib.sh` | 가짜 명령 설치·단언 함수 |
| `.github/scripts/tests/ssm_deploy_test.sh` | ssm_deploy.sh 테스트 |
| `.github/scripts/tests/backup_db_test.sh` | backup_db.sh 테스트 |
| `.github/workflows/deploy-api.yml` | 자동 배포 workflow |
| `.github/workflows/deploy-checks.yml` | PR에서 배포 스크립트·workflow 검사 |
| `docs/release/DEPLOY_ACCESS_SETUP.md` | 자동 배포 절, AWS·GitHub 설정, 서버 1회 전환 절차 |

---

### Task 0: 검사 도구 설치

**Files:** 없음

- [ ] **Step 1: 설치**

Run: `brew install shellcheck actionlint`
Expected: 두 명령 모두 `which`로 찾아진다.

---

### Task 1: 서버 설정 파일을 저장소로

**Files:**
- Create: `deploy/compose.yml`
- Create: `deploy/Caddyfile`
- Create: `deploy/remote_deploy.sh`

**Interfaces:**
- Produces: `deploy/remote_deploy.sh` (인자 없음, 스크립트 위치 기준으로 compose 실행). Task 2의 SSM 명령이 `bash deploy/remote_deploy.sh`로 부른다.
- Produces: 환경변수 `ASKBUDDY_ENV_FILE`(기본 `/home/ubuntu/askbuddy.env`). 로컬 검증에서 다른 경로를 넣을 때 쓴다.

- [ ] **Step 1: 실패하는 검증 실행**

Run: `ASKBUDDY_ENV_FILE=/dev/null docker compose -f deploy/compose.yml config -q`
Expected: FAIL (`deploy/compose.yml` 없음)

- [ ] **Step 2: `deploy/compose.yml` 작성**

```yaml
# 운영 API 서버 구성. 비밀값은 저장소 밖 env 파일에만 둔다.
# 최상위 name 으로 프로젝트 이름을 고정해 폴더 위치가 바뀌어도 같은 컨테이너·볼륨을 쓴다.
name: askbuddy

services:
  api:
    build: ../api
    env_file: ${ASKBUDDY_ENV_FILE:-/home/ubuntu/askbuddy.env}
    environment:
      PORT: "8000"
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

  caddy:
    image: caddy:2
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    restart: unless-stopped
    depends_on:
      - api

volumes:
  caddy_data:
  caddy_config:
```

- [ ] **Step 3: `deploy/Caddyfile` 작성**

```
# HTTPS 인증서는 Caddy 가 자동 발급·갱신한다. 80·443 이 열려 있어야 한다.
api.askbuddy.kr {
    reverse_proxy api:8000
}
```

- [ ] **Step 4: `deploy/remote_deploy.sh` 작성**

```bash
#!/usr/bin/env bash
# 서버에서 ubuntu 사용자로 실행된다. 지금 체크아웃된 커밋으로 API 를 다시 띄운다.
# 커밋을 맞추는 일은 호출하는 쪽(SSM 명령)이 먼저 끝낸다.
set -euo pipefail

cd "$(dirname "$0")"
docker compose up -d --build --remove-orphans
# 오래된 이미지가 작은 디스크를 채우지 않게 정리한다
docker image prune -f >/dev/null
docker compose ps
```

- [ ] **Step 5: 검증 통과 확인**

Run: `ASKBUDDY_ENV_FILE=/dev/null docker compose -f deploy/compose.yml config -q && shellcheck -S warning deploy/remote_deploy.sh && echo OK`
Expected: `OK`

- [ ] **Step 6: 변경 확인**

Run: `git status --short deploy/`
Expected: 위 세 파일만 새로 생김

---

### Task 2: SSM 배포 명령 스크립트

**Files:**
- Create: `.github/scripts/tests/lib.sh`
- Create: `.github/scripts/tests/ssm_deploy_test.sh`
- Create: `.github/scripts/ssm_deploy.sh`

**Interfaces:**
- Consumes: Task 1 `deploy/remote_deploy.sh`
- Produces: `bash .github/scripts/ssm_deploy.sh <instance-id> <40자 커밋 SHA>`. 환경변수 `SSM_TIMEOUT_SEC`(기본 900), `SSM_POLL_SEC`(기본 10). 성공 0, 실패 1, 인자 오류 2.
- Produces: `.github/scripts/tests/lib.sh`의 `setup_stubs`, `assert_eq`, `assert_contains`, `assert_not_contains`, `finish`. Task 3이 같은 함수를 쓴다.

- [ ] **Step 1: 테스트 공용 함수 작성 `.github/scripts/tests/lib.sh`**

```bash
#!/usr/bin/env bash
# 배포 스크립트 테스트 공용 함수. 실제 aws·docker 대신 가짜 명령을 PATH 앞에 둔다.
set -uo pipefail

FAILURES=0
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 가짜 명령 폴더를 만들고 PATH 앞에 둔다. 호출 기록은 $STUB_LOG 에 쌓인다.
setup_stubs() {
  STUB_DIR="$(mktemp -d)"
  STUB_LOG="$STUB_DIR/calls.log"
  : > "$STUB_LOG"
  export STUB_DIR STUB_LOG
  export PATH="$STUB_DIR:$PATH"
}

# 이름과 본문으로 가짜 명령을 만든다
make_stub() {
  local name="$1" body="$2"
  printf '#!/usr/bin/env bash\necho "%s $*" >> "$STUB_LOG"\n%s\n' "$name" "$body" > "$STUB_DIR/$name"
  chmod +x "$STUB_DIR/$name"
}

assert_eq() {
  if [[ "$1" != "$2" ]]; then
    echo "FAIL: $3 (기대: '$2', 실제: '$1')"; FAILURES=$((FAILURES + 1))
  fi
}

assert_contains() {
  if [[ "$1" != *"$2"* ]]; then
    echo "FAIL: $3 ('$2' 가 없음)"; FAILURES=$((FAILURES + 1))
  fi
}

assert_not_contains() {
  if [[ "$1" == *"$2"* ]]; then
    echo "FAIL: $3 ('$2' 가 있으면 안 됨)"; FAILURES=$((FAILURES + 1))
  fi
}

finish() {
  if (( FAILURES > 0 )); then echo "$FAILURES 건 실패"; exit 1; fi
  echo "PASS"
}
```

- [ ] **Step 2: 실패하는 테스트 작성 `.github/scripts/tests/ssm_deploy_test.sh`**

```bash
#!/usr/bin/env bash
# ssm_deploy.sh 테스트. aws 는 가짜 명령이고, 상태 순서는 $STUB_DIR/statuses 에서 한 줄씩 꺼낸다.
source "$(dirname "$0")/lib.sh"

SHA="0123456789abcdef0123456789abcdef01234567"

# get-command-invocation 이 statuses 파일의 다음 줄을 돌려주는 가짜 aws
install_aws_stub() {
  make_stub aws '
case "$*" in
  *"send-command"*) echo "cmd-123" ;;
  *"--query Status"*)
    line=$(head -n1 "$STUB_DIR/statuses"); sed -i.bak 1d "$STUB_DIR/statuses"
    if [[ "$line" == "MISSING" ]]; then echo "InvocationDoesNotExist" >&2; exit 254; fi
    echo "$line" ;;
  *"StandardOutputContent"*) echo "server output tail" ;;
  *"cancel-command"*) : ;;
esac'
}

run_deploy() {
  SSM_POLL_SEC=0 SSM_TIMEOUT_SEC="${1:-900}" bash "$SCRIPTS_DIR/ssm_deploy.sh" i-abc "$2" 2>&1
}

# 1) 조회 직후 기록 없음 → 진행 중 → 성공
setup_stubs; install_aws_stub
printf 'MISSING\nInProgress\nSuccess\n' > "$STUB_DIR/statuses"
out=$(run_deploy 900 "$SHA"); code=$?
assert_eq "$code" "0" "성공 시 종료 코드 0"
assert_contains "$(cat "$STUB_LOG")" "git checkout --quiet --force $SHA" "테스트된 커밋으로 맞춤"
assert_contains "$(cat "$STUB_LOG")" "bash deploy/remote_deploy.sh" "서버 배포 스크립트 실행"
assert_contains "$(cat "$STUB_LOG")" "executionTimeout" "서버 명령 실행 시간 상한 전달"
assert_contains "$out" "server output tail" "서버 출력을 로그에 남김"

# 2) 서버 명령 실패
setup_stubs; install_aws_stub
printf 'InProgress\nFailed\n' > "$STUB_DIR/statuses"
run_deploy 900 "$SHA" >/dev/null; code=$?
assert_eq "$code" "1" "서버 명령 실패 시 종료 코드 1"

# 3) 끝나지 않음 → 시간 초과 → 취소
setup_stubs; install_aws_stub
yes InProgress | head -n 50 > "$STUB_DIR/statuses"
out=$(run_deploy 0 "$SHA"); code=$?
assert_eq "$code" "1" "시간 초과 시 종료 코드 1"
assert_contains "$(cat "$STUB_LOG")" "cancel-command" "시간 초과 시 명령 취소"
assert_contains "$out" "시간 초과" "시간 초과 안내"

# 4) 잘못된 커밋 SHA 는 서버에 보내지 않는다
setup_stubs; install_aws_stub
: > "$STUB_DIR/statuses"
run_deploy 900 "main; rm -rf /" >/dev/null; code=$?
assert_eq "$code" "2" "잘못된 SHA 거부"
assert_not_contains "$(cat "$STUB_LOG")" "send-command" "잘못된 SHA 는 전송하지 않음"

finish
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `bash .github/scripts/tests/ssm_deploy_test.sh`
Expected: `FAIL` 줄들과 `N 건 실패` (스크립트 없음)

- [ ] **Step 4: `.github/scripts/ssm_deploy.sh` 작성**

```bash
#!/usr/bin/env bash
# SSM 으로 운영 서버에 배포 명령을 보내고 끝날 때까지 기다린다.
# 사용: ssm_deploy.sh <instance-id> <40자 커밋 SHA>
# 환경: SSM_TIMEOUT_SEC(기본 900) SSM_POLL_SEC(기본 10)
set -euo pipefail

instance_id="${1:?instance-id 가 필요하다}"
sha="${2:?커밋 SHA 가 필요하다}"
timeout_sec="${SSM_TIMEOUT_SEC:-900}"
poll_sec="${SSM_POLL_SEC:-10}"

# 원격 셸에 그대로 들어가는 값이라 형식을 먼저 확인한다
if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "잘못된 커밋 SHA: $sha" >&2
  exit 2
fi

# SSM 은 root 로 실행된다. 저장소·Docker 작업은 ubuntu 사용자로 한다
remote="runuser -l ubuntu -c 'set -euo pipefail; cd ~/askbuddy && git fetch --quiet origin && git checkout --quiet --force ${sha} && bash deploy/remote_deploy.sh'"
params=$(jq -nc --arg c "$remote" --arg t "$timeout_sec" '{commands: [$c], executionTimeout: [$t]}')

command_id=$(aws ssm send-command \
  --instance-ids "$instance_id" \
  --document-name AWS-RunShellScript \
  --comment "deploy ${sha:0:12}" \
  --parameters "$params" \
  --query Command.CommandId --output text)
echo "SSM command: $command_id"

deadline=$((SECONDS + timeout_sec))
status="Pending"
while true; do
  # 전송 직후에는 호출 기록이 아직 없을 수 있다. 그때는 대기 중으로 본다
  status=$(aws ssm get-command-invocation \
    --command-id "$command_id" --instance-id "$instance_id" \
    --query Status --output text 2>/dev/null) || status="Pending"
  case "$status" in
    Success|Failed|Cancelled|TimedOut) break ;;
  esac
  if (( SECONDS >= deadline )); then
    echo "시간 초과: ${timeout_sec}초 안에 서버 명령이 끝나지 않아 취소한다" >&2
    aws ssm cancel-command --command-id "$command_id" --instance-ids "$instance_id" || true
    exit 1
  fi
  sleep "$poll_sec"
done

# 서버 출력 끝부분만 남긴다. env 값은 서버 스크립트가 출력하지 않는다
aws ssm get-command-invocation \
  --command-id "$command_id" --instance-id "$instance_id" \
  --query '[StandardOutputContent, StandardErrorContent]' --output text | tail -n 80

echo "서버 명령 상태: $status"
[[ "$status" == "Success" ]] || exit 1
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `bash .github/scripts/tests/ssm_deploy_test.sh && shellcheck -S warning .github/scripts/ssm_deploy.sh .github/scripts/tests/*.sh`
Expected: `PASS`, shellcheck 경고 없음

- [ ] **Step 6: 변경 확인**

Run: `git status --short .github/scripts/`

---

### Task 3: DB 백업 스크립트

**Files:**
- Create: `.github/scripts/tests/backup_db_test.sh`
- Create: `.github/scripts/backup_db.sh`

**Interfaces:**
- Consumes: Task 2 `.github/scripts/tests/lib.sh`
- Produces: `PROD_DB_URL=... bash .github/scripts/backup_db.sh <bucket> <40자 커밋 SHA>`. 성공 시 마지막 줄 `backup: s3://<bucket>/db/<키>`. 실패 1, 인자 오류 2.

- [ ] **Step 1: 실패하는 테스트 작성**

```bash
#!/usr/bin/env bash
# backup_db.sh 테스트. docker 는 -v 로 받은 폴더에 덤프 파일을 만드는 가짜 명령이다.
source "$(dirname "$0")/lib.sh"

SHA="0123456789abcdef0123456789abcdef01234567"
SECRET_URL="postgresql://postgres.ref:s3cretPW@host:5432/postgres"

# DUMP_BYTES 만큼 덤프 파일을 만드는 가짜 docker
install_docker_stub() {
  make_stub docker '
dir=$(printf "%s\n" "$@" | grep -m1 ":/out" | cut -d: -f1)
head -c "${DUMP_BYTES:-100}" /dev/zero > "$dir/db.dump"'
}

# 1) 정상: 키 형식, 암호화, 주소 미출력
setup_stubs; install_docker_stub; make_stub aws ':'
out=$(DUMP_BYTES=100 PROD_DB_URL="$SECRET_URL" bash "$SCRIPTS_DIR/backup_db.sh" my-bucket "$SHA" 2>&1); code=$?
assert_eq "$code" "0" "정상 백업 종료 코드 0"
assert_contains "$(cat "$STUB_LOG")" "s3 cp" "S3 업로드"
assert_contains "$(cat "$STUB_LOG")" "--sse AES256" "서버 측 암호화"
assert_contains "$out" "backup: s3://my-bucket/db/" "백업 위치 출력"
assert_contains "$out" "-${SHA:0:12}.dump" "키에 커밋 앞 12자"
[[ "$out" =~ db/[0-9]{8}T[0-9]{6}Z- ]] || { echo "FAIL: UTC 시각 형식"; FAILURES=$((FAILURES + 1)); }
assert_not_contains "$out" "s3cretPW" "출력에 DB 비밀번호 없음"
assert_not_contains "$(cat "$STUB_LOG")" "s3cretPW" "명령 인자에 DB 주소를 넣지 않음"

# 2) 빈 덤프는 실패하고 업로드하지 않는다
setup_stubs; install_docker_stub; make_stub aws ':'
DUMP_BYTES=0 PROD_DB_URL="$SECRET_URL" bash "$SCRIPTS_DIR/backup_db.sh" my-bucket "$SHA" >/dev/null 2>&1; code=$?
assert_eq "$code" "1" "빈 덤프는 실패"
assert_not_contains "$(cat "$STUB_LOG")" "s3 cp" "빈 덤프는 업로드하지 않음"

# 3) DB 주소가 없으면 실패
setup_stubs; install_docker_stub; make_stub aws ':'
env -u PROD_DB_URL bash "$SCRIPTS_DIR/backup_db.sh" my-bucket "$SHA" >/dev/null 2>&1; code=$?
assert_eq "$code" "2" "PROD_DB_URL 없으면 인자 오류"

# 4) pg_dump 실패가 전파된다
setup_stubs; make_stub docker 'exit 1'; make_stub aws ':'
PROD_DB_URL="$SECRET_URL" bash "$SCRIPTS_DIR/backup_db.sh" my-bucket "$SHA" >/dev/null 2>&1; code=$?
assert_eq "$code" "1" "pg_dump 실패 시 종료 코드 1"

finish
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `bash .github/scripts/tests/backup_db_test.sh`
Expected: `N 건 실패`

- [ ] **Step 3: `.github/scripts/backup_db.sh` 작성**

```bash
#!/usr/bin/env bash
# 운영 DB 를 덤프해 S3 비공개 버킷에 올린다. 덤프 파일은 runner 에만 잠깐 둔다.
# 사용: PROD_DB_URL=... backup_db.sh <bucket> <40자 커밋 SHA>
set -euo pipefail

bucket="${1:-}"
sha="${2:-}"
if [[ -z "$bucket" || ! "$sha" =~ ^[0-9a-f]{40}$ || -z "${PROD_DB_URL:-}" ]]; then
  echo "사용: PROD_DB_URL=... backup_db.sh <bucket> <40자 커밋 SHA>" >&2
  exit 2
fi

key="db/$(date -u +%Y%m%dT%H%M%SZ)-${sha:0:12}.dump"
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

# 운영 DB 가 Postgres 17 이라 같은 버전 도구를 쓴다.
# 주소는 명령 인자가 아니라 환경변수로 넘겨 로그·프로세스 목록에 남지 않게 한다
docker run --rm -e PROD_DB_URL -v "$workdir:/out" postgres:17 \
  sh -c 'pg_dump "$PROD_DB_URL" --no-owner --no-privileges -Fc -n public -n supabase_migrations -f /out/db.dump'

if [[ ! -s "$workdir/db.dump" ]]; then
  echo "백업 파일이 비어 있어 중단한다" >&2
  exit 1
fi

aws s3 cp "$workdir/db.dump" "s3://${bucket}/${key}" --sse AES256 --only-show-errors
echo "backup: s3://${bucket}/${key}"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `bash .github/scripts/tests/backup_db_test.sh && shellcheck -S warning .github/scripts/backup_db.sh .github/scripts/tests/backup_db_test.sh`
Expected: `PASS`, 경고 없음

- [ ] **Step 5: 실제 덤프 한 번 확인 (로컬, 운영 DB 읽기만)**

Run:
```bash
docker run --rm -e PROD_DB_URL="$(cat ~/.askbuddy_prod_db_url)" postgres:17 \
  sh -c 'pg_dump "$PROD_DB_URL" --no-owner --no-privileges -Fc -n public -n supabase_migrations | wc -c'
```
Expected: 0보다 큰 바이트 수. 실패하면 이미지 버전·연결 문자열을 확인한다. S3 업로드는 하지 않는다.

- [ ] **Step 6: 변경 확인**

Run: `git status --short .github/scripts/`

---

### Task 4: 배포 workflow와 PR 검사 workflow

**Files:**
- Create: `.github/workflows/deploy-api.yml`
- Create: `.github/workflows/deploy-checks.yml`

**Interfaces:**
- Consumes: Task 2 `ssm_deploy.sh <instance-id> <sha>`, Task 3 `backup_db.sh <bucket> <sha>`
- Consumes (GitHub `api-production`): vars `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `EC2_INSTANCE_ID`, `DB_BACKUP_BUCKET`, `API_HEALTH_URL`; secret `PROD_DB_URL`

- [ ] **Step 1: 실패하는 검사 실행**

Run: `actionlint .github/workflows/deploy-api.yml`
Expected: FAIL (파일 없음)

- [ ] **Step 2: `.github/workflows/deploy-api.yml` 작성**

```yaml
name: Deploy API
on:
  workflow_run:
    workflows: ["R validation"]
    types: [completed]
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  id-token: write

# 배포는 하나씩. migration 도중에 끊기지 않게 진행 중인 배포를 취소하지 않는다
concurrency:
  group: deploy-api-production
  cancel-in-progress: false

jobs:
  deploy:
    # main push 에서 테스트가 성공했을 때, 또는 main 에서 수동 실행했을 때만
    if: >-
      (github.event_name == 'workflow_run'
        && github.event.workflow_run.conclusion == 'success'
        && github.event.workflow_run.event == 'push')
      || (github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main')
    runs-on: ubuntu-latest
    timeout-minutes: 30
    environment: api-production
    env:
      # 테스트를 통과한 바로 그 커밋. 그 사이 main 이 더 나아가도 섞지 않는다
      DEPLOY_SHA: ${{ github.event.workflow_run.head_sha || github.sha }}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ env.DEPLOY_SHA }}

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}

      - name: 운영 DB 백업
        env:
          PROD_DB_URL: ${{ secrets.PROD_DB_URL }}
          DB_BACKUP_BUCKET: ${{ vars.DB_BACKUP_BUCKET }}
        run: bash .github/scripts/backup_db.sh "$DB_BACKUP_BUCKET" "$DEPLOY_SHA"

      - uses: supabase/setup-cli@v1
        with:
          version: 2.115.0

      - name: migration 적용
        env:
          PROD_DB_URL: ${{ secrets.PROD_DB_URL }}
        run: supabase db push --db-url "$PROD_DB_URL" --yes

      - name: 서버 배포
        env:
          EC2_INSTANCE_ID: ${{ vars.EC2_INSTANCE_ID }}
        run: bash .github/scripts/ssm_deploy.sh "$EC2_INSTANCE_ID" "$DEPLOY_SHA"

      - name: health 확인
        env:
          API_HEALTH_URL: ${{ vars.API_HEALTH_URL }}
        run: |
          for attempt in $(seq 1 12); do
            if curl -fsS "$API_HEALTH_URL"; then exit 0; fi
            echo "health 대기 ${attempt}/12"
            sleep 10
          done
          echo "health 확인 실패" >&2
          exit 1
```

- [ ] **Step 3: `.github/workflows/deploy-checks.yml` 작성**

```yaml
name: Deploy checks
on:
  pull_request:
    paths:
      - "deploy/**"
      - ".github/scripts/**"
      - ".github/workflows/deploy-*.yml"
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - name: 셸 스크립트 검사
        run: shellcheck -S warning deploy/remote_deploy.sh .github/scripts/*.sh .github/scripts/tests/*.sh
      - name: 배포 스크립트 테스트
        run: |
          bash .github/scripts/tests/ssm_deploy_test.sh
          bash .github/scripts/tests/backup_db_test.sh
      - name: compose 문법
        run: ASKBUDDY_ENV_FILE=/dev/null docker compose -f deploy/compose.yml config -q
      - name: workflow 문법
        run: |
          bash <(curl -fsSL https://raw.githubusercontent.com/rhysd/actionlint/v1.7.7/scripts/download-actionlint.bash) 1.7.7
          ./actionlint -color
```

- [ ] **Step 4: 검사 통과 확인**

Run: `actionlint .github/workflows/deploy-api.yml .github/workflows/deploy-checks.yml && echo OK`
Expected: `OK`

- [ ] **Step 5: 조건 수동 점검**

`deploy-api.yml`의 `if`를 다시 읽고 아래가 모두 배포되지 않는지 확인한다.
- `R validation`이 실패·취소된 main push
- `R validation`이 PR(`event == 'pull_request'`)에서 성공
- main이 아닌 브랜치에서 수동 실행

- [ ] **Step 6: 변경 확인**

Run: `git status --short .github/workflows/`
Expected: 두 파일만 새로 생김. `r-validation.yml`은 바뀌지 않음

---

### Task 5: 운영 문서

**Files:**
- Modify: `docs/release/DEPLOY_ACCESS_SETUP.md` (§5-5, §6, §8 뒤에 새 절 추가)
- Modify: `docs/release/README.md` (설계·계획 문서 줄 추가)
- Modify: `docs/release/plan/API_AUTO_DEPLOY_DESIGN.md` §5 (`ssm:CancelCommand` 추가)

- [ ] **Step 1: 설계 문서 권한 보완**

§5 허용 목록의 SSM 줄을 `ssm:SendCommand`, `ssm:GetCommandInvocation`, `ssm:ListCommandInvocations`, `ssm:CancelCommand`로 고친다. Task 2의 시간 초과 처리가 `cancel-command`를 부른다.

- [ ] **Step 2: `DEPLOY_ACCESS_SETUP.md`에 "12. 자동 배포" 절 추가**

다음 하위 절을 그대로 쓴다.

**12-1. S3 백업 버킷**
1. S3 → Create bucket → 이름 `askbuddy-db-backups-<계정ID>` · 리전 `ap-northeast-2`
2. Block all public access 켜짐, Default encryption SSE-S3
3. 버킷 → Management → Create lifecycle rule → Prefix `db/` → Expire current versions after 30 days

**12-2. GitHub OIDC 공급자** (계정에 한 번)
IAM → Identity providers → Add provider → OpenID Connect
- Provider URL `https://token.actions.githubusercontent.com`
- Audience `sts.amazonaws.com`

**12-3. 배포 역할 `askbuddy-github-deploy`**
IAM → Roles → Create role → Web identity → 위 공급자, audience `sts.amazonaws.com` → 만든 뒤 Trust relationships를 아래로 교체:
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

**12-4. GitHub `api-production` 환경**
저장소 Settings → Environments → New environment `api-production`
- Deployment branches: Selected branches → `main`
- Variables: `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`=`ap-northeast-2`, `EC2_INSTANCE_ID`, `DB_BACKUP_BUCKET`, `API_HEALTH_URL`=`https://api.askbuddy.kr/health`
- Secrets: `PROD_DB_URL` (Session pooler 연결 문자열)

**12-5. 서버 1회 전환** (기존 `~/deploy` → 저장소 `deploy/`)
```bash
sudo su - ubuntu
cd ~/deploy && docker compose down
cd ~/askbuddy && git fetch origin && git checkout --force origin/main
cd deploy && docker compose up -d --build
docker compose logs -f caddy   # certificate obtained 확인
```
볼륨 이름이 바뀌어 HTTPS 인증서를 한 번 새로 받는다. 확인 후 `rm -rf ~/deploy`.

**12-6. 동작 방식과 실패 대응**
[설계 §3·§6](plan/API_AUTO_DEPLOY_DESIGN.md)을 링크하고, 백업 내려받기 명령을 적는다:
`aws s3 cp s3://<버킷>/db/<파일>.dump ./restore.dump` (배포 역할이 아니라 관리자 계정으로)

- [ ] **Step 3: §8 표의 "옛 서버 즉시 중지" 아래에 한 줄 추가**

"자동 배포를 쓰면 새 서버로 옮긴 뒤 `api-production`의 `EC2_INSTANCE_ID`와 배포 역할 정책의 인스턴스 ARN을 바꾼다."

- [ ] **Step 4: `docs/release/README.md` 표에 두 줄 추가**

```
| [plan/API_AUTO_DEPLOY_DESIGN.md](plan/API_AUTO_DEPLOY_DESIGN.md) | API 자동 배포 설계: 백업·migration·서버 배포 순서와 권한 |
| [plan/API_AUTO_DEPLOY_PLAN.md](plan/API_AUTO_DEPLOY_PLAN.md) | API 자동 배포 구현 계획 |
```

- [ ] **Step 5: 변경 확인**

Run: `git diff --stat docs/release`

---

### Task 6: 최종 검증

**Files:** 없음

- [ ] **Step 1: 전체 로컬 검사**

Run:
```bash
shellcheck -S warning deploy/remote_deploy.sh .github/scripts/*.sh .github/scripts/tests/*.sh \
  && bash .github/scripts/tests/ssm_deploy_test.sh \
  && bash .github/scripts/tests/backup_db_test.sh \
  && ASKBUDDY_ENV_FILE=/dev/null docker compose -f deploy/compose.yml config -q \
  && actionlint && echo ALL_OK
```
Expected: `ALL_OK`

- [ ] **Step 2: 기존 workflow 무변경 확인**

Run: `git diff --quiet HEAD -- .github/workflows/r-validation.yml && echo UNCHANGED`
Expected: `UNCHANGED`

- [ ] **Step 3: 보고**

로컬에서 검증한 것과 사용자 설정 후에만 확인 가능한 것을 나눠 보고한다.
- 로컬 확인: 스크립트 테스트, shellcheck, actionlint, compose 문법, 운영 DB 덤프 가능 여부
- 미확인: OIDC 역할 획득, S3 업로드, SSM 실제 실행, 첫 자동 배포. Task 5의 12-1~12-5를 마치고 main에 push해야 확인된다.
