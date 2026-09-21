"""Build/import a private external-session package without model/network calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.team.real_data_review import prepare_dev_review
from app.team.external_review import build_package, import_result
from scripts.prepare_r_review_queue import write_once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', choices=('store-a', 'store-b'), required=True)
    parser.add_argument('--queue', required=True, help='filename inside the store r-review directory')
    parser.add_argument('--package', help='package filename; required for result import')
    parser.add_argument('--result', help='external session JSON filename in the same private directory')
    parser.add_argument('--redactions', help='private original-to-pseudonym JSON filename; never sent out')
    args = parser.parse_args()
    root = (Path(__file__).resolve().parents[1] / 'eval/data').resolve(strict=True)
    store = (root / args.store).resolve(strict=True)
    directory = (store / 'r-review').resolve(strict=True)
    if store.parent != root or directory.parent != store:
        parser.error('redirected private directory')
    def read(name):
        path = (directory / name).resolve(strict=True)
        if path.parent != directory:
            raise ValueError('input must stay inside store review directory')
        return json.loads(path.read_text(encoding='utf-8-sig'))
    review = prepare_dev_review(root, store=args.store)
    queue = read(args.queue)
    redactions = read(args.redactions) if args.redactions else None
    if args.result:
        if not args.package:
            parser.error('--result requires --package')
        document = import_result(review, queue, read(args.package), read(args.result), redactions=redactions)
        name = 'external-import-' + document['import_hash'].split(':')[1] + '.json'
    else:
        if args.package:
            parser.error('--package is only used with --result')
        document = build_package(review, queue, redactions=redactions)
        name = 'external-package-' + document['package_hash'].split(':')[1] + '.json'
    write_once(directory, name, document)
    print(json.dumps(dict(store=args.store, output=name, human_reviewed=0,
        evaluation_ready=False, production_promotion=False,
        external_calls=0, status='AI_PROPOSAL_IMPORTED' if args.result else 'PACKAGE_READY')))


if __name__ == '__main__':
    main()
