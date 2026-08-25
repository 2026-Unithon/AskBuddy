"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Badge, Button, Card, Input, WideShell } from "@/components/ui";
import { useApp } from "@/lib/store";
import type { StaffLevel } from "@/lib/types";

const LEVEL_TONE: Record<StaffLevel, "brand" | "neutral" | "warn"> = {
  great: "brand",
  good: "neutral",
  warn: "warn",
};
const LEVEL_LABEL: Record<StaffLevel, string> = {
  great: "잘하고 있어요",
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
    <WideShell>
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">{state.storeName} 대시보드</h1>
          <p className="text-sm text-muted mt-0.5">직원 진행 상황과 대기 질문을 한눈에 봐요.</p>
        </div>
        <div className="flex items-center gap-2">
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
          <Link href="/role" className="text-sm text-muted hover:text-foreground px-2">
            나가기
          </Link>
        </div>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="p-5">
          <p className="text-xs text-muted">등록 직원 수</p>
          <p className="text-2xl font-bold mt-1">{state.staff.length}명</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs text-muted">평균 이해도</p>
          <p className="text-2xl font-bold mt-1">{avgProgress}%</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs text-muted">답변 대기 질문</p>
          <p className="text-2xl font-bold mt-1">{state.pendingQuestions.length}건</p>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-muted">직원별 이해도</h2>
          <Card className="divide-y divide-border">
            {state.staff.map((s) => (
              <div key={s.id} className="p-4 flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center font-semibold text-sm">
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

          <h2 className="text-sm font-semibold text-muted pt-2">빈 지식 알림</h2>
          <Card className="divide-y divide-border">
            {state.emptyKnowledge.map((g) => (
              <div key={g.id} className="p-4 flex items-center gap-2">
                <span>🕳️</span>
                <span className="text-sm">{g.topic}</span>
                <Badge tone="neutral">미등록</Badge>
              </div>
            ))}
            {state.emptyKnowledge.length === 0 && (
              <p className="p-4 text-sm text-muted">빈 지식이 없어요.</p>
            )}
          </Card>
        </section>

        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-muted">답변 대기 질문</h2>
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
                <p className="text-[11px] text-muted">
                  답변하면 Buddy 지식에 자동 반영되고 신입 화면의 배지가 사라져요.
                </p>
              </Card>
            ))}
            {state.pendingQuestions.length === 0 && (
              <Card className="p-6 text-center text-sm text-muted">대기 중인 질문이 없어요 🎉</Card>
            )}
          </div>
        </section>
      </div>
    </WideShell>
  );
}
