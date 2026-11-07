"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useNavHistory } from "@/lib/nav-history";
import { useState } from "react";
import {
  BackButton,
  Button,
  ButtonLink,
  Caption,
  Chip,
  ComposerTool,
  Empty,
  ErrorInline,
  Icon,
  PageHeader,
  Screen,
  Skeleton,
  Surface,
  focusRing,
} from "@/components/kit";
import { ApiError, apiErrorMessage } from "@/lib/api";
import { rDetailQuery, rKeys, rPendingQuery } from "@/lib/query";
import { useRPublicationRefresh } from "@/lib/r-publication-refresh";
import { rOwnerRetry, type RPending } from "@/lib/r-v2-api";
import { useApp } from "@/lib/store";
import { AnswerAttachmentHints, AnswerAttachmentRows, useAnswerAttachments, type AnswerAttachments } from "@/components/owner/owner-answer-attachments";
import { QuestionAnswerForm } from "@/components/owner/question-answer-form";

type Answer = RPending["answers"][number];

const SLOT_LABEL: Record<string, string> = { entity: "대상", predicate: "물어본 내용", temperature: "온도", size: "크기" };

// O7 답하기 → O8 카드로 남았어요. 원문 전달과 카드 반영은 다른 단계다 (MVP §13-2).
export default function OwnerAnswerPage() {
  const { pendingId } = useParams<{ pendingId: string }>();
  const { state } = useApp();
  const router = useRouter();
  const { markReplace } = useNavHistory();
  const detail = useQuery(rDetailQuery(state.token, state.storeId, state.userId, pendingId));
  const waiting = useInfiniteQuery(rPendingQuery(state.token, state.storeId, state.userId, "WAITING"));
  const [sent, setSent] = useState(false);
  const [showAsked, setShowAsked] = useState(false);
  const questionId = /^\d+$/.test(pendingId) ? Number(pendingId) : null;
  const files = useAnswerAttachments(questionId ?? 0);

  const latest = detail.data?.answers.at(-1);
  useRPublicationRefresh(
    state.storeId,
    detail.data?.answers
      .filter((a) => ["PUBLISHED", "LINKED"].includes(a.knowledge_status))
      .map((a) => `${a.owner_answer_id}:${a.revision}:${a.knowledge_status}`)
      .join("|") ?? ""
  );

  if (detail.isLoading) {
    return (
      <Screen>
        <BackButton parent="/owner" label="오늘 매장" />
        <Skeleton className="h-20" />
        <Skeleton className="h-8 w-1/2" />
      </Screen>
    );
  }

  if (detail.error || !detail.data) {
    const missing = detail.error instanceof ApiError && [403, 404].includes(detail.error.status);
    return (
      <Screen>
        <BackButton parent="/owner" label="오늘 매장" />
        {missing ? (
          <Empty title="이 질문을 볼 수 없어요" description="이미 정리됐거나 다른 매장의 질문이에요." action={<ButtonLink href="/owner">오늘 매장으로</ButtonLink>} />
        ) : (
          <ErrorInline
            message={apiErrorMessage(detail.error, "질문을 불러오지 못했어요.")}
            onRetry={() => void detail.refetch()}
            retrying={detail.isRefetching}
          />
        )}
      </Screen>
    );
  }

  const data = detail.data;
  const first = data.occurrences[0];
  const title = first?.original_question ?? data.question ?? "직원 질문";
  const askedCount = data.occurrences.length;
  const slots = Object.entries(first?.resolved_query.confirmed_slots ?? {});
  const others = (waiting.data?.pages.flatMap((page) => page.questions) ?? []).filter((q) => q.status === "WAITING" && q.pending_id !== pendingId);

  // o10c: 보낸 순간. 체크가 튀어나오고 다음 질문으로 이어 간다
  if (sent) {
    return (
      <Screen
        footer={
          others.length > 0 ? (
            <Button
              onClick={() => {
                markReplace();
                router.replace(`/owner/questions/${others[0].pending_id}`);
                setSent(false);
              }}
            >
              다음 질문 {others.length}개
            </Button>
          ) : (
            <ButtonLink href="/owner">오늘 매장으로</ButtonLink>
          )
        }
      >
        <BackButton parent="/owner" />
        <div className="flex flex-1 flex-col items-center justify-center gap-3">
          <span className="flex size-16 items-center justify-center rounded-full bg-primary text-white animate-[check-pop_var(--dur-base)_var(--ease-spring)]">
            <Icon name="check" size={32} />
          </span>
          <p className="text-[24px] font-black text-ink">답을 보냈어요</p>
          <p className="text-[14px] text-ink-muted">물어본 직원에게 바로 전해요. 카드로도 남겨요.</p>
        </div>
      </Screen>
    );
  }

  if (latest && latest.knowledge_status === "PUBLISHED" && latest.knowledge_availability === "CURRENT") {
    return <PublishedResult question={title} answer={latest.answer} more={questionId !== null ? <MoreAttachments files={files} /> : null} />;
  }

  return (
    <Screen
      footer={
        latest ? (
          <>
            {questionId !== null && <MoreAttachments files={files} />}
            <ButtonLink href="/owner">오늘 매장으로</ButtonLink>
          </>
        ) : (
          <>
            {files.input}
            <QuestionAnswerForm
              pendingId={pendingId}
              onSent={() => setSent(true)}
              tools={questionId !== null && files.caps.data ? <ComposerTool icon="clip" label="파일" onClick={files.open} /> : undefined}
              attachments={<AnswerAttachmentRows files={files} />}
              below={<AnswerAttachmentHints files={files} />}
            />
          </>
        )
      }
    >
      <BackButton parent="/owner" />
      <PageHeader title={title} />
      <div className="-mt-2 flex flex-wrap items-center gap-2">
        <Caption className="text-[13px]">{askedCount > 1 ? `직원이 ${askedCount}번 물어봤어요` : "직원이 물어본 질문"}</Caption>
        {askedCount > 1 && (
          <button type="button" aria-expanded={showAsked} onClick={() => setShowAsked((v) => !v)} className="min-h-8 text-[13px] font-bold text-primary underline-offset-4 hover:underline">
            물어본 말 보기
          </button>
        )}
      </div>
      {showAsked && (
        <ul className="flex flex-col gap-1.5 rounded-[14px] bg-surface px-4 py-3 shadow-card">
          {data.occurrences.map((occurrence) => (
            <li key={occurrence.receipt_id} className="text-[14px] text-ink [word-break:keep-all]">
              {occurrence.original_question}
            </li>
          ))}
        </ul>
      )}
      {slots.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {slots.map(([slot, value]) => (
            <Chip key={slot} tone="neutral">
              {SLOT_LABEL[slot] ?? "조건"} {value}
            </Chip>
          ))}
        </div>
      )}
      {latest && <AnswerStatus answer={latest} pendingId={pendingId} />}
      {data.legacy_answers?.map((previous) => <Surface key={previous.owner_answer_id} className="space-y-2 p-4">
        <Caption>이전에 전달한 답변. 카드 반영 상태는 카드에서 확인해 주세요</Caption>
        <p className="whitespace-pre-wrap">{previous.answer}</p>
      </Surface>)}
    </Screen>
  );
}

/** 답한 뒤에도 사진·파일을 더 붙인다(서버가 보충 작업을 만든다). 붙인 줄과 종류 칩은 같은 모양. */
function MoreAttachments({ files }: { files: AnswerAttachments }) {
  if (!files.caps.data) return null;
  return (
    <div className="flex flex-col gap-2">
      {files.input}
      <AnswerAttachmentRows files={files} />
      <AnswerAttachmentHints files={files} />
      <button type="button" onClick={files.open} className={`flex min-h-11 items-center justify-center gap-1.5 rounded-[12px] border-[1.5px] border-dashed border-empty text-[14px] font-bold text-primary ${focusRing}`}>
        <Icon name="clip" size={14} />
        사진, 파일 더 붙이기
      </button>
    </div>
  );
}

/** 저장된 답 + 카드 반영 상태. PUBLISHED 는 O8 전용 화면으로 따로 그린다. */
function AnswerStatus({ answer, pendingId }: { answer: Answer; pendingId: string }) {
  const status: Record<string, { chip: string; tone: "brand" | "warn" | "danger" | "neutral"; text: string }> = {
    PENDING: { chip: "카드로 정리하는 중", tone: "neutral", text: "답은 물어본 직원에게 전달했어요. 카드로 정리하고 있어요." },
    LINKED: { chip: "이미 있는 카드와 같아요", tone: "brand", text: "답은 직원에게 전달했어요. 같은 내용의 카드가 있어서 새로 만들지 않았어요." },
    REVIEW: { chip: "확인이 필요해요", tone: "warn", text: "기존 카드와 다른 부분이 있어요. 공개하기 전에 카드에서 확인해 주세요." },
    FAILED: { chip: "카드 반영 실패", tone: "danger", text: "답은 직원에게 전달했어요. 카드로 정리하지는 못했어요." },
    DISMISSED: { chip: "제안 닫힘", tone: "neutral", text: "답은 직원에게 전달했고, 이 제안은 공개하지 않고 닫았어요." },
    CHANGED: { chip: "카드가 바뀌었어요", tone: "neutral", text: "이전에 반영한 답변이에요. 현재 카드에는 이후 변경된 내용이 있어요." },
    UNAVAILABLE: { chip: "현재 공개된 카드가 없어요", tone: "neutral", text: "직원에게 전달한 답은 남아 있어요. 이 답의 카드 반영 상태는 카드에서 다시 확인해 주세요." },
    PUBLISHED: { chip: "이전에 카드에 반영했어요", tone: "neutral", text: "당시 반영한 답변이에요. 현재 공개 상태를 확인해 주세요." },
  };
  const dismissed = answer.proposal_status === "DISMISSED";
  const unavailable = answer.knowledge_availability === "UNAVAILABLE";
  const view = status[dismissed ? "DISMISSED" : unavailable ? "UNAVAILABLE" : answer.knowledge_availability === "CHANGED" ? "CHANGED" : answer.knowledge_status] ?? status.PENDING;
  return (
    <Surface className="flex flex-col gap-2 px-[18px] py-4">
      {/* 답 고치기는 없다(o11b). 고치기는 카드에서 */}
      <div className="flex items-center gap-2">
        <Chip tone={view.tone}>{view.chip}</Chip>
      </div>
      <p className="whitespace-pre-wrap text-[15px] leading-[1.45] tracking-[-0.15px] text-ink">{answer.answer}</p>
      <Caption>{view.text}</Caption>
      {answer.knowledge_status === "REVIEW" && !dismissed && !unavailable && <ButtonLink href="/owner/cards/proposals" variant="secondary">제안 확인하기</ButtonLink>}
      {answer.knowledge_status === "FAILED" && answer.retry_available && answer.event_id && (
        <RetryKnowledge eventId={answer.event_id} pendingId={pendingId} />
      )}
    </Surface>
  );
}

function RetryKnowledge({ eventId, pendingId }: { eventId: string; pendingId: string }) {
  const { state } = useApp();
  const client = useQueryClient();
  // 실패한 재처리 요청을 다시 보낼 때도 같은 request_id 를 쓴다(멱등)
  const [requestId] = useState(() => crypto.randomUUID());
  const retry = useMutation({
    // API 가 재처리 사유를 요구한다. 점주에게 사유를 쓰게 하지 않고 고정 사유를 남긴다.
    mutationFn: () => rOwnerRetry(state.token!, eventId, { request_id: requestId, reason: "점주가 화면에서 다시 시도" }),
    onSuccess: () => client.invalidateQueries({ queryKey: rKeys.detail(state.storeId, state.userId, pendingId) }),
  });
  if (retry.error) {
    return (
      <ErrorInline message={apiErrorMessage(retry.error, "다시 시도하지 못했어요.")} onRetry={() => retry.mutate()} retrying={retry.isPending} />
    );
  }
  return (
    <button
      type="button"
      onClick={() => retry.mutate()}
      disabled={retry.isPending || retry.isSuccess}
      className="min-h-11 self-start rounded-full bg-background px-4 text-[13px] font-bold text-primary disabled:opacity-50"
    >
      {retry.isPending ? "다시 정리하는 중" : retry.isSuccess ? "다시 정리를 요청했어요" : "카드로 다시 정리하기"}
    </button>
  );
}

/** O8: 점주 답이 새 카드로 공개됐을 때(o11a). 성공은 초록, 체크가 스프링으로 튀어나온다. 답 고치기는 없다(o11b). */
function PublishedResult({ question, answer, more }: { question: string; answer: string; more: React.ReactNode }) {
  return (
    <Screen
      footer={
        <>
          {more}
          <ButtonLink href="/owner">오늘 매장으로</ButtonLink>
        </>
      }
    >
      <BackButton parent="/owner" />
      <div className="flex flex-1 flex-col items-center justify-center gap-4">
        <div className="relative flex w-full flex-col gap-1.5 rounded-[20px] border-[1.5px] border-primary bg-surface px-[18px] py-4 shadow-card">
          <span data-tone="success" className="absolute right-4 top-3.5 rounded-full bg-primary px-2.5 py-1 text-[12px] font-bold tracking-[-0.24px] text-white">
            공개됨
          </span>
          <p className="pr-16 text-[17px] font-bold leading-[1.45] tracking-[-0.34px] text-ink [word-break:keep-all]">{question}</p>
          <p className="whitespace-pre-wrap text-[14px] leading-[1.45] tracking-[-0.14px] text-ink-muted">{answer}</p>
        </div>
        <span className="flex size-12 items-center justify-center rounded-full bg-primary text-white animate-[check-pop_var(--dur-base)_var(--ease-spring)]">
          <Icon name="check" size={24} />
        </span>
        <p className="text-center text-[24px] font-black leading-[1.45] tracking-[-0.48px] text-ink">카드로 남았어요</p>
        <p className="text-center text-[14px] leading-[1.45] tracking-[-0.14px] text-ink-muted">답변 내용이 공개 카드에 반영됐어요</p>
      </div>
    </Screen>
  );
}
