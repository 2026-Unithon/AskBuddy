"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  AnswerBubble,
  AskBar,
  BackButton,
  Button,
  Caption,
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

const KNOWLEDGE_CHIP: Record<string, string> = {
  PUBLISHED: "새 카드 · 방금 추가했어요",
  LINKED: "매장 카드와 같은 내용이에요",
};

/** A5 물어보기 · A6 답 도착. R v2 대화(/learn/v2) 위에 Figma 말풍선을 입힌다. */
export function AskScreen() {
  const { state } = useApp();
  const router = useRouter();
  const client = useQueryClient();
  const params = useSearchParams();
  const sessionParam = params.get("session_id");
  const [input, setInput] = useState("");
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
      <BackButton href="/staff" />
      <p className="text-[20px] font-black leading-[1.45] tracking-[-0.4px] text-ink">버디</p>

      {loading && (
        <>
          <Skeleton className="ml-auto h-11 w-2/3" />
          <Skeleton className="h-20 w-4/5" />
        </>
      )}
      {loadError && (
        <ErrorInline
          message={apiErrorMessage(loadError, "대화를 불러오지 못했어요.")}
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
        <AnswerBubble>{"매장 카드에 있는 내용으로 답해 드려요.\n메뉴 이름과 HOT·ICE 같은 규격을 함께 물어보면 더 정확해요."}</AnswerBubble>
      )}

      <ol className="flex flex-col gap-4" aria-live="polite">
        {messages.map((message) => (
          <li key={message.message_id}>
            <MessageView
              message={message}
              isLast={message.message_id === lastId}
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
        {busy && ask.variables && !ask.variables.option && !ask.variables.policy_receipt_id && (
          <li className="flex flex-col gap-4">
            <QuestionBubble pending>{ask.variables.question}</QuestionBubble>
            <Caption>매장 카드를 확인하고 있어요</Caption>
          </li>
        )}
      </ol>
      <RefreshingHint active={history.isRefetching && !busy} />
      <div ref={bottomRef} />
    </Screen>
  );
}

function MessageView({
  message,
  isLast,
  busy,
  onOption,
  onPolicyConfirm,
}: {
  message: RMessage;
  isLast: boolean;
  busy: boolean;
  onOption: (option: string, context: { context_id: string; context_revision: number }) => void;
  onPolicyConfirm: (question: string, receiptId: string) => void;
}) {
  if (message.sender === "USER") return <QuestionBubble>{message.content}</QuestionBubble>;

  const response = message.response;
  // 점주 원문 답 (A6). 카드 반영은 별도 상태라 공개·연결됐을 때만 칩을 단다
  if (message.owner_answer_id) {
    const chip = KNOWLEDGE_CHIP[message.knowledge_status ?? ""];
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
          {response?.action === "ESCALATE" && response.pending_id && <Chip>확인 중 · 답 오면 알려드려요</Chip>}
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
          <OptionButton disabled={busy} onClick={() => onPolicyConfirm(message.original_question!, message.receipt_id!)}>
            사장님께 확인 요청
          </OptionButton>
        ) : undefined
      }
    >
      {message.content}
    </AnswerBubble>
  );
}

function OptionButton({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
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
        className="self-start rounded-full bg-empty px-2.5 py-1.5 text-[12px] font-medium leading-[1.45] text-primary"
      >
        {citation.data ? `카드 · ${citation.data.title}` : `근거 카드 ${order}`}
        {broken && " · 인용 끊김"}
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
              {citation.data.owner_answer_id && <p className="mt-1 text-ink-muted">출처 · 사장님 답</p>}
              {citation.data.source_availability !== "AVAILABLE" && (
                <p className="mt-1 text-ink-muted">원본 자료는 지워졌어요. 승인된 내용은 그대로 남아 있어요.</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
