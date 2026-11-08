#!/usr/bin/env bash
# Run on the AskBuddy API host: bash deploy/store9-gemini.sh enable|disable|status
set -euo pipefail
umask 077
cd "$(dirname "$0")"
envfile=${ASKBUDDY_ENV_FILE:-/home/ubuntu/askbuddy.env}
test "$envfile" = /home/ubuntu/askbuddy.env && test -f "$envfile" && test ! -L "$envfile" || exit 1
op=${1:-status}
if [ "$op" = status ]; then
  docker compose exec -T api python -c "from app.config import get_settings; s=get_settings(); print('enabled:',s.r_general_semantics_enabled,'store:',s.r_general_semantics_store_id,'model:',s.gemini_model)"
  exit
fi
[[ "$op" = enable || "$op" = disable ]] || exit 2
token=$(curl -fsS --max-time 3 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')
instance=$(curl -fsS --max-time 3 -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/instance-id)
test "$instance" = i-0a83bc49c38c9f36c && test "$(id -un)" = ubuntu || exit 1
unset token
exec 9>/home/ubuntu/.askbuddy-gemini-rollout.lock
flock -n 9 || { echo 'Another rollout is in progress'; exit 1; }
docker compose config --quiet
backup=$(mktemp /home/ubuntu/askbuddy.env.gemini.XXXXXXXX)
cp -- "$envfile" "$backup"
bundle=$(mktemp)
trap 'rm -f -- "$bundle"' EXIT
if [ "$op" = enable ]; then
  # This only reads the active index and generates a release; no model is called.
  docker compose exec -T api python -m scripts.chat_gemini_pilot prepare >"$bundle"
  sudo install -d -o ubuntu -g ubuntu -m 0750 /home/ubuntu/askbuddy-releases
fi
rollback() {
  trap - ERR
  cp -- "$backup" "$envfile"
  docker compose up -d --no-build --no-deps --force-recreate api
  echo 'Original configuration restored.' >&2
}
trap rollback ERR
python3 - "$envfile" "$op" "$bundle" <<'PY'
import json,os,re,sys,tempfile
from pathlib import Path
p=Path(sys.argv[1]); updates={'R_GENERAL_SEMANTICS_ENABLED':'false'}
def write(path,body):
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as f:
        f.write(body); f.flush(); os.fsync(f.fileno())
    os.replace(f.name,path)
if sys.argv[2]=='enable':
    obj=json.loads(Path(sys.argv[3]).read_text())
    pin=obj['pin']; assert re.fullmatch(r'sha256:[0-9a-f]{64}',pin)
    name='store9-'+pin[7:]+'.json'
    write(Path('/home/ubuntu/askbuddy-releases')/name,json.dumps(obj['release'],ensure_ascii=False))
    updates.update(R_GENERAL_SEMANTICS_ENABLED='true',R_GENERAL_SEMANTICS_STORE_ID='9',
        R_GENERAL_SEMANTICS_PATH='/run/askbuddy/releases/'+name,R_GENERAL_SEMANTICS_HASH=pin)
lines=[line for line in p.read_text().splitlines()
       if not any(re.match(r'^\s*(?:export\s+)?'+k+r'\s*=',line) for k in updates)]
write(p,'\n'.join([*lines,*(k+'='+v for k,v in updates.items())])+'\n')
PY
docker compose up -d --no-build --no-deps --force-recreate api
healthy=0
for _ in {1..12}; do
  if curl -fsS --max-time 3 https://api.askbuddy.kr/health >/dev/null; then healthy=1; break; fi
  sleep 2
done
test "$healthy" = 1
if [ "$op" = enable ]; then
  docker compose exec -T api python -m scripts.chat_gemini_pilot verify
else
  docker compose exec -T api python -c 'from app.config import get_settings; assert not get_settings().r_general_semantics_enabled'
fi
trap - ERR
echo "Verified $op; configuration backup: $backup"
