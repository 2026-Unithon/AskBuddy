"""Import manually observed aliases with provenance; never scrape or auto-approve."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.team.lexicon_review import collect_lexicon_review


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True, help='entries and collection_reference JSON')
    parser.add_argument('--store-directory', type=Path, required=True, help='private directory for this store')
    args = parser.parse_args()
    root = args.store_directory.resolve(strict=True)
    source = args.input.resolve(strict=True)
    if not source.is_relative_to(root):
        parser.error('input must remain within its private store directory')
    data = json.loads(source.read_text(encoding='utf-8'))
    review = collect_lexicon_review(root, data['entries'], collection_reference=data['collection_reference'])
    print(json.dumps(dict(status=review['status'], unique_count=review['unique_count'], review_hash=review['review_hash'])))


if __name__ == '__main__': main()
