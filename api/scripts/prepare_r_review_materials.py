"""Create private human worksheets and term-review templates; never approve truth."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.team.real_data_review import prepare_dev_review
from app.team.review_queue import prepare_review_queue
from app.contracts.hashing import digest
from prepare_r_review_queue import write_once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', choices=('store-a', 'store-b'), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'eval/data'
    review = prepare_dev_review(root, store=args.store)
    queue = prepare_review_queue(review, limit=40)
    directory = root / args.store / 'r-review'
    if directory.resolve().parent != (root / args.store).resolve():
        raise ValueError('redirected private review directory')
    directory.mkdir(exist_ok=True)
    terms = {}
    for row in review['cases']:
        label = row['source_label']
        term = label['subject']
        entry = terms.setdefault(term, dict(term=term, source_fact_ids=[], observed_variants=[],
            variant_kind=None, source_reference=None, collected_at=None, reviewer=None,
            approval_version=None, status='UNREVIEWED'))
        entry['source_fact_ids'].append(row['source_fact_id'])
    vocabulary = dict(schema_version='r_observed_term_review/v1', store=args.store,
        review_hash=review['review_hash'], entries=list(terms.values()),
        policy='No invented aliases/STT errors; each observed variant needs source, reviewer and approved version.',
        search_expansion_decision='DEFER_PENDING_PAIRED_EVIDENCE', production_eligible=False)
    write_once(directory, 'term-review-' + digest(vocabulary).split(':')[1][:16] + '.json', vocabulary)
    lines = ['# R 질문·용어 사람 검토', '',
        '이 파일은 매장 내부 검토용입니다. 원본 자료와 함께 확인하며 외부에 공유하지 않습니다.', '',
        '각 문항의 기대 행동, 필수 사실/RAW, 금지 주장, 규격·조건·예외와 이유를 queue JSON에 기록하세요.',
        'ANSWER는 현재 승인 snapshot의 revision/RAW 매핑이 필요합니다. 미확정은 null로 남깁니다.',
        '용어 파일에는 실제 관찰한 별칭·오타·STT 변형과 출처를 기록하세요. 유사해 보인다는 이유로 만들지 않습니다.',
        '이 문서를 채워도 자동 승인되지 않습니다. finalize_r_dev_review.py의 완전성 검사를 거칩니다.', '']
    for index, row in enumerate(queue['source_rows'], 1):
        label = row['source_label']
        lines.extend([f'## {index}. {row["meaning_id"]}', '',
            f'- 질문 초안: {row["question_draft"]}',
            f'- 사실 라벨: {label["subject"]} / {label["attribute"]} / {label["value"]}',
            f'- 원본 사실 ID: {row["source_fact_id"]}',
            '- 확인: 기대 행동 / 필수 근거 / 금지 주장 / 규격 / 조건 / 예외 / 검토자·이유', ''])
    target = directory / ('worksheet-' + queue['queue_hash'].split(':')[1][:16] + '.md')
    content = '\n'.join(lines) + '\n'
    if target.resolve().parent != directory.resolve():
        raise ValueError('redirected worksheet')
    if target.exists():
        if target.read_text(encoding='utf-8') != content:
            raise ValueError('existing worksheet differs; preserve human edits')
    else:
        with target.open('x', encoding='utf-8') as stream:
            stream.write(content)
    print(json.dumps(dict(store=args.store, question_drafts=queue['draft_count'],
        term_review_rows=len(terms), reviewed=0, evaluation_ready=False)))


if __name__ == '__main__':
    main()
