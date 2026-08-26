"""검색 게이트 판정. /reg/retrieve 와 /learn/chat 이 같은 함수를 쓴다.

공개 JSON 계약은 바꾸지 않는다. 내부 후보는 title 을 더 실어 citation 에 쓴다.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import asyncpg

from app.config import get_settings
from app.reg.embeddings import embed_text, vector_literal

MISS_MESSAGE = "사장님께 확인 중"

# 벡터 점수만으로는 "주차 자리 어디예요?" 와 "컵은 어디 있어요?" 를 못 가른다.
# 둘 다 '어디' 를 묻는 문장이라 임베딩이 0.5 넘게 붙는다 — 실측에서 이 오답이
# 정답 8개보다 높았다. 임계를 올리면 정답이 죽고 내리면 오답이 산다.
#
# 갈라주는 건 말투가 아니라 '무엇을' 묻느냐다. 그래서 질문에서 낱말을 뽑아
# 카드 본문에 그 말이 실제로 나오는지 본다. 주차는 어느 카드에도 없고 컵은 있다.

# 어느 카드에나 흔히 나와서 근거가 못 되는 말들
_STOP = {
    "어디", "언제", "어떻게", "어떤", "무엇", "무슨", "누구", "왜",
    "자리", "위치", "장소", "방법", "경우", "정도", "얼마", "여기", "거기",
    "이거", "그거", "저거", "우리", "그것", "지금", "오늘", "내일", "이제",
    "하나", "가지", "부분", "때문", "관련", "사용", "확인", "필요", "가능",
}
# 한 글자짜리도 앵커가 된다 — 샷·컵·잔 같은 말이 통째로 버려지면
# "아아 샷 몇 개?" 가 miss 로 떨어진다. 다만 아래 글자들은 근거가 못 된다.
_STOP1 = set("것거때곳수개몇왜뭐등안잘좀더또그이저첫한두세네위밑앞뒤옆말일분초년월")
# 붙어 다니는 조사·어미. 긴 것부터 떼어낸다
_TAIL = (
    "이라던데요", "라던데요", "인가요", "이에요", "예요", "에요", "해요", "어요",
    "아요", "나요", "가요", "까요", "던데", "습니까", "습니다", "봐요",
    "에서", "으로", "한테", "에게", "까지", "부터", "이랑", "보다", "처럼",
    "은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "로", "과", "와", "랑",
)


def _anchors(text: str) -> set[str]:
    """질문에서 '무엇을 묻는지' 에 해당하는 낱말만 남긴다."""
    out: set[str] = set()
    for word in re.split(r"[^0-9A-Za-z가-힣]+", text):
        if not word:
            continue
        if len(word) == 1:
            if word not in _STOP1:
                out.add(word)
            continue
        forms = {word}
        stem = word
        for tail in _TAIL:
            if stem.endswith(tail):
                stem = stem[: -len(tail)]
                if len(stem) >= 2:
                    forms.add(stem)
                break
        # "있어요" 처럼 떼고 나면 한 글자도 안 남는 건 서술어다. 근거가 못 된다.
        if word.endswith(("요", "죠", "까", "다")) and len(stem) < 2:
            continue
        out |= {f for f in forms if len(f) >= 2 and f not in _STOP}
    return out


def _grounded(anchors: set[str], card_text: str) -> bool:
    """질문의 낱말이 카드 본문에 실제로 나오는가."""
    return any(a in card_text for a in anchors)


async def retrieve_question(
    db: asyncpg.Connection,
    store_id: int,
    question: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """hit/miss 만 판정한다. miss 면 LLM 을 부르지 않는다."""
    question = question.strip()
    if len(question) < 2:
        return {
            "kind": "miss",
            "reason": "no_anchor",
            "message": MISS_MESSAGE,
            "candidates": [],
        }

    query_vec = await asyncio.to_thread(embed_text, question)
    rows = await db.fetch(
        """
        select
          m.card_id as id,
          m.content,
          m.title,
          coalesce(tc.category_name, '') as category,
          m.score
        from match_cards($1, $2::vector, $3) m
        join knowledge_cards c on c.card_id = m.card_id
        left join task_categories tc on tc.category_id = c.category_id
        where c.store_id = $1
        order by m.score desc
        """,
        store_id,
        vector_literal(query_vec),
        top_k,
    )

    settings = get_settings()
    threshold = settings.retrieval_threshold
    strong = settings.retrieval_strong_score
    anchors = _anchors(question)

    candidates = []
    for r in rows:
        score = float(r["score"])
        if score < threshold:
            continue
        # 점수가 아주 높으면 낱말이 안 겹쳐도 통과시킨다.
        # 같은 말을 다르게 부르는 경우(아아/아이스 아메리카노)를 막지 않기 위해서다.
        if score < strong and anchors and not _grounded(
            anchors, f"{r['title'] or ''} {r['content']}"
        ):
            continue
        candidates.append(
            {
                "id": int(r["id"]),
                "content": r["content"],
                "title": r["title"] or "",
                "category": r["category"],
                "score": score,
            }
        )

    if not candidates:
        return {
            "kind": "miss",
            "reason": "no_match",
            "message": MISS_MESSAGE,
            "candidates": [],
        }

    return {"kind": "hit", "candidates": candidates}
