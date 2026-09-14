"""서버 렌더러 (가짜) — 승인된 글자만 골라 답을 만든다 (MVP 31-5, D12).

**새 문장을 만들지 않는다.** 모델이 쓴 문장을 그대로 내보내면 승인 검사를 통과한
것은 인용 목록뿐이고 정작 직원이 읽는 문장은 아무도 검수하지 않은 것이 된다.
그래서 렌더러는 승인된 `assertion` 과 원문 구간을 고르고 잇는 일만 한다.

`renderer_version` 이 다른 snapshot 은 거절한다. 같은 승인 내용이 렌더러가 바뀌면
다르게 읽힐 수 있고, 그때 과거 답변의 재현이 끊긴다.
"""
from __future__ import annotations

from app.contracts.answer import AnswerPlan
from app.contracts.chat import (
    POLICY_MESSAGES,
    ChatResponse,
    Citation,
    SourceAvailability,
)
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.contracts.validate import validate_answer_plan

RENDERER_VERSION = "fake-renderer/v1"

ESCALATE_MESSAGE = "지금 확인된 자료로는 답을 드릴 수 없어요. 사장님께 여쭤보고 알려드릴게요."
CLARIFY_TEMPLATE = "{slot} 을(를) 알려주시면 정확히 알려드릴게요."


class RenderError(RuntimeError):
    """렌더링할 수 없다. 이 예외를 삼키고 모델 문장으로 대체하지 않는다."""


class FakeRenderer:
    version = RENDERER_VERSION

    def render(
        self,
        plan: AnswerPlan,
        snapshot: PublishedKnowledgeSnapshot,
        *,
        store_id: str,
        request_id: str,
        availability: dict[str, SourceAvailability] | None = None,
        pending_id: str | None = None,
    ) -> ChatResponse:
        if snapshot.renderer_version != self.version:
            raise RenderError(
                f"이 snapshot 은 renderer {snapshot.renderer_version} 로 만들어졌다. "
                f"여기는 {self.version} 다")
        # 모양 검증과 별개로 매장·승인 범위를 다시 본다 (RV-04)
        validate_answer_plan(plan, snapshot, store_id=store_id)

        common = dict(request_id=request_id, action=plan.action,
                      snapshot_id=plan.snapshot_id,
                      knowledge_revision=plan.knowledge_revision)

        if plan.action in POLICY_MESSAGES:
            return ChatResponse(message=POLICY_MESSAGES[plan.action], **common)
        if plan.action == "CLARIFY":
            return ChatResponse(
                message=CLARIFY_TEMPLATE.format(slot=plan.clarification_slot),
                context_id=plan.context_id,
                clarification_slot=plan.clarification_slot,
                allowed_options=plan.allowed_options, **common)
        if plan.action == "ESCALATE":
            if not pending_id:
                # 저장 전에 응답을 만들면 직원에게 "여쭤볼게요" 라고 해놓고
                # 점주에게는 아무것도 가지 않는다 (불변식 5)
                raise RenderError("ESCALATE 응답은 WAITING 저장 뒤에만 만든다")
            return ChatResponse(message=ESCALATE_MESSAGE, pending_id=pending_id,
                                **common)

        lines, citations = self._answer_body(plan, snapshot, availability or {})
        if not lines:
            raise RenderError("인용할 승인 문장이 없다. 근거 없이 답하지 않는다")
        return ChatResponse(message="\n".join(lines), citations=tuple(citations),
                            **common)

    def _answer_body(self, plan, snapshot, availability):
        lines: list[str] = []
        citations: list[Citation] = []
        for sel in plan.selected_blocks:
            card = snapshot.card(sel.card_id)
            block = next(b for b in card.blocks if b.block_id == sel.block_id)
            if sel.raw_span_id or block.raw_span_id:
                span = next(r for r in snapshot.raw_spans
                            if r.raw_span_id == block.raw_span_id)
                lines.append(span.text)
                citations.append(Citation(
                    card_id=card.card_id, card_version_id=card.card_version_id,
                    block_id=block.block_id, raw_span_id=span.raw_span_id,
                    source_id=span.source_id,
                    source_availability=availability.get(span.source_id,
                                                         "AVAILABLE")))
                continue
            # 블록이 정한 순서를 따른다. 인용한 것만 보여준다
            chosen = [f for f in (snapshot.fact(fid)
                                  for fid in block.fact_revision_ids)
                      if f.fact_revision_id in sel.fact_revision_ids]
            for fact in sorted(chosen, key=lambda f: (f.order or 0)):
                lines.append(self._line(fact))
                source_id = fact.provenance[0].source_id
                citations.append(Citation(
                    card_id=card.card_id, card_version_id=card.card_version_id,
                    block_id=block.block_id,
                    fact_revision_id=fact.fact_revision_id,
                    source_id=source_id,
                    source_availability=availability.get(source_id, "AVAILABLE")))
        return lines, citations

    @staticmethod
    def _line(fact) -> str:
        """승인된 표현을 그대로 쓰고, 조건·예외를 덧붙인다.

        조건을 떼면 "225ml" 만 남아 규격이 다른 음료에 그대로 적용된다 (D19).
        """
        text = fact.assertion
        if fact.polarity == "NEGATE" and "않" not in text and "금지" not in text:
            text = f"{text} (하지 않는다)"
        if fact.conditions:
            text = f"{text} — {' · '.join(fact.conditions)}"
        if fact.exceptions:
            text = f"{text} (예외: {' · '.join(fact.exceptions)})"
        return text
