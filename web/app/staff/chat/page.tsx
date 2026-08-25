"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { Badge, Buddy } from "@/components/ui";
import { useApp } from "@/lib/store";
import { ApiError, askChat, listChat, type LearnChatCitation, type LearnChatMessage } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";

function mapCitations(citations: LearnChatCitation[] | undefined) {
  return (citations ?? []).map((c) => ({ cardId: String(c.card_id), title: c.title }));
}

function fromHistory(m: LearnChatMessage): ChatMessage {
  return {
    id: String(m.message_id),
    from: m.sender_type,
    text: m.content,
    pending: m.sender_type === "BUDDY" && m.answer_type === "NO_ANSWER",
    citations: mapCitations(m.citations),
    createdAt: m.created_at,
  };
}

export default function ChatPage() {
  const { state, dispatch } = useApp();
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const typingRef = useRef(false);
  typingRef.current = typing;
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state.chatMessages, typing]);

  useEffect(() => {
    if (!state.token) return;
    let cancelled = false;

    async function refresh(isFirst = false) {
      if (!isFirst && typingRef.current) return;
      try {
        const res = await listChat(state.token!);
        if (cancelled) return;
        dispatch({ type: "SET_CHAT_MESSAGES", messages: (res.messages ?? []).map(fromHistory) });
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.detail || "대화를 불러오지 못했어요" : "서버에 연결할 수 없습니다");
      } finally {
        if (!cancelled && isFirst) setLoaded(true);
      }
    }

    void refresh(true);
    const timer = window.setInterval(() => void refresh(false), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [state.token, dispatch]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || typing || !state.token) return;
    setInput("");
    setError(null);

    dispatch({
      type: "ADD_CHAT_MESSAGE",
      message: { id: `local-${Date.now()}`, from: "USER", text: question, createdAt: new Date().toISOString() },
    });
    setTyping(true);

    try {
      await askChat(question, state.token);
      const hist = await listChat(state.token);
      dispatch({ type: "SET_CHAT_MESSAGES", messages: (hist.messages ?? []).map(fromHistory) });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail || "답변을 가져오지 못했어요" : "서버에 연결할 수 없습니다");
    } finally {
      setTyping(false);
    }
  }

  const empty = loaded && state.chatMessages.length === 0;

  return (
    <div className="min-h-dvh w-full flex justify-center bg-background">
      <div className="w-full max-w-[480px] min-h-dvh flex flex-col bg-[#EEF4EF]">
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

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3.5">
          {empty && (
            <div className="flex items-end gap-2 justify-start">
              <Buddy size={32} />
              <div className="space-y-1.5 max-w-[74%]">
                <div className="px-4 py-2.5 shadow-[0_1px_4px_rgba(0,0,0,0.08)] bg-accent-100 text-foreground rounded-[4px_20px_20px_20px]">
                  <p className="text-sm font-medium leading-snug">
                    안녕하세요! 저는 Buddy예요 업무에 대해 궁금한 점이 있으면 편하게 물어보세요!
                  </p>
                </div>
              </div>
            </div>
          )}
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

        <form onSubmit={handleSubmit} className="shrink-0 bg-surface border-t border-border px-4 py-3 flex flex-col gap-2">
          {error && <p className="text-xs font-medium text-[#E57373] px-1">{error}</p>}
          <div className="flex items-center gap-2.5">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="업무에 대해 질문해보세요..."
              className="flex-1 bg-background rounded-full px-4 py-2.5 text-sm font-medium text-foreground outline-none"
            />
            <button
              type="submit"
              disabled={!input.trim() || typing || !loaded || !state.token}
              className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 transition-all active:scale-90 ${
                input.trim() && loaded ? "bg-brand-500" : "bg-surface-muted"
              }`}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M2 8L14 2L8 14L7 9L2 8Z" fill="white" />
              </svg>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
