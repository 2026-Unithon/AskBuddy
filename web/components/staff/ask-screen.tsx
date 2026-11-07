"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { SuggestedQuestions } from "@/components/staff/suggested-questions";
import {
  AnswerBubble,
  AskBar,
  BackButton,
  Button,
  Chip,
  ErrorInline,
  QuestionBubble,
  RefreshingHint,
  Screen,
  Skeleton,
} from "@/components/kit";
import { ApiError, apiErrorMessage } from "@/lib/api";
import { rCitationQuery, rHistoryQuery, rKeys, rSessionsQuery } from "@/lib/query";
import { useRPublicationRefresh } from "@/lib/r-publication-refresh";
import { rAsk, rCreateSession, type RChatInput, type RMessage } from "@/lib/r-v2-api";
import { useApp } from "@/lib/store";
import { CitationOrigin } from "@/components/citation-origin";

const KNOWLEDGE_CHIP: Record<string, string> = {
  PUBLISHED: "공개된 매장 카드에 반영됐어요",
  LINKED: "매장 카드와 같은 내용이에요",
};

// 새 답변 경로가 꺼져 있으면(V2_UNAVAILABLE) 서버가 준 안내를 그대로 보여준다
function loadErrorMessage(error: unknown) {
  if (error instanceof ApiError && error.code === "V2_UNAVAILABLE" && error.detail) return error.detail;
  return apiErrorMessage(error, "대화를 불러오지 못했어요.");
}

/** A5 물어보기 · A6 답 도착. R v2 대화(/learn/v2) 위에 Figma 말풍선을 입힌다. */
export function AskScreen() {
  const { state } = useApp();
  const router = useRouter();
  const client = useQueryClient();
  const params = useSearchParams();
  const sessionParam = params.get("session_id");
  // 레시피 보기의 "이 레시피에 대해 물어보기"는 ?q= 로 질문 앞부분을 채워 보낸다
  const [input, setInput] = useState(() => params.get("q") ?? "");
  const bottomRef = useRef<HTMLDivElement>(null);

  const sessions = useQuery(rSessionsQuery(state.token, state.storeId, state.userId));
  // 딥링크(답 도착 알림)가 가리키는 대화를 먼저, 없으면 가장 최근 대화를 이어 쓴다
  const session = sessionParam ?? sessions.data?.sessions[0]?.session_id ?? null;
  const history = useInfiniteQuery(rHistoryQuery(state.token, state.storeId, state.userId, session));
  const messages: RMessage[] = history.data ? [...history.data.pages].reverse().flatMap((page) => page.messages) : [];

  useRPublicationRefresh(
    state.storeId,
    messages
      .filter((m) => m.knowledge_status && ["PUBLISHED", "LINKED"].includes(m.knowledge_status))
      .map((m) => `${m.owner_answer_id}:${m.revision}:${m.knowledge_status}`)
      .join("|")
  );

  const ask = useMutation({
    mutationFn: async (body: Omit<RChatInput, "session_id">) => {
      let target = session;
      if (!target) {
        const created = await rCreateSession(state.token!, crypto.randomUUID());
        target = created.session_id;
        await client.invalidateQueries({ queryKey: rKeys.sessions(state.storeId, state.userId) });
        router.replace(`/staff/ask?session_id=${encodeURIComponent(target)}`);
      }
      await rAsk(state.token!, { ...body, session_id: target });
      return target;
    },
    onSuccess: async (target, body) => {
      if (!body.option && !body.policy_receipt_id) setInput("");
      await client.invalidateQueries({ queryKey: rKeys.history(state.storeId, state.userId, target) });
    },
  });

  const lastId = messages.at(-1)?.message_id;
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [lastId, ask.isPending]);

  const busy = ask.isPending;
  // 처음 불러온 대화는 '이미 본 것'. 그 뒤 새로 생긴 버디 답만 타이핑으로 보인다(s04c).
  // 서버 데이터 복사가 아니라 화면 연출용 표시(어떤 id 를 처음 봤는지)만 둔다
  const [known, setKnown] = useState<Set<string> | null>(null);
  const firstReady = !sessions.isLoading && (!session || Boolean(history.data));
  if (known === null && firstReady) setKnown(new Set(messages.map((m) => m.message_id)));
  const loading = sessions.isLoading || (Boolean(session) && history.isLoading);
  const loadError = sessions.error ?? history.error;

  return (
    <Screen
      footer={
        <div className="flex flex-col gap-2">
          {ask.error && (
            <ErrorInline
              message={
                ask.error instanceof ApiError && ask.error.status === 429
                  ? "질문이 많아 잠시 쉬고 있어요. 잠시 후 다시 보내 주세요. 입력 내용은 그대로 두었어요."
                  : apiErrorMessage(ask.error, "질문이 전달되지 않았어요. 입력 내용은 그대로 두었어요.")
              }
              onRetry={() => ask.variables && ask.mutate(ask.variables)}
              retrying={busy}
            />
          )}
          {/* 대화 목록을 불러오기 전에 누르면 새 대화가 생기므로 다 불러온 뒤에만 보인다 */}
          {!busy && !loading && !input.trim() && !loadError && (
            <SuggestedQuestions onPick={(question) => ask.mutate({ request_id: crypto.randomUUID(), question })} />
          )}
          <AskBar
            value={input}
            onChange={(value) => {
              setInput(value);
              if (ask.isError) ask.reset();
            }}
            onSubmit={() => ask.mutate({ request_id: crypto.randomUUID(), question: input })}
            submitting={busy}
            disabled={loading || Boolean(loadError)}
          />
        </div>
      }
    >
      <BackButton parent="/staff" />
      <p className="text-[20px] font-black leading-[1.45] tracking-[-0.4px] text-ink">버디</p>

      {loading && (
        <>
          <Skeleton className="ml-auto h-11 w-2/3" />
          <Skeleton className="h-20 w-4/5" />
        </>
      )}
      {loadError && (
        <ErrorInline
          message={loadErrorMessage(loadError)}
          onRetry={() => void (sessions.error ? sessions.refetch() : history.refetch())}
          retrying={sessions.isRefetching || history.isRefetching}
        />
      )}
      {history.hasNextPage && (
        <Button variant="secondary" loading={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>
          이전 대화 보기
        </Button>
      )}
      {!loading && !loadError && messages.length === 0 && !busy && (
        <AnswerBubble>{"매장 카드에 있는 내용으로 답해 드려요.\n메뉴 이름과 HOT, ICE 같은 규격을 함께 물어보면 더 정확해요."}</AnswerBubble>
      )}

      <ol className="flex flex-col gap-4" aria-live="polite">
        {messages.map((message) => (
          <li key={message.message_id}>
            <MessageView
              message={message}
              isLast={message.message_id === lastId}
              animate={known !== null && !known.has(message.message_id)}
              busy={busy}
              onOption={(option, context) =>
                ask.mutate({
                  request_id: crypto.randomUUID(),
                  question: option,
                  option,
                  context_id: context.context_id,
                  context_revision: context.context_revision,
                })
              }
              onPolicyConfirm={(question, receiptId) =>
                ask.mutate({ request_id: crypto.randomUUID(), question, policy_receipt_id: receiptId })
              }
            />
          </li>
        ))}
      </ol>
      {busy && ask.variables && !ask.variables.option && !ask.variables.policy_receipt_id && (
        <div className="flex flex-col gap-4" aria-live="polite">
          <QuestionBubble pending>{ask.variables.question}</QuestionBubble>
          <div role="status" aria-label="버디가 생각 중이에요" data-thinking="" className="flex gap-1.5 self-start rounded-[18px] bg-surface px-4 py-3 shadow-card">
            {[0, 1, 2].map((i) => (
              <span key={i} className="size-2 rounded-full bg-ink-muted motion-safe:animate-bounce" style={{ animationDelay: `${i * 150}ms` }} />
            ))}
          </div>
        </div>
      )}
      <RefreshingHint active={history.isRefetching && !busy} />
      <div ref={bottomRef} />
    </Screen>
  );
}

function MessageView({
  message,
  isLast,
  animate = false,
  busy,
  onOption,
  onPolicyConfirm,
}: {
  message: RMessage;
  isLast: boolean;
  animate?: boolean;
  busy: boolean;
  onOption: (option: string, context: { context_id: string; context_revision: number }) => void;
  onPolicyConfirm: (question: string, receiptId: string) => void;
}) {
  if (message.sender === "USER") return <QuestionBubble>{message.content}</QuestionBubble>;

  const response = message.response;
  // 점주 원문 답 (A6). 카드 반영은 별도 상태라 공개·연결됐을 때만 칩을 단다
  if (message.owner_answer_id) {
    const chip = message.knowledge_availability === "UNAVAILABLE" ? "현재 공개된 카드가 없어요"
      : message.knowledge_availability === "CHANGED" ? "이후 카드 내용이 바뀌었어요"
      : message.knowledge_availability === "CURRENT" ? KNOWLEDGE_CHIP[message.knowledge_status ?? ""] : undefined;
    return (
      <AnswerBubble chips={<>{<Chip tone="neutral">사장님 답</Chip>}{chip && <Chip>{chip}</Chip>}</>}>
        {message.content}
      </AnswerBubble>
    );
  }

  const citations = message.receipt_id ? response?.citations ?? [] : [];
  const clarify = response?.action === "CLARIFY" && isLast && response.context_id && message.context_revision !== null;
  const policy = response?.action === "SAFE_ROUTE" && isLast && message.receipt_id && message.original_question;

  return (
    <AnswerBubble
      chips={
        <>
          {citations.map((citation, index) => (
            <CitationChip
              key={`${citation.card_version_id}-${index}`}
              receipt={message.receipt_id!}
              order={index + 1}
              broken={citation.source_availability !== "AVAILABLE"}
            />
          ))}
          {response?.action === "ESCALATE" && response.pending_id && <EscalateSteps />}
        </>
      }
      actions={
        clarify ? (
          response.allowed_options.map((option) => (
            <OptionButton
              key={option}
              disabled={busy}
              onClick={() =>
                onOption(option, { context_id: response.context_id!, context_revision: message.context_revision! })
              }
            >
              {option}
            </OptionButton>
          ))
        ) : policy ? (
          <OptionButton testId="r-policy-confirm" disabled={busy} onClick={() => onPolicyConfirm(message.original_question!, message.receipt_id!)}>
            사장님께 확인 요청
          </OptionButton>
        ) : undefined
      }
    >
      {animate ? <Typewriter text={message.content} /> : message.content}
    </AnswerBubble>
  );
}

/** 사장님께 넘긴 답의 단계(s04b). 앞 두 단계는 끝났고, 마지막은 답을 기다린다. */
function EscalateSteps() {
  const steps = ["질문을 받았어요", "사장님께 보냈어요", "답 오면 알려드려요"];
  return (
    <div role="list" aria-label="사장님께 확인 중" className="flex w-full flex-col gap-1.5 rounded-[14px] bg-background px-3 py-2.5">
      {steps.map((step, i) => {
        const waiting = i === steps.length - 1;
        return (
          <div role="listitem" key={step} className={`flex items-center gap-2 text-[13px] ${waiting ? "font-bold text-primary" : "text-ink-muted"}`}>
            {waiting ? (
              <span aria-hidden className="size-2 rounded-full bg-primary motion-safe:animate-pulse" />
            ) : (
              <span aria-hidden className="flex size-4 items-center justify-center rounded-full bg-primary text-[10px] text-white">✓</span>
            )}
            {step}
          </div>
        );
      })}
    </div>
  );
}

const TYPE_MS = 300;

/** 다 받은 답을 0.3초에 걸쳐 타이핑하듯 보인다(s04c). 움직임 줄이기 설정이면 바로 전부. */
function Typewriter({ text }: { text: string }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const id = requestAnimationFrame(() => setShown(text.length));
      return () => cancelAnimationFrame(id);
    }
    const start = performance.now();
    let id = 0;
    const tick = (now: number) => {
      const next = Math.min(text.length, Math.ceil(((now - start) / TYPE_MS) * text.length));
      setShown(next);
      if (next < text.length) id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [text]);
  if (shown >= text.length) return <>{text}</>;
  return (
    <span data-typing="">
      {text.slice(0, shown)}
      <span className="sr-only">{text.slice(shown)}</span>
    </span>
  );
}

function OptionButton({
  children,
  onClick,
  disabled,
  testId,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      className="min-h-11 rounded-full border-[1.5px] border-primary-weak bg-surface px-4 text-[14px] font-bold text-primary disabled:opacity-50"
    >
      {children}
    </button>
  );
}

/** 근거 카드 칩. 누르면 그 카드의 승인된 내용을 펼친다. */
function CitationChip({ receipt, order, broken }: { receipt: string; order: number; broken: boolean }) {
  const { state } = useApp();
  const [open, setOpen] = useState(false);
  const citation = useQuery(rCitationQuery(state.token, state.storeId, state.userId, receipt, order, open));
  return (
    <div className="flex w-full flex-col gap-1.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="min-h-8 self-start text-[12px] leading-[1.45] text-ink-muted underline underline-offset-2"
      >
        {citation.data ? `근거 ${citation.data.title}` : "근거 카드"}
        {broken && " (인용 끊김)"}
      </button>
      {open && (
        <div className="rounded-[14px] bg-background px-3 py-2 text-[13px] leading-[1.45] text-ink">
          {citation.isLoading && <span className="text-ink-muted">카드를 불러오고 있어요</span>}
          {citation.error && (
            <ErrorInline message={apiErrorMessage(citation.error, "카드를 불러오지 못했어요.")} onRetry={() => void citation.refetch()} />
          )}
          {citation.data && (
            <>
              <p className="whitespace-pre-wrap">{citation.data.text}</p>
              <CitationOrigin citation={citation.data} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
