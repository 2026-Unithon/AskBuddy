"""Offline proposal replay; no provider, DB, automatic approval or pending mutation."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.reg.hybrid import Candidate, SearchResult
from app.learn.semantic_proposals import ComparisonQuestion, compare_proposal, proposal_input


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True, help='snapshot, candidates, question, user_turns, comparisons')
    parser.add_argument('--proposal', type=Path, help='omit to prepare provider input')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding='utf-8'))
    snapshot = PublishedKnowledgeSnapshot.model_validate(data['snapshot'])
    search = SearchResult(snapshot, data['index_revision'], tuple(Candidate(**c) for c in data['candidates']), data['question'])
    payload = proposal_input(search, store_id=int(snapshot.store_id), question=data['question'],
        user_turns=tuple(data.get('user_turns', [])),
        comparisons=tuple(ComparisonQuestion.model_validate(c) for c in data.get('comparisons', [])))
    if args.proposal:
        result = compare_proposal(search, payload=payload, raw=json.loads(args.proposal.read_text(encoding='utf-8')))
        output = {**asdict(result), 'proposal': result.proposal.model_dump(mode='json'),
            'baseline_plan': result.baseline_plan.model_dump(mode='json')}
    else:
        output = payload
    # The caller must use a private store-local output directory for real data.
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(status='REVIEW_REQUIRED' if args.proposal else 'INPUT_PREPARED', production_eligible=False)))


if __name__ == '__main__':
    main()
