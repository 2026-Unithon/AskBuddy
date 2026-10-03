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
