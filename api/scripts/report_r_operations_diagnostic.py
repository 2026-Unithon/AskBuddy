"""Apply output-bound review to the core-only operations diagnostic; never infer live accuracy."""
import argparse
import hashlib
import json
from pathlib import Path
from run_r_operations_diagnostic import dump, write_report


def main(args):
    report=json.loads(args.run.read_text('utf-8'))
    review=json.loads(args.review.read_text('utf-8'))
    assert review['run_sha256']==hashlib.sha256(args.run.read_bytes()).hexdigest()
    labels={(v['case_id'],v['turn_number']):v for v in review['judgments']}
    assert len(labels)==len(review['judgments'])
    used=set()
    for case in report['rows']:
        for n,t in enumerate(case['turns'],1):
            key=(case['case_id'],n)
            if key in labels:
                label=labels[key]
                assert label['response_sha256']==hashlib.sha256(json.dumps(t['observed']['response'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                assert label['reviewer'].strip() and label['reason'].strip()
                assert type(label['semantic_correct']) is bool
                t['semantic_correct']=label['semantic_correct']
                t['verdict_reason']=label['reason']
                used.add(key)
    assert used==set(labels)
    turns=[t for case in report['rows'] for t in case['turns']]
    summary=report['summary']
    summary['unreviewed']=sum(t['semantic_correct'] is None for t in turns)
    summary['turn_passes']=sum(t['semantic_correct'] is True for t in turns)
    summary['single_passes']=sum(all(t['semantic_correct'] is True for t in c['turns']) for c in report['rows'] if c['kind']=='단일 질문')
    report['review']=review
    report['session_accuracy']=None
    dump(args.run.parent/'run.json',report)
    write_report(args.run.parent,report)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--review',type=Path,required=True)
    main(parser.parse_args())
