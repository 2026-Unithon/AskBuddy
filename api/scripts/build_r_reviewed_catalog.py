"""Offline compile of explicit human judgments and applicability; no calls or deployment."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.reg.hybrid import SearchResult, Candidate
from app.team.reviewed_catalog import build_catalog


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True,help='private bundle: acceptance_reference and items')
    parser.add_argument('--output',type=Path,required=True,help='new private catalog file; never overwritten')
    args=parser.parse_args()
    raw=json.loads(args.input.read_text(encoding='utf-8'))
    items=[]
    for item in raw['items']:
        source=item['search']
        search=SearchResult(PublishedKnowledgeSnapshot.model_validate(source['snapshot']),source['index_revision'],
            tuple(Candidate(**c) for c in source['candidates']),item['observation']['input']['question'])
        items.append(dict(item,search=search))
    data,content_hash=build_catalog(items,acceptance_reference=raw['acceptance_reference'])
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(data,stream,ensure_ascii=False,indent=2)
    print(json.dumps(dict(status='VALIDATED_NOT_INSTALLED',catalog_hash=content_hash,entries=len(data['entries']))))


if __name__=='__main__':main()
