"""오프라인 pool/판정/선택적 순위에서 검색 지표를 계산한다."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.team.retrieval_review import review_retrieval


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=review_retrieval(**json.loads(args.input.read_text(encoding='utf-8')))
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write('\n')


if __name__=='__main__': main()
