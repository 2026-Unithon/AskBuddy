"""Parameter Store 값을 docker compose env 파일 줄로 바꾼다(계획 9 Task 8).

사용: aws ssm get-parameters-by-path --path /askbuddy/prod/ --with-decryption --output json \
        | python3 render_env.py > askbuddy.env

표준 라이브러리만 쓴다(서버에 따로 설치하지 않는다). 값은 출력에만 쓰고 로그에 남기지 않는다.
"""
from __future__ import annotations

import json
import re
import sys

PREFIX = "/askbuddy/prod/"
KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def render(parameters: list[dict], prefix: str) -> str:
    """`Parameters` 배열 → 이름순 `KEY=value` 줄. 잘못된 이름·값이면 ValueError(값은 오류 글에 넣지 않는다)."""
    if not parameters:
        raise ValueError("파라미터가 하나도 없다. 경로와 권한을 확인한다")
    lines: dict[str, str] = {}
    for item in parameters:
        name = item["Name"]
        if not name.startswith(prefix):
            raise ValueError(f"접두 밖의 이름: {name}")
        key = name[len(prefix):]
        if not KEY.fullmatch(key):
            raise ValueError(f"env 이름 모양이 아니다: {name}")
        value = item["Value"]
        if "\n" in value or "\r" in value:
            raise ValueError(f"값에 줄바꿈이 있다: {key}")
        # 값의 # 은 그대로 둔다. 이 줄에 주석을 덧붙이지 않는다(불변식 10)
        lines[key] = value
    return "".join(f"{key}={lines[key]}\n" for key in sorted(lines))


def main() -> int:
    data = json.load(sys.stdin)
    sys.stdout.write(render(data.get("Parameters", []), PREFIX))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
