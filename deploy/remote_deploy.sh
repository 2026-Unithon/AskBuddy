#!/usr/bin/env bash
# 서버에서 ubuntu 사용자로 실행된다. 지금 체크아웃된 커밋으로 API 를 다시 띄운다.
# 커밋을 맞추는 일은 호출하는 쪽(SSM 명령)이 먼저 끝낸다.
set -euo pipefail

cd "$(dirname "$0")"
docker compose up -d --build --remove-orphans
# 오래된 이미지가 작은 디스크를 채우지 않게 정리한다
docker image prune -f >/dev/null
# 빌드 캐시도 일주일 지난 것은 지운다
docker builder prune -f --filter until=168h >/dev/null || true
docker compose ps
