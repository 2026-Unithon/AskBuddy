"""Report a local synthetic/private grouping evaluation; no model or DB calls."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.team.grouping_evaluation import evaluate_grouping


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=json.loads(args.input.read_text('utf-8'))
    report=evaluate_grouping(data['cases'],data['assignments'],data['judgments'])
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps({key:report[key] for key in ('question_count','pair_count','unjudged_pair_count','precision','recall','scope_violations')}))


if __name__=='__main__':main()
