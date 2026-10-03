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
    if [[ "$line" == "DENIED" ]]; then echo "AccessDeniedException: not allowed" >&2; exit 254; fi
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

# 5) 조회 권한 오류 등은 대기하지 않고 바로 실패한다
setup_stubs; install_aws_stub
printf 'DENIED\nSuccess\n' > "$STUB_DIR/statuses"
out=$(run_deploy 900 "$SHA"); code=$?
assert_eq "$code" "1" "조회 오류 시 즉시 종료 코드 1"
assert_contains "$out" "AccessDeniedException" "조회 오류 내용을 출력"
assert_not_contains "$out" "서버 명령 상태" "오류 뒤 계속 기다리지 않음"

finish
