"use client";

import { useQuery } from "@tanstack/react-query";
import { focusRing, pressable } from "@/components/kit/buttons";
import { faqsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

/**
 * 추천 질문 칩(s01f·s03c·NAV-6). 매장에서 많이 물어본 질문(/learn/faqs) 상위 몇 개.
 * cardId 가 있으면 그 카드에 대한 질문만. 불러오는 중·실패·0개면 아무것도 그리지 않는다(입력창은 그대로 쓴다).
 */
export function SuggestedQuestions({ cardId, limit = 3, onPick }: { cardId?: number; limit?: number; onPick: (question: string) => void }) {
  const { state } = useApp();
  const faqs = useQuery(faqsQuery(state.token, state.storeId));
  const items = (faqs.data?.items ?? [])
    .filter((item) => cardId === undefined || item.card_id === cardId)
    .sort((a, b) => b.question_count - a.question_count)
    .slice(0, limit);
  if (items.length === 0) return null;
  return (
    <div aria-label="추천 질문" className="-mx-1 flex shrink-0 gap-2 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
      {items.map((item) => (
        <button
          key={item.question}
          type="button"
          data-suggested=""
          onClick={() => onPick(item.question)}
          className={`min-h-10 shrink-0 whitespace-nowrap rounded-full bg-surface px-3.5 text-[14px] font-medium text-ink shadow-card ${pressable} ${focusRing}`}
        >
          {item.question}
        </button>
      ))}
    </div>
  );
}
