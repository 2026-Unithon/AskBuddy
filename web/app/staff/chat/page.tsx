"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Buddy, Input } from "@/components/ui";
import { useApp } from "@/lib/store";
import { ApiError, askChat, type LearnChatCitation, type LearnChatMessage } from "@/lib/api";
import { chatQuery, queryKeys } from "@/lib/query";
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
  const { state } = useApp();
  const queryClient = useQueryClient();
  const chat = useQuery(chatQuery(state.token, state.storeId, state.userId));

  const [input, setInput] = useState("");
  const [lastFailedQuestion, setLastFailedQuestion] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const ask = useMutation({
    mutationFn: (question: string) => askChat(question, state.token!),
    onSuccess: () => {
      setLastFailedQuestion(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.chat(state.storeId, state.userId),
      });
    },
    onError: (_err, variables) => {
      // 실패 시 입력했던 질문을 복구할 수 있도록 보존
      setLastFailedQuestion(variables);
    },
  });

  const messages = (chat.data?.messages ?? []).map(fromHistory);
  const typing = ask.isPending;
  const error = chat.error ?? ask.error;
  const errorText =
    error instanceof ApiError
      ? error.detail || "답변을 가져오지 못했어요"
      : error
      ? "서버에 연결할 수 없습니다"
      : null;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, typing]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || typing || !state.token) return;
    setInput("");
    setLastFailedQuestion(null);
    ask.mutate(question);
  }

  function handleRestoreFailed() {
    if (lastFailedQuestion) {
      setInput(lastFailedQuestion);
      setLastFailedQuestion(null);
    }
  }

  const empty = !chat.isLoading && messages.length === 0;

  return (
    <div className="flex-1 flex flex-col w-full h-dvh bg-background relative">
      {/* 상단 컴팩트 헤더 */}
      <header className="shrink-0 bg-surface border-b border-border px-4 py-3 flex items-center justify-between shadow-xs">
        <div className="flex items-center gap-2.5">
          <Buddy size={36} />
          <div>
            <div className="flex items-center gap-1.5">
              <h1 className="text-sm font-bold text-brand-700">Buddy</h1>
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand-500 motion-safe:animate-pulse" />
            </div>
            <p className="text-xs text-muted">승인된 매장 지식 기반 답변</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {chat.isFetching && !chat.isLoading && !typing && (
            <span className="text-xs text-muted bg-surface-muted px-2 py-0.5 rounded-full">
              새 답변 확인 중…
            </span>
          )}
        </div>
      </header>

      {/* 대화 메시지 스크롤 영역 */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {/* 로딩 표시 */}
        {chat.isLoading && (
          <div className="py-8 text-center space-y-2">
            <p className="text-xs text-muted">이전 대화 기록을 불러오는 중…</p>
          </div>
        )}

        {/* 빈 대화 상태 */}
        {empty && (
          <div className="flex items-start gap-2.5 pt-2">
            <Buddy size={34} className="shrink-0 mt-0.5" />
            <div className="max-w-[78%] space-y-1">
              <div className="rounded-[4px_20px_20px_20px] px-4 py-3 bg-accent-100 text-foreground shadow-xs">
                <p className="text-base font-semibold leading-relaxed">
                  안녕하세요! 저는 매장 업무 도우미 Buddy예요. 🐥
                </p>
                <p className="mt-1 text-base text-foreground/80 leading-relaxed">
                  레시피, 마감 절차, 손님 응대 등 궁금한 점을 언제든 물어보세요. 승인된 매장 매뉴얼만 바탕으로 정확하게 알려드릴게요!
                </p>
              </div>
            </div>
          </div>
        )}

        {/* 대화 목록 */}
        {messages.map((m) => {
          const isUser = m.from === "USER";

          return (
            <div
              key={m.id}
              className={`flex items-end gap-2 ${isUser ? "justify-end" : "justify-start"}`}
            >
              {!isUser && <Buddy size={32} className="shrink-0 mb-1" />}
              <div className={`space-y-1.5 max-w-[78%] ${isUser ? "items-end" : "items-start"}`}>
                <div
                  className={`px-4 py-2.5 text-base leading-relaxed shadow-xs ${
                    isUser
                      ? "bg-brand-500 text-white rounded-[20px_20px_4px_20px] font-medium"
                      : "bg-accent-100 text-foreground rounded-[4px_20px_20px_20px]"
                  }`}
                >
                  <p className="whitespace-pre-wrap select-text">{m.text}</p>
                </div>

                {/* 인용된 지식 카드 목록 */}
                {m.citations && m.citations.length > 0 && (
                  <div className="flex gap-1 flex-wrap pt-0.5">
                    {m.citations.map((c) => (
                      <Badge key={c.cardId} tone="brand">
                        📎 {c.title}
                      </Badge>
                    ))}
                  </div>
                )}

                {/* 점주 확인 대기 상태 */}
                {m.pending && (
                  <div className="flex items-center gap-1.5 px-1 py-0.5">
                    <span className="h-2 w-2 rounded-full bg-accent-500 motion-safe:animate-pulse" />
                    <span className="text-xs font-bold text-brand-700">
                      사장님께 확인 중이에요
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* 전송 중인 질문 (낙관적 사용자 버블) */}
        {ask.isPending && ask.variables && (
          <div className="flex items-end gap-2 justify-end">
            <div className="max-w-[78%] rounded-[20px_20px_4px_20px] bg-brand-500 px-4 py-2.5 text-base text-white shadow-xs font-medium">
              <p className="whitespace-pre-wrap">{ask.variables}</p>
            </div>
          </div>
        )}

        {/* Buddy 답변 생성 중 로딩 애니메이션 */}
        {typing && (
          <div className="flex items-end gap-2">
            <Buddy size={32} className="shrink-0 mb-1" />
            <div className="rounded-[4px_20px_20px_20px] px-4 py-3 bg-accent-100 shadow-xs">
              <div className="flex gap-1.5 items-center">
                <span className="text-xs text-brand-700 font-medium mr-1">답변 찾는 중</span>
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="w-1.5 h-1.5 rounded-full bg-brand-500 inline-block motion-safe:animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* 하단 질문 입력 영역 (하단 3탭 바 바로 위에 배치되도록 mb-16 적용) */}
      <div className="shrink-0 mb-[calc(4rem+env(safe-area-inset-bottom,0px))] bg-surface border-t border-border px-3 py-2.5 shadow-sm">
        {/* 에러 및 질문 복원 배너 */}
        {errorText && (
          <div className="mb-2 flex items-center justify-between rounded-lg bg-danger-50 px-3 py-1.5 text-sm text-danger-700">
            <span className="font-medium truncate">{errorText}</span>
            {lastFailedQuestion && (
              <button
                type="button"
                onClick={handleRestoreFailed}
                className="ml-2 min-h-11 shrink-0 rounded-lg px-3 font-bold underline hover:bg-danger-100 hover:text-danger-900 active:scale-95"
              >
                질문 복구
              </button>
            )}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="업무에 대해 질문해보세요..."
            disabled={typing}
            aria-label="Buddy에게 보낼 질문"
            aria-invalid={Boolean(errorText)}
            className="min-w-0 flex-1 rounded-full bg-background font-medium"
          />
          <button
            type="submit"
            disabled={!input.trim() || typing || chat.isLoading || !state.token}
            aria-label="질문 전송"
            aria-busy={typing || undefined}
            className={`min-h-[44px] min-w-[44px] rounded-full flex items-center justify-center shrink-0 transition-all active:scale-90 ${
              input.trim() && !typing && !chat.isLoading
                ? "bg-brand-500 text-white shadow-xs hover:bg-brand-600"
                : "bg-surface-muted text-muted cursor-not-allowed opacity-60"
            }`}
          >
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
              <path d="M2 8L14 2L8 14L7 9L2 8Z" fill="currentColor" />
            </svg>
          </button>
        </form>
      </div>
    </div>
  );
}
