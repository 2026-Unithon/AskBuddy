#!/usr/bin/env bash
# 서버에서 ubuntu 사용자로 실행된다. 지금 체크아웃된 커밋으로 API 를 다시 띄운다.
# 커밋을 맞추는 일은 호출하는 쪽(SSM 명령)이 먼저 끝낸다.
set -euo pipefail

cd "$(dirname "$0")"
# 비밀값은 Parameter Store 가 정본이다. 배포 때마다 env 파일을 새로 만든다
ENV_FILE="${ASKBUDDY_ENV_FILE:-/home/ubuntu/askbuddy.env}"
if [ "${ASKBUDDY_ENV_FROM_SSM:-0}" = "1" ]; then
  umask 077
  aws ssm get-parameters-by-path --path /askbuddy/prod/ --with-decryption --output json \
    | python3 render_env.py > "${ENV_FILE}.new"
  mv "${ENV_FILE}.new" "$ENV_FILE"
fi
docker compose up -d --build --remove-orphans
# 비공개 Storage 버킷(sources·avatars)을 맞춘다. 이미 있으면 넘어가므로 매번 돌려도 된다(2026-11-09: avatars 가 운영에 없었다)
docker compose exec -T api python scripts/init_storage.py
bash demo-gemini.sh apply-once
# 오래된 이미지가 작은 디스크를 채우지 않게 정리한다
docker image prune -f >/dev/null
# 빌드 캐시도 일주일 지난 것은 지운다
docker builder prune -f --filter until=168h >/dev/null || true
docker compose ps
