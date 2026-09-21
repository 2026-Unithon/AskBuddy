"""Persist explicit human review decisions in a private store directory.

No human decision is inferred. Passing no --decision initializes/reads the intake.
Records are immutable by queue and revision; concurrent conflicting writes fail.
"""
import argparse
import json
import os
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.team.review_intake import start_intake, checked_intake, record_decision, pending_questions


def save_revision(directory, state):
    name = 'intake-' + state['queue_hash'].split(':')[1] + f'-{state["revision"]:06d}.json'
    path = directory / name
    if path.resolve().parent != directory:
        raise ValueError('redirected intake path')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                prefix='.r-intake-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)  # Atomic publication without overwriting another reviewer.
        except FileExistsError:
            if json.loads(path.read_text(encoding='utf-8')) != state:
                raise ValueError('revision already exists; read latest before retrying') from None
    finally:
        if temporary is not None:
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', choices=('store-a', 'store-b'), required=True)
    parser.add_argument('--queue', required=True, help='filename inside this store r-review directory')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--decision', help='explicit human decision JSON filename in same directory')
    source.add_argument('--external-import', help='validated external AI proposal import filename')
    parser.add_argument('--external-package')
    parser.add_argument('--redactions', help='same private pseudonym map used for the external package')
    parser.add_argument('--meaning-id')
    parser.add_argument('--reviewer')
    parser.add_argument('--confirm-external-proposal', action='store_true',
        help='attest that this reviewer explicitly checked this individual AI proposal')
    parser.add_argument('--expected-hash')
    parser.add_argument('--request-id')
    args = parser.parse_args()
    confirmation = (args.external_package, args.meaning_id, args.reviewer, args.confirm_external_proposal)
    if args.external_import and not all(confirmation):
        parser.error('external import requires package, meaning ID, reviewer and explicit confirmation')
    if not args.external_import and (any(confirmation) or args.redactions):
        parser.error('external confirmation options require --external-import')
    root = (Path(__file__).resolve().parents[1] / 'eval/data' / args.store).resolve(strict=True)
    directory = (root / 'r-review').resolve(strict=True)
    if directory.parent != root:
        parser.error('review directory must stay within this store')
    def read(name):
        path = (directory / name).resolve(strict=True)
        if path.parent != directory:
            raise ValueError('input must stay within the store review directory')
        return json.loads(path.read_text(encoding='utf-8'))
    queue = read(args.queue)
    initial = start_intake(queue)
    prefix = 'intake-' + queue['queue_hash'].split(':')[1] + '-'
    paths = sorted(directory.glob(prefix + '*.json'))
    state = checked_intake(queue, read(paths[-1].name)) if paths else initial
    if args.decision or args.external_import:
        if not args.expected_hash or not args.request_id:
            parser.error('decision requires expected hash and request ID')
        if args.external_import:
            from app.team.real_data_review import prepare_dev_review
            from app.team.external_review import confirmed_decision
            review = prepare_dev_review(root.parent, store=args.store)
            decision = confirmed_decision(review, queue, read(args.external_package), read(args.external_import),
                meaning_id=args.meaning_id, reviewer=args.reviewer,
                redactions=read(args.redactions) if args.redactions else None)
        else:
            decision = read(args.decision)
        state = record_decision(queue, state, expected_hash=args.expected_hash,
            request_id=args.request_id, decision=decision)
    save_revision(directory, state)
    print(json.dumps(dict(store=args.store, revision=state['revision'], intake_hash=state['intake_hash'],
        reviewed=len(state['decisions']), remaining=len(queue['selected_meaning_ids'])-len(state['decisions']),
        next_meaning_ids=[r['meaning_id'] for r in pending_questions(queue, state)], evaluation_ready=False)))


if __name__ == '__main__': main()
