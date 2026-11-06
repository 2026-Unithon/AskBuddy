"""대상 이름은 현재 DB가 아닌 승인 snapshot의 사실·카드에서 읽는다."""


def entity_names(snapshot, entity_id: str) -> tuple[str, ...]:
    subjects = [f.subject.strip() for f in snapshot.fact_revisions
                if f.entity_id == entity_id and f.subject and f.subject.strip()]
    titles = [c.title for c in snapshot.cards if c.entity_id == entity_id]
    return tuple(dict.fromkeys((*subjects, *titles)))


def entity_label(snapshot, entity_id: str) -> str:
    return entity_names(snapshot, entity_id)[0]
