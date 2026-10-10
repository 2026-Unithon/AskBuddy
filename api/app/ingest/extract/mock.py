"""외부 모델 없이 사실 추출→카드 조립 계약을 확인하는 합성 mock.

실제 경로와 같은 원래 응답 기록을 남긴다 (W1-1) — 테스트·재현에서 기록 경로를 함께 돈다.
mode='mock' 으로 남아 모델 성능 집계와 섞이지 않는다 (D10).
재사용 키(W1-3)도 실제 경로와 같은 완성 프롬프트로 계산·저장·조회한다. model·mode 가 키에
들어가므로 mock 응답이 실제 호출에 되쓰이는 일은 없다. mock 은 원가 원장에 쓰지 않는다.
"""
import re
from collections import defaultdict

from app.config import get_settings
from app.ingest import raw_responses, reuse
from app.ingest.schemas import (CardPlanBatch, Evidence, ExtractedAssertion, ExtractedCard,
                                ExtractedFact, ExtractionResult, FactExtractionResult,
                                PlannedBlock, PlannedCard)


# 원래 응답 행의 model 열. 실제 모델명이 아니다 — mode='mock' 과 함께 합성 응답임을 밝힌다
MOCK_MODEL = "mock"


async def _as_recorded(build, schema, *, raw_sink, usage_context, prompt, media=()):
    """합성 결과를 모델 응답처럼 JSON 으로 남기고, 실제 경로와 같이 파싱해 돌려준다.

    `build()` 가 '모델 호출' 자리다. 같은 키의 지난 성공 응답을 되쓰면 부르지 않는다.
    """
    key = None
    if raw_sink is not None and usage_context is not None:
        s = get_settings()
        key = await reuse.key_for(usage_context, s, model=MOCK_MODEL, mode="mock",
                                  prompt=prompt, media=media, schema=schema,
                                  max_output_tokens=None)
        if reuse.lookup_allowed(usage_context, s):
            hit = await reuse.find(raw_sink, usage_context, key, schema)
            if hit is not None:
                parsed = schema.model_validate_json(hit.response_text)
                parsed._raw_response_id = hit.raw_response_id
                return parsed
    text = build().model_dump_json()
    raw_id = await raw_responses.record(
        raw_sink, usage_context, model=MOCK_MODEL, mode="mock", prompt_hash=None,
        schema=schema, finish_reason="STOP", response_text=text, usage={},
        reuse_key=key)
    parsed = await raw_responses.parse_recorded(
        raw_sink, usage_context, raw_id, lambda: schema.model_validate_json(text))
    parsed._raw_response_id = raw_id
    return parsed


def _facts_result(source_id) -> FactExtractionResult:
    samples = [("커피머신", "예열시간", "15분", .91, 12),
               ("커피머신", "적정압력", "9바", .88, 12),
               ("원두", "보관위치", "제빙기 아래 세 번째 선반", .78, 41),
               ("아이스머신", "마감작업", "배수 밸브 개방", .42, 88)]
    result = FactExtractionResult(assertions=[
        ExtractedAssertion(local_ref=f"m{i}", original_assertion=f"{subject} {attribute} {value}",
                           subject=subject, attribute=attribute, value=value, confidence=confidence,
                           evidence=Evidence(source_id=source_id, timestamp_sec=timestamp))
        for i, (subject, attribute, value, confidence, timestamp) in enumerate(samples, 1)
    ], unresolved=["합성 mock 데이터: 원본 자료의 실제 추출 결과가 아님"])
    return result


async def extract_facts(*, source_id, source_type, text, glossary, media=(),
                        usage_context=None, raw_sink=None):
    from app.ingest.extract.gemini import facts_schema, locator_hints, render_facts_prompt

    s = get_settings()
    schema = facts_schema(s)
    prompt = (render_facts_prompt(source_type=source_type, text=text, glossary=glossary,
                                  locator_hints=locator_hints(s))
              if raw_sink is not None and usage_context is not None else "")
    # 합성 사실은 page·line 을 채우지 않는다 — 켠 판의 스키마로 다시 읽어 모양만 맞춘다
    return await _as_recorded(lambda: schema.model_validate(_facts_result(source_id).model_dump()),
                              schema,
                              raw_sink=raw_sink, usage_context=usage_context,
                              prompt=prompt, media=list(media or []))


async def assemble(*, source_id, facts, category_names, glossary,
                   usage_context=None, raw_sink=None):
    from app.ingest.extract.gemini import render_assemble_prompt

    prompt = (render_assemble_prompt(facts=facts, category_names=category_names,
                                     glossary=glossary)
              if raw_sink is not None and usage_context is not None else "")
    return await _as_recorded(lambda: _assembled(source_id, facts, category_names),
                              ExtractionResult, raw_sink=raw_sink,
                              usage_context=usage_context, prompt=prompt)


def _assembled(source_id, facts, category_names) -> ExtractionResult:
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


async def assemble_plan(*, source_id, entities, category_names, glossary,
                        usage_context=None, raw_sink=None):
    """사실 조립(W3a) 합성 대역. 실제 경로와 같은 완성 프롬프트로 기록·재사용한다."""
    from app.ingest.extract.gemini import render_card_plan_prompt

    prompt = (render_card_plan_prompt(entities=entities, category_names=category_names,
                                      glossary=glossary)
              if raw_sink is not None and usage_context is not None else "")
    return await _as_recorded(lambda: _planned(entities, category_names),
                              CardPlanBatch, raw_sink=raw_sink,
                              usage_context=usage_context, prompt=prompt)


def _planned(entities, category_names) -> CardPlanBatch:
    """규칙대로 배치한 합성 계획. 서버 검증(card_plan.validate_proposals)을 통과한다.

    대상마다 카드 하나. 규격 문자열이 처음 나온 순서로 묶고, 묶음마다
    QUANTITIES(단계 아님·부정 아님)·STEPS(단계, 순서 오름차순)·NOTES(단계 아님·부정) 블록.
    """
    category = category_names[0] if category_names else "기타"
    cards = []
    for entity in entities:
        by_variant: dict[str, list[dict]] = {}
        for fact in entity["사실"]:
            by_variant.setdefault(fact["규격"], []).append(fact)
        blocks = []
        for facts in by_variant.values():
            quantities = [f["id"] for f in facts if f["순서"] == 0 and not f["부정"]]
            # sorted 는 안정 정렬이다 — 같은 순서 값은 입력 순서를 지킨다
            steps = [f["id"] for f in sorted((f for f in facts if f["순서"] > 0),
                                             key=lambda f: f["순서"])]
            notes = [f["id"] for f in facts if f["순서"] == 0 and f["부정"]]
            for kind, refs in (("QUANTITIES", quantities), ("STEPS", steps), ("NOTES", notes)):
                if refs:
                    blocks.append(PlannedBlock(kind=kind, facts=refs))
        cards.append(PlannedCard(entity=entity["대상"], category_name=category, blocks=blocks))
    return CardPlanBatch(cards=cards)


_NUMBER_UNIT = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ml|g|kg|l|개|번|초|분|회|잔|컵|스푼|펌프|샷)?")
_NEGATIONS = ("않", "금지", "말 것", "하지 마")


async def parse_owner_facts(*, payload, usage_context=None, raw_sink=None):
    """W3b 점주 문장 분석 합성 대역. 결정적으로 한 건을 만든다. 실제 경로와 같은 프롬프트로 기록한다."""
    from app.ingest.extract.gemini import render_owner_fact_prompt

    prompt = (render_owner_fact_prompt(payload)
              if raw_sink is not None and usage_context is not None else "")
    return await _as_recorded(lambda: _parsed_owner_fact(payload), FactExtractionResult,
                              raw_sink=raw_sink, usage_context=usage_context, prompt=prompt)


def _parsed_owner_fact(payload) -> FactExtractionResult:
    text = str(payload.get("text", ""))
    found = _NUMBER_UNIT.search(text)
    value, unit = (found.group(1) or "", found.group(2) or "") if found else ("", "")
    return FactExtractionResult(assertions=[ExtractedAssertion(
        local_ref="o1", original_assertion=text.strip(),
        subject=str(payload.get("entity_name", "")), attribute="", value=value, unit=unit,
        polarity="NEGATE" if any(k in text for k in _NEGATIONS) else "AFFIRM",
        variant="", confidence=1.0)])
