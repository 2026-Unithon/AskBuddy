"""저장된 v2 평가 실행과 출력에 연결된 검토 파일을 보고한다. API/모델 호출 없음."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.team.v2_evaluation import build_v2_report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--judgments',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=build_v2_report(json.loads(args.run.read_text('utf-8')),
        json.loads(args.judgments.read_text('utf-8')) if args.judgments else None)
    with args.output.open('x',encoding='utf-8') as output:
        json.dump(report,output,ensure_ascii=False,indent=2)
        output.write('\n')
    print(json.dumps(dict(question_count=report['question_count'],unjudged_answers=len(report['unjudged_answer_ids'])),ensure_ascii=False))


if __name__=='__main__':main()
