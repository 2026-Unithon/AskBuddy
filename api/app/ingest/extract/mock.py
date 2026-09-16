"""외부 모델 없이 사실 추출→카드 조립 계약을 확인하는 합성 mock."""
from collections import defaultdict
from app.ingest.schemas import (Evidence, ExtractedAssertion, ExtractedCard,
                                ExtractedFact, ExtractionResult, FactExtractionResult)


async def extract_facts(*, source_id, source_type, text, glossary, media=()):
    samples = [("커피머신", "예열시간", "15분", .91, 12),
               ("커피머신", "적정압력", "9바", .88, 12),
               ("원두", "보관위치", "제빙기 아래 세 번째 선반", .78, 41),
               ("아이스머신", "마감작업", "배수 밸브 개방", .42, 88)]
    return FactExtractionResult(assertions=[
        ExtractedAssertion(local_ref=f"m{i}", original_assertion=f"{subject} {attribute} {value}",
                           subject=subject, attribute=attribute, value=value, confidence=confidence,
                           evidence=Evidence(source_id=source_id, timestamp_sec=timestamp))
        for i, (subject, attribute, value, confidence, timestamp) in enumerate(samples, 1)
    ], unresolved=["합성 mock 데이터: 원본 자료의 실제 추출 결과가 아님"])


async def assemble(*, source_id, facts, category_names, glossary):
    if not category_names:
        return ExtractionResult(unresolved=["켜둔 업무 카테고리가 없어 카드를 만들지 못했다"])
    groups = defaultdict(list)
    for fact in facts:
        groups[fact["대상"]].append(fact)
    cards = []
    for index, (subject, rows) in enumerate(groups.items()):
        content = "\n".join(f"{r.get('규격') or '규격 미확정'} · {r['속성']}: {r['값']}"
                            + (" (금지)" if r.get("부정") else "")
                            + (f" · 조건: {r['조건']}" if r.get("조건") else "")
                            + (f" · 예외: {r['예외']}" if r.get("예외") else "")
                            + (f" · 순서: {r['순서']}" if r.get("순서") else "") for r in rows)
        cards.append(ExtractedCard(category_name=category_names[index % len(category_names)],
            title=subject, content=content, confidence=min(r["확실함"] for r in rows),
            facts=[ExtractedFact(object_name=r["대상"], attribute=r["속성"], value=r["값"],
                                 confidence=r["확실함"], ref=r["ref"]) for r in rows],
            evidence=Evidence(source_id=source_id, timestamp_sec=min(r["근거시각"] for r in rows))))
    return ExtractionResult(cards=cards)
