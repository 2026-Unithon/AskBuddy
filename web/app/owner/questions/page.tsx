"use client";

import { useEffect, useState } from "react";
import { Badge, BuddyBubble, Button, Card, Input, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { ApiError, answerPending, listQuestions, type LearnQuestionItem } from "@/lib/api";

const POLL_MS = 2000;

function formatAskedAt(iso: string) {
  return new Date(iso).toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusBadge(status: LearnQuestionItem["status"]) {
  if (status === "WAITING") return { tone: "warn" as const, label: "대기" };
  if (status === "OWNER_ANSWERED") return { tone: "brand" as const, label: "사장님 답" };
  return { tone: "neutral" as const, label: "지식 답" };
}

export default function QuestionsPage() {
  const { state } = useApp();
  const [items, setItems] = useState<LearnQuestionItem[]>([]);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [answeringId, setAnsweringId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!state.token) return;
    let cancelled = false;

    async function refresh() {
      try {
        const res = await listQuestions(state.token!);
        if (cancelled) return;
        setItems(res.items ?? []);
        setError(null);
        setLoaded(true);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.detail || "질문을 불러오지 못했어요" : "서버에 연결할 수 없습니다");
        setLoaded(true);
      }
    }

    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [state.token]);

  async function submitAnswer(item: LearnQuestionItem) {
    const waitingId = item.waiting_question_id;
    const text = drafts[item.message_id]?.trim();
    if (!waitingId || !text || !state.token || answeringId) return;
    setAnsweringId(item.message_id);
    setError(null);
    try {
      await answerPending(waitingId, text, state.token);
      const same = item.question_text.trim();
      setItems((prev) =>
        prev.map((q) =>
          q.question_text.trim() === same
            ? {
                ...q,
                status: "OWNER_ANSWERED",
                answer_text: text,
                waiting_question_id: null,
              }
            : q
        )
      );
      setDrafts((d) => ({ ...d, [item.message_id]: "" }));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail || "답변 저장에 실패했어요" : "서버에 연결할 수 없습니다");
    } finally {
      setAnsweringId(null);
    }
  }

  return (
    <Shell>
      <TopBar title="전체 질문" />
      <div className="px-5 pt-1 pb-3">
        <BuddyBubble text="알바가 물은 질문을 최신순으로 보여 드려요. 바로 답한 것과 아직 대기 중인 것이 함께 보여요." />
      </div>
      <div className="px-5 flex-1 overflow-y-auto pb-6 space-y-3">
        {error && <p className="text-xs font-medium text-[#E57373]">{error}</p>}
        {loaded && items.length === 0 && !error && (
          <Card className="p-6 text-center text-sm text-muted">아직 질문이 없어요</Card>
        )}
        {items.map((q) => {
          const badge = statusBadge(q.status);
          const canAnswer = q.status === "WAITING" && q.waiting_question_id != null;
          return (
            <Card key={q.message_id} className="p-4 space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-xs text-muted">
                    {q.asked_by}님 · {formatAskedAt(q.created_at)}
                  </p>
                  <p className="text-sm font-medium mt-0.5">{q.question_text}</p>
                </div>
                <Badge tone={badge.tone}>{badge.label}</Badge>
              </div>
              {q.answer_text && (
                <p className="text-sm text-foreground whitespace-pre-wrap bg-brand-50 rounded-xl px-3 py-2">
                  {q.answer_text}
                </p>
              )}
              {canAnswer && (
                <div className="flex gap-2">
                  <Input
                    placeholder="답변을 입력하세요"
                    value={drafts[q.message_id] ?? ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [q.message_id]: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && submitAnswer(q)}
                    disabled={answeringId === q.message_id}
                  />
                  <Button onClick={() => submitAnswer(q)} disabled={answeringId === q.message_id}>
                    {answeringId === q.message_id ? "저장 중" : "답변"}
                  </Button>
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </Shell>
  );
}
