"""Create a private, unreviewed R draft from the two dev stores. Never reads holdout."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.team.real_data_review import prepare_dev_review


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', choices=('store-a', 'store-b'), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'eval' / 'data'
    report = prepare_dev_review(root, store=args.store)
    directory = root / args.store / 'r-review'
    if directory.resolve().parent != (root / args.store).resolve():
        raise ValueError('redirected review directory')
    directory.mkdir(exist_ok=True)
    output = directory / ('review-' + report['review_hash'].split(':')[1][:16] + '.json')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    # No subjects, assertions, reviewers, original filenames or question text in stdout.
    print(json.dumps(dict(store=args.store, **report['summary'],
        source_label_status=report['source_label_status'], evaluation_ready=False)))


if __name__ == '__main__':
    main()
