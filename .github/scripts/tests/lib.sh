#!/usr/bin/env bash
# 배포 스크립트 테스트 공용 함수. 실제 aws·docker 대신 가짜 명령을 PATH 앞에 둔다.
set -uo pipefail

FAILURES=0
# shellcheck disable=SC2034  # 이 파일을 source 하는 테스트가 쓴다
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
