"""Prepare private dev fact labels for R review, without manufacturing approval.

No DB, model, source transcription or holdout access. A W fact label is not an
R question/action judgment, and TEST is not owner confirmation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.contracts.hashing import digest


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    return 'sha256:' + hasher.hexdigest()


def _within(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError('source path required')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('missing or out-of-store input')
    return path


def prepare_dev_review(data_root: Path, *, store: str) -> dict:
    if store not in ('store-a', 'store-b'):
        raise ValueError('only the two dev stores are permitted')
    root = data_root.resolve()
    directory = (root / store).resolve()
    if directory.parent != root or directory.name != store:
        raise ValueError('redirected store directory')
    manifest_path = _within(directory, 'manifest.json')
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode('utf-8-sig'))
    # Before reading truth or any source, even when the folder has a dev name.
    if manifest.get('split') != 'dev':
        raise ValueError('holdout or unknown split is sealed')
    truth_path = _within(directory, 'truth/facts.json')
    truth_bytes = truth_path.read_bytes()
    truth = json.loads(truth_bytes.decode('utf-8-sig'))
    if not manifest.get('store_slug') or truth.get('store_slug') != manifest['store_slug']:
        raise ValueError('manifest/truth store mismatch')
    sources = {}
    for source in manifest.get('sources', []):
        key = source.get('source_key')
        if not isinstance(key, str) or not key or key in sources:
            raise ValueError('missing or duplicate source ID')
        path = _within(directory, source.get('file'))
        sources[key] = dict(type=source.get('type'), sha256=_hash_file(path), bytes=path.stat().st_size)
    rows = truth.get('facts')
    if not isinstance(rows, list) or not rows:
        raise ValueError('nonempty fact labels required')
    seen = set()
    drafts = []
    for fact in rows:
        fid = fact.get('fact_id')
        if not isinstance(fid, str) or not fid.strip() or fid in seen:
            raise ValueError('missing or duplicate fact ID')
        seen.add(fid)
        if fact.get('source_key') not in sources:
            raise ValueError('unknown source ID')
        if any(not isinstance(fact.get(key), str) or not fact[key].strip()
               for key in ('subject', 'attribute', 'value')) or type(fact.get('must_have')) is not bool:
            raise ValueError('invalid fact label fields')
        variant = fact.get('variant')
        if variant is not None and not isinstance(variant, str):
            raise ValueError('unsupported legacy variant type')
        locator = fact.get('locator')
        if not isinstance(locator, dict) or not locator.get('type'):
            raise ValueError('source locator required')
        # Source fact identity, never a fabricated PublishedKnowledgeSnapshot fact ID.
        meaning_id = 'r-meaning-' + digest(dict(store=store, source_fact_id=fid)).split(':')[-1][:24]
        drafts.append(dict(meaning_id=meaning_id, source_fact_id=fid, source_fact_hash=digest(fact),
            source_label=fact, question_draft=' '.join(x for x in (variant, fact['subject'], fact['attribute']) if x) + '은?',
            review_status='UNREVIEWED', question=None, expected_action=None,
            must_have=fact['must_have'], applicability=dict(status='UNREVIEWED',
                variant_label=variant, conditions=None, exceptions=None, reviewer=None, reason=None),
            required_meaning_ids=[meaning_id], forbidden_claims=None,
            snapshot_mapping=None, reviewer=None, reason=None))
    confirmation = truth.get('owner_confirmed')
    label_status = ('OWNER_CONFIRMED' if confirmation is True else
                    'TEAM_TEST' if confirmation == 'TEST' else 'UNCONFIRMED')
    result = dict(schema_version='r_dev_review/v1', store=store, split='dev',
        manifest_hash='sha256:' + hashlib.sha256(manifest_bytes).hexdigest(),
        truth_hash='sha256:' + hashlib.sha256(truth_bytes).hexdigest(), sources=sources,
        source_label_status=label_status, source_reviewer=truth.get('judged_by'),
        source_reviewed_at=truth.get('judged_at'), cases=drafts,
        summary=dict(fact_count=len(drafts), must_have_count=sum(row['must_have'] for row in drafts),
            missing_variant_count=sum(not row['source_label'].get('variant') for row in drafts),
            question_reviewed_count=0, snapshot_mapped_count=0),
        blockers=['R_QUESTION_ACTION_REVIEW_REQUIRED','APPLICABILITY_REVIEW_REQUIRED',
                  'APPROVED_SNAPSHOT_AND_MAPPING_REQUIRED'],
        evaluation_ready=False, production_promotion=False)
    if label_status == 'UNCONFIRMED' or not truth.get('judged_by') or not truth.get('judged_at'):
        result['blockers'].append('SOURCE_TRUTH_REVIEW_REQUIRED')
    result['review_hash'] = digest(result)
    return result
