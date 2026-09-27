"""카드 버전 → RAW 블록 고정과 KnowledgeContent 조립 (W, CP-05 / Task 2).

**카드 버전은 승인 시점의 원문을 그대로 얼려둔다.** typed 파싱이 아직 없는
지금은 원문 전체를 RAW 블록 몇 개로 쪼개 `raw_spans` 에 못박고, 그 뒤로는
`card_versions.content` 가 바뀌어도 이미 발행된 블록은 움직이지 않는다.
한 번 고정하면 다시 만들지 않는다(멱등) — 재실행마다 raw_span_id 가 새로
발급되면 이전 발행이 인용한 구간이 조용히 달라진다.

원문의 출처는 둘 중 하나다: 점주가 올린 자료(`knowledge_cards.source_id`),
또는 신입 질문에 점주가 직접 단 답변(`owner_answers`, D 2026-09-27). 어느 쪽도
없으면 공개할 근거가 없다는 뜻이므로 `NoProvenance` 로 멈춘다 — 근거 없이
싣지 않는다(불변식 6).
"""
from __future__ import annotations

from app.contracts.card import CardBlock
from app.contracts.snapshot import KnowledgeContent, PublishedCard, RawSpan
from app.learn.approved_renderer import RENDERER_VERSION

# 원문 한 조각의 최대 길이. RawSpan.text 계약의 상한과 같다 (app.contracts.snapshot)
RAW_SPAN_MAX = 4000
# 카드 하나에 담기는 블록 수 상한. PublishedCard.blocks 계약의 상한과 같다
MAX_BLOCKS = 20


class NoProvenance(RuntimeError):
    """카드 버전에 공개 가능한 출처(자료·점주 답변)가 없다."""


class InvalidContent(ValueError):
    """카드 버전 원문이 비었거나 블록 상한을 넘어 공개판에 실을 수 없다.

    빈 원문은 블록 0개가 되어 조립 단계에서 뒤늦게 터지므로, 고정 단계에서
    이 예외로 명시적으로 멈춘다 — 블록 없는 버전을 조용히 만들지 않는다.
    """


def _split_raw_spans(content: str, max_len: int) -> list[str]:
    """빈 줄(`\\n\\n`) 경계로 `max_len` 이하 조각을 만든다.

    원문 공백을 하나도 버리지 않기 위해 구분자 `\\n\\n` 을 별도 토큰으로 남겨
    쪼갠다 — 조각을 순서대로 이어 붙이면 원문과 완전히 같아진다. 문단(또는
    구분자) 하나가 그 자체로 `max_len` 을 넘으면 문자 단위로 더 자른다.
    """
    if not content:
        return []

    parts: list[str] = []
    rest = content
    while True:
        idx = rest.find("\n\n")
        if idx == -1:
            if rest:
                parts.append(rest)
            break
        if idx > 0:
            parts.append(rest[:idx])
        parts.append("\n\n")
        rest = rest[idx + 2:]

    chunks: list[str] = []
    current = ""
    for part in parts:
        if len(current) + len(part) <= max_len:
            current += part
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(part) <= max_len:
            current = part
            continue
        # 문단 하나가 상한을 넘는다 — 문자 단위로 잘라 각각 조각으로 만든다
        for i in range(0, len(part), max_len):
            piece = part[i:i + max_len]
            if len(piece) == max_len:
                chunks.append(piece)
            else:
                current = piece
    if current:
        chunks.append(current)
    return chunks


async def _resolve_provenance(
    conn, *, store_id: int, card_id: int, allow_owner_answer: bool,
) -> tuple[int | None, int | None]:
    """(source_id, owner_answer_id) 중 정확히 하나만 채워 돌려준다.

    (1) 자료 출처가 있으면 그것을 쓴다. (2) 없고 `allow_owner_answer` 면 그
    카드에 달린 가장 이른 점주 답변을 쓴다. `owner_answers` 에는 store_id 가
    없으므로 `pending_questions` 를 거쳐 매장을 확인한다. (3) 둘 다 없으면
    공개할 수 없다.
    """
    source_id = await conn.fetchval(
        "select source_id from knowledge_cards where store_id = $1 and card_id = $2",
        store_id, card_id)
    if source_id is not None:
        return source_id, None

    if allow_owner_answer:
        answer_id = await conn.fetchval(
            """
            select oa.answer_id
            from owner_answers oa
            join pending_questions pq on pq.question_id = oa.question_id
            where pq.store_id = $1 and oa.card_id = $2
            order by oa.answer_id asc
            limit 1
            """,
            store_id, card_id)
        if answer_id is not None:
            return None, answer_id

    raise NoProvenance(f"카드 {card_id} 에 공개 가능한 출처(자료·점주 답변)가 없다")


async def ensure_raw_blocks(
    conn, *, store_id: int, card_id: int, card_version_id: int,
    allow_owner_answer: bool,
) -> None:
    """카드 버전의 원문을 RAW 블록으로 고정한다.

    이미 블록이 있으면 아무것도 하지 않는다(멱등·불변) — 한 번 발행에 실린
    원문 구간은 원본이 나중에 바뀌어도 그대로 남아야 과거 인용이 재현된다.

    **트랜잭션은 호출부 책임이다.** 이 함수는 주어진 커넥션 위에서
    `raw_spans` 행과 `card_version_blocks` 행을 조각 수만큼 순서대로
    insert 할 뿐, 트랜잭션을 열거나 커밋하지 않는다. 여러 카드를 한 번에
    발행할 때 하나가 실패하면 이 함수가 만든 행도 함께 롤백돼야 하므로,
    호출부가 트랜잭션 블록 안에서만 이 함수를 부른다.
    """
    exists = await conn.fetchval(
        """
        select 1 from card_version_blocks
        where store_id = $1 and card_version_id = $2
        limit 1
        """,
        store_id, card_version_id)
    if exists:
        return

    version_row = await conn.fetchrow(
        """
        select content, owner_answer_id from card_versions
        where store_id = $1 and card_id = $2 and version_id = $3
        """,
        store_id, card_id, card_version_id)
    if version_row is None:
        raise ValueError(
            f"카드 버전을 찾을 수 없다: store={store_id} card={card_id} "
            f"version={card_version_id}")

    version_answer_id = version_row.get("owner_answer_id")
    if version_answer_id is not None:
        # 이 판의 본문은 점주 답변이다. 카드에 자료 출처가 있어도 그 자료를 인용하면
        # 자료에 없는 내용을 자료 근거로 싣게 된다. 판에 적힌 답변만 출처로 쓴다
        if not allow_owner_answer:
            raise NoProvenance(
                f"카드 {card_id} 판 {card_version_id} 은 점주 답변 출처라 아직 공개할 수 없다")
        source_id, owner_answer_id = None, version_answer_id
    else:
        source_id, owner_answer_id = await _resolve_provenance(
            conn, store_id=store_id, card_id=card_id,
            allow_owner_answer=allow_owner_answer)

    content = version_row["content"] or ""
    if not content.strip():
        raise InvalidContent(
            f"카드 버전 {card_version_id} 의 원문이 비어 있어 공개할 수 없다")

    chunks = _split_raw_spans(content, RAW_SPAN_MAX)
    if len(chunks) > MAX_BLOCKS:
        raise InvalidContent(
            f"카드 버전 {card_version_id} 의 원문이 {len(chunks)}조각으로 "
            f"쪼개져 상한 {MAX_BLOCKS}을 넘는다")

    for n, chunk in enumerate(chunks, start=1):
        raw_span_id = await conn.fetchval(
            """
            insert into raw_spans (store_id, source_id, owner_answer_id,
                                   span_text, locator_type, locator)
            values ($1, $2, $3, $4, 'WHOLE_SOURCE', '{}'::jsonb)
            returning raw_span_id
            """,
            store_id, source_id, owner_answer_id, chunk)
        await conn.execute(
            """
            insert into card_version_blocks (store_id, card_version_id,
                                             block_id, kind, block_order,
                                             raw_span_id)
            values ($1, $2, $3, 'RAW', $4, $5)
            """,
            store_id, card_version_id, f"raw{n}", n, raw_span_id)


async def current_manifest(conn, *, store_id: int) -> dict[int, int]:
    """지금 공개해야 할 카드 집합 — `{card_id: card_version_id}`.

    **현재 카드 포인터가 정본이다** (Ruling, final fix). 승인(`APPROVED`)되고
    `published_version_id` 가 있는 카드 전체를 그 공개 포인터 버전으로 싣는다.
    직전 snapshot 을 베끼지 않는 이유:
      - 제외 뒤 복원된 카드가 다음 공개에서 스스로 돌아온다.
      - 레거시 경로(공개 포인터를 직접 옮기는 R·ingest 경로)로 공개된 카드와,
        출처가 없어 한 번 빠졌던 카드(예: 점주 답변 공개 플래그 OFF)가 다음
        공개에서 저절로 다시 실린다 — snapshot 을 베끼면 한 번 빠진 카드는
        영영 돌아오지 않는다.
    제외·검수 대기 등 `APPROVED` 가 아닌 카드는 싣지 않는다.
    """
    rows = await conn.fetch(
        """
        select card_id, published_version_id as card_version_id
        from knowledge_cards
        where store_id = $1 and review_status = 'APPROVED'
          and published_version_id is not null
        order by card_id
        """,
        store_id)
    return {row["card_id"]: row["card_version_id"] for row in rows}


async def build_knowledge_content(
    conn, *, store_id: int, manifest: dict[int, int], glossary_version: str,
) -> KnowledgeContent:
    """manifest 의 각 카드 버전을 읽어 불변 `KnowledgeContent` 로 조립한다.

    블록이 없는 버전은 `ensure_raw_blocks` 를 먼저 부르지 않은 것이므로
    `ValueError` 로 멈춘다 — 호출부가 발행 전에 순서를 보장해야 한다.

    `entity_id` 는 카드가 어느 대상에 대한 것인지 가리키는 축인데, 그 대상을
    담는 테이블이 아직 없다. 이번 조립에서는 `card_id` 를 그대로 쓴다
    (Ruling, Task 2 — 대상 테이블이 생기면 옮긴다).
    """
    cards: list[PublishedCard] = []
    spans_by_id: dict[str, RawSpan] = {}

    for card_id, card_version_id in manifest.items():
        version_row = await conn.fetchrow(
            """
            select title from card_versions
            where store_id = $1 and card_id = $2 and version_id = $3
            """,
            store_id, card_id, card_version_id)
        if version_row is None:
            raise ValueError(
                f"카드 버전을 찾을 수 없다: store={store_id} card={card_id} "
                f"version={card_version_id}")

        block_rows = await conn.fetch(
            """
            select block_id, kind, block_order, raw_span_id
            from card_version_blocks
            where store_id = $1 and card_version_id = $2
            order by block_order
            """,
            store_id, card_version_id)
        if not block_rows:
            raise ValueError(
                f"카드 버전 {card_version_id} 에 블록이 없다. "
                "ensure_raw_blocks 를 먼저 불러야 한다")

        blocks: list[CardBlock] = []
        for row in block_rows:
            raw_span_id = row["raw_span_id"]
            blocks.append(CardBlock(
                block_id=row["block_id"], kind=row["kind"],
                order=row["block_order"],
                raw_span_id=str(raw_span_id) if raw_span_id is not None else None))

            if raw_span_id is not None and str(raw_span_id) not in spans_by_id:
                span_row = await conn.fetchrow(
                    """
                    select raw_span_id, source_id, owner_answer_id, span_text
                    from raw_spans
                    where store_id = $1 and raw_span_id = $2
                    """,
                    store_id, raw_span_id)
                spans_by_id[str(raw_span_id)] = RawSpan(
                    raw_span_id=str(span_row["raw_span_id"]),
                    source_id=(str(span_row["source_id"])
                               if span_row["source_id"] is not None else None),
                    owner_answer_id=(str(span_row["owner_answer_id"])
                                      if span_row["owner_answer_id"] is not None
                                      else None),
                    text=span_row["span_text"])

        title = (version_row["title"] or "").strip()
        title = title[:120] if title else "제목 없음"

        cards.append(PublishedCard(
            card_id=str(card_id), card_version_id=str(card_version_id),
            entity_id=str(card_id), title=title, blocks=tuple(blocks)))

    return KnowledgeContent(
        store_id=str(store_id), glossary_version=glossary_version,
        renderer_version=RENDERER_VERSION, cards=tuple(cards),
        fact_revisions=(), raw_spans=tuple(spans_by_id.values()))
