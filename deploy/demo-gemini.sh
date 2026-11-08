#!/usr/bin/env bash
# Once-only demo rollout for the requested EC2 instance; no new IAM privileges.
set -euo pipefail
cd "$(dirname "$0")"
marker=/home/ubuntu/askbuddy-releases/.demo-rollout-20261108-applied
case "${1:-status}" in
  status) exec bash store9-gemini.sh status ;;
  enable|refresh) bash store9-gemini.sh enable-demo; touch "$marker" ;;
  disable) bash store9-gemini.sh disable; touch "$marker" ;;
  apply-once)
    # A later deployment must not enable an old experiment or undo a manual stop.
    if [[ "$(date -u +%Y%m%d)" != 20261108 && "$(date -u +%Y%m%d)" != 20261109 ]]; then exit 0; fi
    token=$(curl -fsS --max-time 2 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60') || { echo 'Demo rollout skipped: no EC2 metadata'; exit 0; }
    target=$(curl -fsS --max-time 2 -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/instance-id) || { echo 'Demo rollout skipped: instance identity unavailable'; exit 0; }
    [[ "$target" = i-0a83bc49c38c9f36c ]] || { echo 'Demo rollout skipped: different instance'; exit 0; }
    if [[ -e "$marker" ]]; then
      if [[ ! -e "$marker.query-recovery" ]]; then
        state=$(docker compose exec -T api python -m scripts.chat_gemini_pilot repair-state)
        if [[ "$state" = REBIND ]]; then bash store9-gemini.sh rebind-demo; fi
        touch "$marker.query-recovery"
      fi
      echo 'Demo rollout already handled'; exit 0
    fi
    bash store9-gemini.sh enable-demo
    touch "$marker"
    ;;
  *) echo 'Expected enable, refresh, disable, status, or apply-once' >&2; exit 2 ;;
esac
