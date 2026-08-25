"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Badge, Button, Input, Shell, TopBar } from "@/components/ui";
import { StaffTabBar } from "@/components/StaffTabBar";
import { useApp } from "@/lib/store";
import { retrieve } from "@/lib/api";
import { MOCK_KNOWLEDGE_SECTIONS } from "@/lib/mock";
import type { ChatMessage } from "@/lib/types";

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
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state.chatMessages, loading]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || loading) return;
    setInput("");

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      from: "USER",
      text: question,
      createdAt: new Date().toISOString(),
    };
    dispatch({ type: "ADD_CHAT_MESSAGE", message: userMsg });
    setLoading(true);

    // kind: "miss" 면 LLM을 호출하지 않는다 — 이 판정은 반드시 /reg/retrieve 를 거친다 (CLAUDE.md 불변식 5).
    const result = await retrieve(state.storeSlug, question).catch(() => simulateRetrieve(question));

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
          text: "아직 확인된 내용이 없어요. 사장님께 확인 중이에요 🙏",
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
    setLoading(false);
  }

  return (
    <Shell>
      <TopBar title="Buddy 채팅" />
      <div className="flex-1 overflow-y-auto px-4 pt-2 pb-4 flex flex-col gap-3">
        {state.chatMessages.map((m) => (
          <div
            key={m.id}
            className={`flex ${m.from === "USER" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                m.from === "USER"
                  ? "bg-brand-600 text-white rounded-br-sm"
                  : "bg-accent-100 text-foreground rounded-bl-sm"
              }`}
            >
              <p>{m.text}</p>
              {m.citations && m.citations.length > 0 && (
                <div className="flex gap-1.5 mt-2 flex-wrap">
                  {m.citations.map((c) => (
                    <Badge key={c.cardId} tone="brand">
                      📎 {c.title}
                    </Badge>
                  ))}
                </div>
              )}
              {m.pending && (
                <div className="mt-2">
                  <Badge tone="warn">🕐 사장님께 확인 중</Badge>
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-accent-100 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm text-muted">
              Buddy가 찾아보는 중…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={handleSubmit} className="flex gap-2 px-4 py-3 border-t border-border">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="궁금한 걸 물어보세요"
        />
        <Button type="submit" disabled={loading || !input.trim()}>
          전송
        </Button>
      </form>
      <StaffTabBar />
    </Shell>
  );
}
