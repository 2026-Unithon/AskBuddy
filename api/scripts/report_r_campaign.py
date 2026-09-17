"""파일에 고정된 반복 실행을 대조한다. API/모델/운영 설정 변경 없음."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.team.v2_campaign import compare_campaign


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    bundle=json.loads(args.bundle.read_text('utf-8'))
    report=compare_campaign(**bundle)
    with args.output.open('x',encoding='utf-8') as out:
        json.dump(report,out,ensure_ascii=False,indent=2)
        out.write('\n')
    print(json.dumps(dict(eligible=report['gate']['eligible'],blocking_reasons=report['gate']['blocking_reasons'])))


if __name__=='__main__':main()
