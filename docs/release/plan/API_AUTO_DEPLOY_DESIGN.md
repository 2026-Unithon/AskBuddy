# API 자동 배포 설계

2026-10-02 · 상태: 설계 확정, 구현 전. 구현 순서는 [API_AUTO_DEPLOY_PLAN.md](API_AUTO_DEPLOY_PLAN.md).

## 1. 목적

main에 push된 코드가 테스트를 통과하면, 사람이 서버에 접속하지 않아도 운영 API 서버에 반영되게 한다.
Web은 Vercel의 Git 연동이 이미 자동 배포하므로 범위에서 뺀다.

## 2. 결정 사항

| 항목 | 결정 | 결정한 사람 |
|---|---|---|
| 배포 조건 | `R validation` workflow가 main push에서 **성공**했을 때만 | 차준혁 |
| 운영 DB migration | 배포 때 **자동 적용**. 적용 전에 백업을 남긴다 | 차준혁 |
| 백업 위치 | AWS S3 비공개 버킷, 30일 뒤 자동 삭제 | 차준혁 |
| AWS 인증 | GitHub OIDC로 배포 전용 역할을 받는다. 장기 액세스 키를 저장하지 않는다 | AI 제안, 차준혁 승인 |
| 서버 접속 | SSM 명령. SSH(22번)는 열지 않는다 | 차준혁 (서버 구성 시 결정) |
| 서버 설정 파일 | `deploy/compose.yml`, `deploy/Caddyfile`을 저장소에서 관리. 비밀값 env 파일만 서버에 둔다 | AI 제안, 차준혁 승인 |
| GitHub 환경 이름 | `api-production`. 기존 `Production`(Vercel)·`askbuddy / production`(Railway)과 구분 | AI 제안 |

## 3. 흐름

```
main push
  └─ R validation (기존 테스트) ── 실패 → 배포 안 함
       └─ 성공 → deploy-api workflow (workflow_run)
            1. OIDC로 AWS 배포 역할 획득
            2. 운영 DB 백업 → S3 db/<UTC시각>-<커밋 앞 12자>.dump
            3. supabase db push (밀린 migration 적용, 없으면 무동작)
            4. SSM으로 서버에 배포 명령: 해당 커밋으로 맞춤 → docker compose up -d --build
            5. https://api.askbuddy.kr/health 확인
```

- 단계 하나라도 실패하면 거기서 멈추고 workflow를 실패로 표시한다.
- migration을 서버 배포보다 **먼저** 적용한다. 새 코드가 새 테이블을 기대하기 때문이다. migration이 실패하면 서버는 이전 코드로 남는다.
- 서버가 이전 코드로 돌고 있는 동안 새 migration이 먼저 들어간다. 현재 migration은 추가형(테이블·컬럼 추가, 제약 완화)이라 이전 코드를 깨지 않는다. **삭제형 migration은 이 가정을 깨므로** 별도 단계로 나눠 올린다(§8).
- 서버는 `workflow_run.head_sha`, 즉 **테스트를 통과한 바로 그 커밋**으로 맞춘다. 그 사이 main이 더 나아가도 테스트하지 않은 커밋을 올리지 않는다.
- 배포는 동시성 그룹 하나로 직렬화한다. 진행 중인 배포를 중간에 끊지 않는다. migration 중에 끊기면 DB가 어중간한 상태로 남을 수 있기 때문이다.
- 수동 재배포용 `workflow_dispatch`를 둔다. 수동 실행은 main의 현재 커밋을 배포한다.

## 4. 구성 요소

### 4-1. `.github/workflows/deploy-api.yml`

- 트리거: `workflow_run`(workflows: `R validation`, types: completed, branches: main) + `workflow_dispatch`
- 조건: `workflow_run`이면 `conclusion == 'success'` 그리고 `event == 'push'`
- 권한: `id-token: write`, `contents: read`
- 환경: `api-production` (비밀값·변수가 이 환경에만 있고, 배포 가능 브랜치는 main으로 제한)
- 동시성: `group: deploy-api-production`, `cancel-in-progress: false`

### 4-2. 백업

- Postgres 17 컨테이너의 `pg_dump`를 쓴다. 운영 DB가 17.6이라 버전이 낮은 도구는 거부된다.
- 대상: `public`, `supabase_migrations` 스키마. custom format(`-Fc`), `--no-owner --no-privileges`.
- `aws s3 cp ... --sse AES256`로 올린다. 덤프 파일은 runner에만 잠깐 있고 artifact로 남기지 않는다. 저장소가 공개라 artifact는 외부에서 내려받을 수 있다.
- 매 배포마다 백업한다. migration 유무를 출력 문자열로 판별하면 CLI 버전에 따라 깨지기 쉽고, 백업 크기가 1MB 미만이라 비용 차이가 없다.

### 4-3. migration

- `supabase/setup-cli` action으로 CLI를 설치한다. 버전은 로컬에서 검증한 2.115.0으로 고정한다.
- `supabase db push --db-url "$PROD_DB_URL"`. 연결은 Session pooler(IPv4)다.

### 4-4. 서버 배포 명령

SSM `AWS-RunShellScript`는 root로 실행된다. 저장소와 Docker 작업은 `ubuntu` 사용자로 실행한다.

```bash
runuser -l ubuntu -c '
  set -euo pipefail
  cd ~/askbuddy
  git fetch --quiet origin
  git checkout --quiet --force <SHA>
  cd deploy
  docker compose up -d --build --remove-orphans
  docker image prune -f
'
```

- `git checkout --force <SHA>`는 서버 저장소를 detached 상태로 해당 커밋에 맞춘다. 서버 저장소에서 직접 고친 내용은 덮어쓴다. 서버 전용 설정은 저장소 밖(`~/askbuddy.env`)에만 둔다.
- workflow는 `get-command-invocation`을 10초 간격으로 확인하며 최대 15분 기다린다. 2GB 서버의 첫 빌드가 몇 분 걸린다.
- 명령의 표준 출력·오류 끝부분을 workflow 로그에 남긴다. env 값은 출력하지 않는다.

### 4-5. 동작 확인

`curl -fsS https://api.askbuddy.kr/health`를 10초 간격으로 최대 12회 시도한다.
`/health`는 기동 여부만 알려 준다. DB·Storage·키 연결은 운영자가 `/preflight`로 확인한다.

### 4-6. `deploy/` 폴더

- `compose.yml`: api(빌드 컨텍스트 `../api`, env_file `/home/ubuntu/askbuddy.env`), caddy(80·443, 데이터 볼륨). 최상위 `name: askbuddy`로 프로젝트 이름을 고정해, 폴더 이름이 바뀌어도 같은 컨테이너·볼륨을 쓴다.
- `Caddyfile`: `api.askbuddy.kr` → `api:8000`. 도메인은 비밀값이 아니다.

## 5. 권한 범위

**AWS 배포 역할 `askbuddy-github-deploy`**
- 신뢰 정책: 발급자 `token.actions.githubusercontent.com`, `aud = sts.amazonaws.com`, `sub = repo:2026-Unithon/AskBuddy:environment:api-production`
- 허용:
  - `ssm:SendCommand`: 운영 인스턴스 ARN 하나와 `AWS-RunShellScript` 문서
  - `ssm:GetCommandInvocation`, `ssm:ListCommandInvocations`, `ssm:CancelCommand` (시간 초과 시 명령 취소)
  - `s3:PutObject`: 백업 버킷의 `db/*`
- 백업을 읽거나 지우는 권한은 주지 않는다. 배포 역할이 털려도 기존 백업을 지울 수 없다.

**GitHub `api-production` 환경**
- 배포 브랜치: `main`만
- 변수(vars): `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`(`ap-northeast-2`), `EC2_INSTANCE_ID`, `DB_BACKUP_BUCKET`, `API_HEALTH_URL`
- 비밀값(secrets): `PROD_DB_URL` (Session pooler 연결 문자열)

**S3 백업 버킷**
- 퍼블릭 액세스 전부 차단, 기본 암호화(SSE-S3)
- 수명 규칙: `db/` 접두사 객체 30일 뒤 만료

## 6. 실패와 복구

| 실패 지점 | 상태 | 복구 |
|---|---|---|
| 백업 | DB·서버 변경 없음 | 원인 확인 후 workflow 재실행 |
| migration | 서버는 이전 코드. DB는 실패한 migration 직전까지 적용됐을 수 있음 | `supabase migration list`로 상태 확인. 필요하면 S3 백업으로 복원(§7) |
| 서버 배포 | DB는 새 스키마. 서버는 빌드 실패 시 이전 컨테이너 유지 | SSM 출력 확인. 고친 커밋을 push하거나 이전 커밋으로 수동 재배포 |
| health | 컨테이너는 바뀌었으나 응답 없음 | 서버에서 `docker compose logs api` 확인 |

## 7. 백업 복원 (사람이 수행)

```bash
aws s3 cp s3://<버킷>/db/<파일>.dump ./restore.dump
pg_restore --list restore.dump            # 내용 확인
# 실제 복원은 운영 데이터를 덮어쓴다. 범위(테이블 단위/전체)를 먼저 정한다
```

복원은 이 workflow가 자동으로 하지 않는다.

## 8. 하지 않는 것과 남은 위험

- **자동 롤백 없음.** 실패하면 멈추고 알린다. 되돌리기는 사람이 판단한다.
- **삭제형 migration의 안전장치 없음.** 컬럼·테이블 삭제는 "코드에서 사용 중단 배포 → 다음 배포에서 삭제"로 나눠 올린다는 팀 규칙으로 막는다.
- **migration이 main에 들어가는 순간 운영 DB에 적용된다.** PR 리뷰가 운영 DB 변경의 마지막 관문이 된다.
- **배포 중 짧은 중단.** 컨테이너를 다시 만드는 몇 초 동안 API가 응답하지 않는다. 서버가 한 대라 무중단 배포는 범위 밖이다.
- **배포 실패 알림은 GitHub 기본 알림(이메일)뿐이다.**
- 실제 배포 성공 여부는 AWS·GitHub 설정을 마치고 main에 push해야만 확인할 수 있다.
