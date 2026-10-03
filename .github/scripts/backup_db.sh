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
# 주소는 docker 인자가 아니라 환경변수로 넘겨 호스트의 명령 인자·로그에는 남지 않게 한다.
# 단 컨테이너 안에서는 pg_dump 의 인자로 보인다
docker run --rm -e PROD_DB_URL -v "$workdir:/out" postgres:17 \
  sh -c 'pg_dump "$PROD_DB_URL" --no-owner --no-privileges -Fc -n public -n supabase_migrations -f /out/db.dump'

if [[ ! -s "$workdir/db.dump" ]]; then
  echo "백업 파일이 비어 있어 중단한다" >&2
  exit 1
fi

aws s3 cp "$workdir/db.dump" "s3://${bucket}/${key}" --sse AES256 --only-show-errors
echo "backup: s3://${bucket}/${key}"
