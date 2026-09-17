"""실자료·API·DB 호출 없이 C0 fixture의 기존 읽기 출력 기록."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.team.baseline import record_baseline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/contracts/v1"
    report = asyncio.run(record_baseline(fixture))
    # 기존 동결 파일을 조용히 덮지 않는다. 새 실행은 새 경로에 기록한다.
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({k: report[k] for k in ("scope", "case_count", "question_count", "error_count")}, ensure_ascii=False))
    return 1 if report["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
