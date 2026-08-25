"""준혁 — M1 목 추출기. LLM 을 호출하지 않는다.

M1 의 목적은 업로드 → 폴링 → 카드 적재 → 검수 화면까지의 경계를 뚫는 것이다.
통합 실패는 항상 이 구간에서 나므로 Gemini 를 붙이기 전에 여기부터 통과시킨다.

confidence 는 일부러 0.6 아래(D3) 카드를 하나 섞어 둔다.
점주 검수 화면의 "우선 노출" 분기를 프론트가 실제로 렌더해봐야 하기 때문이다.
"""
from app.ingest.schemas import Evidence, ExtractedCard, ExtractedFact, ExtractionResult

_TEMPLATES: list[dict] = [
    {
        "title": "커피머신 예열 순서",
        "content": "오픈 후 전원을 켜고 15분간 예열합니다. "
                   "압력 게이지가 9바에 오면 첫 샷을 버리고 시작하세요.",
        "confidence": 0.91,
        "timestamp_sec": 12,
        "facts": [("커피머신", "예열시간", "15분", 0.91),
                  ("커피머신", "적정압력", "9바", 0.88)],
    },
    {
        "title": "원두 보관 위치",
        "content": "원두는 제빙기 아래 세 번째 선반에 있습니다. "
                   "개봉한 봉지는 집게로 막아 같은 칸 맨 앞에 둡니다.",
        "confidence": 0.78,
        "timestamp_sec": 41,
        "facts": [("원두", "보관위치", "제빙기 아래 세 번째 선반", 0.78)],
    },
    {
        "title": "마감 시 아이스머신 물빼기",
        "content": "마감 때 아이스머신 배수 밸브를 열어 물을 뺍니다. "
                   "주기는 자료에서 확인되지 않아 사장님 확인이 필요합니다.",
        "confidence": 0.42,
        "timestamp_sec": 88,
        "facts": [("아이스머신", "마감작업", "배수 밸브 개방", 0.42)],
    },
]


async def extract(
    *, source_id: int, source_type: str, text: str,
    category_names: list[str], glossary: list[dict[str, str]],
) -> ExtractionResult:
    if not category_names:
        return ExtractionResult(
            cards=[],
            unresolved=["점주가 켜둔 업무 카테고리가 없어 카드를 만들지 못했다"],
        )

    cards = []
    for i, t in enumerate(_TEMPLATES):
        cards.append(ExtractedCard(
            category_name=category_names[i % len(category_names)],
            title=t["title"],
            content=t["content"],
            confidence=t["confidence"],
            facts=[ExtractedFact(object_name=o, attribute=a, value=v, confidence=c)
                   for o, a, v, c in t["facts"]],
            evidence=Evidence(source_id=source_id, timestamp_sec=t["timestamp_sec"]),
        ))

    return ExtractionResult(
        cards=cards,
        unresolved=["빨대·냅킨 위치 — 자료에서 확인 불가 (목 데이터)"],
    )
