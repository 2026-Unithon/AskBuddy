"""Human judgments bind to exact shadow rows; missing judgments never count as success."""
from typing import Literal
from math import ceil, isfinite
from statistics import median
from pydantic import Field, StrictBool
from app.contracts.common import Contract
from app.contracts.hashing import digest
from app.contracts.answer import AnswerPlan
from app.learn.semantic_proposals import SemanticProposal


class SemanticJudgment(Contract):
    row_hash: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    reviewer: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)
    expected_action: Literal['ANSWER', 'CLARIFY', 'ESCALATE', 'REFUSE', 'SAFE_ROUTE']
    semantic_correct: StrictBool
    false_block: StrictBool
    false_merge: StrictBool
    citation_error: StrictBool


def semantic_report(rows, judgments=()):
    if not rows or len(rows) > 10000:
        raise ValueError('bounded nonempty observations required')
    hashes = set()
    scopes = set()
    for row in rows:
        key = row['row_hash']
        if key in hashes or key != digest({k: v for k, v in row.items() if k != 'row_hash'}):
            raise ValueError('duplicate or changed observation')
        if row['schema_version'] != 'r_semantic_observation/v1' or row['production_eligible'] is not False:
            raise ValueError('invalid observation authority')
        if row['status'] not in ('REVIEW_REQUIRED', 'FAILED', 'TIMEOUT', 'SKIPPED'):
            raise ValueError('invalid status')
        if row['provider_mode'] not in ('LIVE', 'SYNTHETIC') or not row['source_hashes']:
            raise ValueError('provider/source evidence required')
        payload = row['input']
        if (payload['input_hash'] != row['input_hash']
                or digest({k: v for k, v in payload.items() if k != 'input_hash'}) != row['input_hash']
                or payload['store_id'] != row['store_id'] or payload['snapshot_hash'] != row['snapshot_hash']):
            raise ValueError('review input binding mismatch')
        elapsed = row['elapsed_ms']
        if type(elapsed) not in (float, int) or not isfinite(elapsed) or elapsed < 0:
            raise ValueError('invalid latency')
        baseline = AnswerPlan.model_validate(row['baseline_plan'])
        if row['status'] == 'REVIEW_REQUIRED':
            proposal = SemanticProposal.model_validate(row['proposal'])
            if (proposal.input_hash != row['input_hash'] or proposal.snapshot_hash != row['snapshot_hash']
                    or proposal.plan.snapshot_id != baseline.snapshot_id
                    or proposal.plan.knowledge_revision != baseline.knowledge_revision):
                raise ValueError('proposal observation binding mismatch')
        elif row['proposal'] is not None:
            raise ValueError('failed observation cannot contain proposal')
        scopes.add((row['store_id'], row['snapshot_hash'], row['provider_mode'], digest(row['source_hashes'])))
        hashes.add(key)
    if len(scopes) != 1:
        raise ValueError('store/snapshot/provider/source drift requires separate reports')
    labels = {}
    for raw in judgments:
        label = SemanticJudgment.model_validate(raw)
        if label.row_hash not in hashes or label.row_hash in labels or not label.reviewer.strip() or not label.reason.strip():
            raise ValueError('foreign, duplicate, or unattributed judgment')
        labels[label.row_hash] = label
    reviewed = list(labels.values())
    latencies = sorted(row['elapsed_ms'] for row in rows)
    return dict(schema_version='r_semantic_report/v1', input_hash=digest(rows), total=len(rows),
        reviewed=len(reviewed), unreviewed=len(rows)-len(reviewed),
        failed=sum(row['status'] in ('FAILED', 'TIMEOUT') for row in rows),
        wrong_semantics=sum(not label.semantic_correct for label in reviewed),
        false_blocks=sum(label.false_block for label in reviewed),
        false_merges=sum(label.false_merge for label in reviewed),
        citation_errors=sum(label.citation_error for label in reviewed),
        action_errors=sum(row['proposal'] is not None and
            row['proposal']['plan']['action'] != labels[row['row_hash']].expected_action
            for row in rows if row['row_hash'] in labels),
        latency_p50_ms=median(latencies), latency_p95_ms=latencies[ceil(len(latencies)*.95)-1], latency_max_ms=latencies[-1],
        cost=None, cost_status='REQUIRES_USAGE_LEDGER', production_eligible=False,
        gate='REQUIRES_HUMAN_TRUTH_AND_PAIRED_CAMPAIGN')
