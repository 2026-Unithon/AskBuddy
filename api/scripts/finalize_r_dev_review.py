"""Import explicit human judgments and an approved snapshot from private dev data."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.team.real_data_review import prepare_dev_review, _within
from app.team.reviewed_manifest import finalize_review


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--store',choices=('store-a','store-b'),required=True)
    parser.add_argument('--store-id',type=int,required=True)
    parser.add_argument('--truth-version',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/'eval'/'data'
    # Re-read manifest, truth and hashes of all source files. A changed input
    # invalidates the submitted review hash before it can become a campaign.
    review=prepare_dev_review(root,store=args.store)
    directory=(root/args.store).resolve()
    submitted=json.loads(_within(directory,'r-review/judgments.json').read_text('utf-8'))
    snapshot=json.loads(_within(directory,'r-review/approved_snapshot.json').read_text('utf-8'))
    result=finalize_review(review,review_hash=submitted['review_hash'],judgments=submitted['judgments'],
        snapshot=snapshot,store_id=args.store_id,truth_version=args.truth_version,
        selected_meaning_ids=submitted.get('selected_meaning_ids'),selection_reason=submitted.get('selection_reason'))
    output=directory/'r-review'/('manifest-'+result['artifact_hash'].split(':')[1][:16]+'.json')
    with output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps(dict(store=args.store,question_count=len(result['manifest']['cases']),
        source_label_status=result['source_label_status'],production_promotion=False)))


if __name__=='__main__': main()
