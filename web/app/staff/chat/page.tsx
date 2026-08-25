"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { Badge, Buddy } from "@/components/ui";
import { useApp } from "@/lib/store";
import { retrieve } from "@/lib/api";
import { MOCK_KNOWLEDGE_SECTIONS } from "@/lib/mock";

// 백엔드가 연결되지 않았을 때만 쓰는 로컬 대체 판정 — 실제 판정은 전부 /reg/retrieve 가 한다 (개발가이드 6-3).
function simulateRetrieve(question: string) {
  const hitSection = MOCK_KNOWLEDGE_SECTIONS.find(
    (s) => s.confidence >= 60 && question.includes("우유")
  );
  if (hitSection) {
    return {
      kind: "hit" as const,
      candidates: [
        {
          id: hitSection.id,
          content: hitSection.items[0]?.text ?? "",
          category: hitSection.label,
          score: 0.91,
        },
      ],
    };
  }
  return { kind: "miss" as const, reason: "no_match", message: "사장님께 확인 중이에요" };
}

export default function ChatPage() {
  const { state, dispatch } = useApp();
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state.chatMessages, typing]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || typing) return;
    setInput("");

    dispatch({
      type: "ADD_CHAT_MESSAGE",
      message: { id: `msg-${Date.now()}`, from: "USER", text: question, createdAt: new Date().toISOString() },
    });
    setTyping(true);

    // kind: "miss" 면 LLM을 호출하지 않는다 — 이 판정은 반드시 /reg/retrieve 를 거친다 (CLAUDE.md 불변식 5).
    const [result] = await Promise.all([
      retrieve(state.storeSlug, question).catch(() => simulateRetrieve(question)),
      new Promise((r) => setTimeout(r, 900)), // Buddy가 "생각하는" 최소 시간 — 즉답이 어색해 보이지 않게
    ]);
    setTyping(false);

    if (result.kind === "hit") {
      const top = result.candidates[0];
      dispatch({
        type: "ADD_CHAT_MESSAGE",
        message: {
          id: `msg-${Date.now()}-a`,
          from: "BUDDY",
          text: top?.content ?? "답변을 찾았어요.",
          citations: top ? [{ cardId: top.id, title: top.category }] : [],
          createdAt: new Date().toISOString(),
        },
      });
    } else {
      dispatch({
        type: "ADD_CHAT_MESSAGE",
        message: {
          id: `msg-${Date.now()}-a`,
          from: "BUDDY",
          text: "이 질문은 아직 등록된 내용이 없어요. 사장님께 확인 중이에요! 잠시만 기다려주세요 😊",
          pending: true,
          createdAt: new Date().toISOString(),
        },
      });
      dispatch({
        type: "ADD_PENDING_QUESTION",
        question: {
          id: `pq-${Date.now()}`,
          askedBy: state.displayName ?? "신입",
          questionText: question,
          createdAt: new Date().toISOString(),
        },
      });
    }
  }

  return (
    <div className="min-h-dvh w-full flex justify-center bg-background">
      <div className="w-full max-w-[480px] min-h-dvh flex flex-col bg-[#EEF4EF]">
        {/* 헤더 */}
        <div className="shrink-0 bg-surface border-b border-border px-4 py-3 flex items-center gap-3">
          <Link
            href="/staff/roadmap"
            aria-label="뒤로가기"
            className="w-9 h-9 flex items-center justify-center rounded-full hover:bg-surface-muted transition-colors"
          >
            ←
          </Link>
          <Buddy size={36} />
          <div>
            <p className="text-sm font-bold text-brand-700">Buddy</p>
            <p className="text-xs text-muted">AI 인수인계 도우미</p>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-brand-500 animate-pulse" />
            <span className="text-xs font-medium text-brand-500">온라인</span>
          </div>
        </div>

        {/* 메시지 */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3.5">
          {state.chatMessages.map((m) => (
            <div key={m.id} className={`flex items-end gap-2 ${m.from === "USER" ? "justify-end" : "justify-start"}`}>
              {m.from === "BUDDY" && <Buddy size={32} />}
              <div className="space-y-1.5 max-w-[74%]">
                <div
                  className={`px-4 py-2.5 shadow-[0_1px_4px_rgba(0,0,0,0.08)] ${
                    m.from === "USER"
                      ? "bg-brand-500 text-white rounded-[20px_20px_4px_20px]"
                      : "bg-accent-100 text-foreground rounded-[4px_20px_20px_20px]"
                  }`}
                >
                  <p className="text-sm font-medium leading-snug">{m.text}</p>
                </div>
                {m.citations && m.citations.length > 0 && (
                  <div className="flex gap-1.5 flex-wrap">
                    {m.citations.map((c) => (
                      <Badge key={c.cardId} tone="brand">
                        📎 {c.title}
                      </Badge>
                    ))}
                  </div>
                )}
                {m.pending && (
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-accent-500 animate-pulse" />
                    <span className="text-xs font-semibold text-brand-700">사장님께 확인 중이에요</span>
                  </div>
                )}
              </div>
            </div>
          ))}
          {typing && (
            <div className="flex items-end gap-2">
              <Buddy size={32} />
              <div className="rounded-[4px_20px_20px_20px] px-4 py-3 bg-accent-100 shadow-[0_1px_4px_rgba(0,0,0,0.06)]">
                <div className="flex gap-1.5">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="w-2 h-2 rounded-full bg-border inline-block animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* 입력창 */}
        <form onSubmit={handleSubmit} className="shrink-0 bg-surface border-t border-border px-4 py-3 flex items-center gap-2.5">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="업무에 대해 질문해보세요..."
            className="flex-1 bg-background rounded-full px-4 py-2.5 text-sm font-medium text-foreground outline-none"
          />
          <button
            type="submit"
            disabled={!input.trim() || typing}
            className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 transition-all active:scale-90 ${
              input.trim() ? "bg-brand-500" : "bg-surface-muted"
            }`}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M2 8L14 2L8 14L7 9L2 8Z" fill="white" />
            </svg>
          </button>
        </form>
      </div>
    </div>
  );
}
