"""Read private JSONL observations and optional exact-output human judgments."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.team.semantic_review import semantic_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--observations', type=Path, required=True)
    parser.add_argument('--judgments', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.observations.read_text(encoding='utf-8').splitlines() if line.strip()]
    labels = json.loads(args.judgments.read_text(encoding='utf-8')) if args.judgments else []
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(semantic_report(rows, labels), stream, ensure_ascii=False, indent=2)
    print('REVIEW_REQUIRED')


if __name__ == '__main__': main()
