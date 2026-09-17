"""오프라인 승인 snapshot과 후보 목록으로 검토용 JSON을 만든다."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.team.retrieval_pool import build_retrieval_pool


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = build_retrieval_pool(**json.loads(Path(args.input).read_text(encoding='utf-8')))
    with Path(args.output).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
