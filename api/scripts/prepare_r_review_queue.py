"""Prepare private dev question coverage drafts; never label truth or read holdout."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.team.real_data_review import prepare_dev_review
from app.team.review_queue import prepare_review_queue


def write_once(directory,name,payload):
    target=directory/name
    if target.resolve().parent!=directory.resolve():raise ValueError('redirected output')
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8'))!=payload:raise ValueError('existing artifact differs')
        return
    with target.open('x',encoding='utf-8') as stream:
        json.dump(payload,stream,ensure_ascii=False,indent=2)
        stream.write('\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--store',choices=('store-a','store-b'),required=True)
    parser.add_argument('--limit',type=int,default=40)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/'eval/data'
    review=prepare_dev_review(root,store=args.store)
    queue=prepare_review_queue(review,limit=args.limit)
    directory=root/args.store/'r-review'
    if directory.resolve().parent!=(root/args.store).resolve():raise ValueError('redirected review directory')
    directory.mkdir(exist_ok=True)
    write_once(directory,'review-'+review['review_hash'].split(':')[1][:16]+'.json',review)
    write_once(directory,'queue-'+queue['queue_hash'].split(':')[1][:16]+'.json',queue)
    print(json.dumps(dict(store=args.store,queue_hash=queue['queue_hash'],draft_count=queue['draft_count'],
        distinct_question_draft_count=queue['distinct_question_draft_count'],reviewed_question_count=0,
        snapshot_coverage_verified=False,evaluation_ready=False)))


if __name__=='__main__':main()
