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

errfile=$(mktemp)
trap 'rm -f "$errfile"' EXIT
deadline=$((SECONDS + timeout_sec))
status="Pending"
while true; do
  # 전송 직후에는 호출 기록이 아직 없을 수 있다(InvocationDoesNotExist). 그때만 대기 중으로 본다.
  # 권한·네트워크 같은 다른 오류는 오류 내용을 출력하고 바로 실패한다
  if ! status=$(aws ssm get-command-invocation \
    --command-id "$command_id" --instance-id "$instance_id" \
    --query Status --output text 2>"$errfile"); then
    if grep -q InvocationDoesNotExist "$errfile"; then
      status="Pending"
    else
      echo "상태 조회 실패:" >&2
      cat "$errfile" >&2
      exit 1
    fi
  fi
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
  --query '[StandardOutputContent, StandardErrorContent]' --output text | tail -n 80 || true

echo "서버 명령 상태: $status"
[[ "$status" == "Success" ]] || exit 1
