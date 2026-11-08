"use client";

import { useState } from "react";
import { focusRing, pressable } from "@/components/kit/buttons";
import { useFeedback } from "@/components/kit/feedback";
import { Stagger } from "@/components/kit/stagger";
import { SwipeRow } from "@/components/kit/swipe-row";
import { QuestionSheet } from "@/components/owner/question-sheet";

type Question = { pending_id: string; question: string };
const SNOOZE_KEY = "askbuddy:snoozed-questions";

function readSnoozed(): string[] {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(SNOOZE_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

/**
 * 기다리는 질문 목록(o01d·o09b). 누르면 답하기 시트가 올라오고, 왼쪽으로 밀면 '나중에'(목록 끝으로).
 * '나중에' 순서는 이 탭의 사용자 편의라 sessionStorage 에 두고, 못 쓰면 이번 화면에서만 유지한다.
 */
export function WaitingQuestionList({ questions, meta }: { questions: Question[]; meta?: string }) {
  const [open, setOpen] = useState<Question | null>(null);
  const [snoozed, setSnoozed] = useState<string[]>(() => (typeof window === "undefined" ? [] : readSnoozed()));
  const { toast } = useFeedback();
  const snooze = (id: string) => {
    // 하나뿐이면 끝으로 보내도 그대로라 아무 일도 안 일어난 것처럼 보인다
    if (questions.length <= 1) {
      toast("다른 질문이 없어 그대로 둘게요");
      return;
    }
    const next = [...snoozed.filter((x) => x !== id), id];
    setSnoozed(next);
    try {
      sessionStorage.setItem(SNOOZE_KEY, JSON.stringify(next));
    } catch {
      // 저장 못 해도 이번 화면에서는 끝으로 간다
    }
  };
  const rank = (id: string) => snoozed.indexOf(id);
  const ordered = [...questions].sort((a, b) => rank(a.pending_id) - rank(b.pending_id));

  return (
    <>
      <Stagger>
        {ordered.map((q) => (
          <SwipeRow key={q.pending_id} left={{ label: "나중에", ariaLabel: `${q.question} 나중에`, tone: "neutral", onAction: () => snooze(q.pending_id) }}>
            <button
              type="button"
              onClick={() => setOpen(q)}
              className={`flex w-full flex-col gap-1.5 rounded-[20px] bg-surface px-[18px] py-4 text-left shadow-card ${pressable} ${focusRing}`}
            >
              <span className="text-[15px] font-bold leading-[1.45] text-ink [word-break:keep-all]">{q.question}</span>
              {/* 설명 문구는 두지 않는다(2026-11-08 사용자). 부르는 쪽이 꼭 필요한 한 줄만 넘긴다 */}
              {meta && <span className="text-[12px] text-ink-muted">{meta}</span>}
            </button>
          </SwipeRow>
        ))}
      </Stagger>
      <QuestionSheet
        question={open}
        onClose={() => setOpen(null)}
        // 앞 질문의 저장이 늦게 끝나도 지금 열린 다른 질문 시트는 닫지 않는다
        onSent={(id) => setOpen((current) => (current?.pending_id === id ? null : current))}
      />
    </>
  );
}
