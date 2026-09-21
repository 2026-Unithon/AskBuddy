"""Offline, metadata-only check. Does not load .env or contact hosting."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.team.logging_evidence import check_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--service', required=True)
    parser.add_argument('--environment', required=True)
    parser.add_argument('--deployed-commit', required=True)
    args = parser.parse_args()
    raw = json.loads(args.evidence.read_text(encoding='utf-8'))
    result = check_evidence(raw, service=args.service, environment=args.environment, deployed_commit=args.deployed_commit)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
