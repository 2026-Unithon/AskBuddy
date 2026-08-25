"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Badge, Buddy, BuddyBubble, Button, Card, Input } from "@/components/ui";
import { useApp } from "@/lib/store";
import type { StaffLevel } from "@/lib/types";

const LEVEL_TONE: Record<StaffLevel, "brand" | "warn" | "danger"> = {
  great: "brand",
  good: "warn",
  warn: "danger",
};
const LEVEL_LABEL: Record<StaffLevel, string> = {
  great: "투입 가능",
  good: "괜찮아요",
  warn: "확인이 필요해요",
};

export default function DashboardPage() {
  const { state, dispatch } = useApp();
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const avgProgress = useMemo(() => {
    if (state.staff.length === 0) return 0;
    return Math.round(
      state.staff.reduce((sum, s) => sum + s.progressPct, 0) / state.staff.length
    );
  }, [state.staff]);

  function submitAnswer(id: string) {
    const text = drafts[id]?.trim();
    if (!text) return;
    dispatch({ type: "ANSWER_PENDING_QUESTION", id, answerText: text });
    setDrafts((d) => ({ ...d, [id]: "" }));
  }

  return (
    <div className="min-h-dvh w-full bg-background">
      <div className="bg-brand-700 px-5 sm:px-8 pt-8 pb-7">
        <div className="max-w-5xl mx-auto">
          <Link
            href="/role"
            className="inline-flex items-center gap-1.5 mb-4 text-white/70 hover:text-white transition-colors text-xs font-semibold"
          >
            ← 이전으로
          </Link>
          <div className="flex items-center justify-between mb-5">
            <div>
              <p className="text-white/55 text-xs font-semibold">사장님 대시보드</p>
              <h1 className="text-2xl font-bold text-white">{state.storeName}</h1>
            </div>
            <Buddy size={44} />
          </div>
          <div className="grid grid-cols-3 gap-2.5 max-w-md">
            {[
              { label: "등록 직원", value: `${state.staff.length}명` },
              { label: "평균 이해도", value: `${avgProgress}%` },
              { label: "대기 질문", value: `${state.pendingQuestions.length}건` },
            ].map((s) => (
              <div key={s.label} className="bg-white/12 rounded-2xl py-3 text-center">
                <p className="text-xl font-bold text-white">{s.value}</p>
                <p className="text-[11px] text-white/55 font-medium">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-5 sm:px-8 pt-5 flex items-center gap-2">
        <Link
          href="/owner/upload"
          className="inline-flex items-center gap-1.5 rounded-full bg-brand-600 px-4 h-10 text-sm font-semibold text-white hover:bg-brand-700"
        >
          <span aria-hidden>＋</span> 자료 추가
        </Link>
        <Link
          href="/owner/preview"
          className="inline-flex items-center rounded-full border border-border px-4 h-10 text-sm font-semibold text-brand-700 hover:bg-brand-50"
        >
          학습 미리보기
        </Link>
        <Link href="/role" className="text-sm text-muted hover:text-foreground px-2 ml-auto">
          나가기
        </Link>
      </div>

      <div className="max-w-5xl mx-auto px-5 sm:px-8 py-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="space-y-3">
          <h2 className="text-base font-bold text-brand-700">직원 이해도</h2>
          <Card className="divide-y divide-border">
            {state.staff.map((s) => (
              <div key={s.id} className="p-4 flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-brand-700 text-white flex items-center justify-center font-bold text-sm">
                  {s.name.slice(0, 1)}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{s.name}</p>
                  <p className="text-xs text-muted">{s.label}</p>
                </div>
                <Badge tone={LEVEL_TONE[s.level]}>
                  {s.progressPct}% · {LEVEL_LABEL[s.level]}
                </Badge>
              </div>
            ))}
            {state.staff.length === 0 && (
              <p className="p-4 text-sm text-muted">아직 합류한 직원이 없어요.</p>
            )}
          </Card>

          <h2 className="text-base font-bold text-brand-700 pt-2">빈 지식 알림</h2>
          <div className="bg-accent-100 border border-accent-500/30 rounded-2xl p-4 space-y-3">
            <BuddyBubble text="이 부분은 아직 아무도 안 알려줬어요!" size={32} />
            {state.emptyKnowledge.map((g) => (
              <div key={g.id} className="flex items-center justify-between bg-surface rounded-xl px-3 py-2.5">
                <span className="text-xs font-semibold">❓ {g.topic}</span>
                <button className="text-xs font-bold text-brand-500">추가하기</button>
              </div>
            ))}
            {state.emptyKnowledge.length === 0 && (
              <p className="text-xs text-muted px-1">빈 지식이 없어요.</p>
            )}
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="text-base font-bold text-brand-700">답변 대기 질문</h2>
          <BuddyBubble
            text="답변하면 Buddy 지식에 자동 반영되고 신입 화면의 배지가 사라져요"
            size={32}
          />
          <div className="flex flex-col gap-3">
            {state.pendingQuestions.map((q) => (
              <Card key={q.id} className="p-4 space-y-3">
                <div>
                  <p className="text-xs text-muted">{q.askedBy}님의 질문</p>
                  <p className="text-sm font-medium mt-0.5">{q.questionText}</p>
                </div>
                <div className="flex gap-2">
                  <Input
                    placeholder="답변을 입력하세요"
                    value={drafts[q.id] ?? ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [q.id]: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && submitAnswer(q.id)}
                  />
                  <Button onClick={() => submitAnswer(q.id)}>답변</Button>
                </div>
              </Card>
            ))}
            {state.pendingQuestions.length === 0 && (
              <Card className="p-6 text-center text-sm text-muted">대기 중인 질문이 없어요 🎉</Card>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
