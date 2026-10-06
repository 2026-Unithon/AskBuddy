"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import {
  BackButton,
  ButtonLink,
  Caption,
  Chip,
  Composer,
  Empty,
  ErrorInline,
  PageHeader,
  Screen,
  Skeleton,
  Surface,
  TextButton,
} from "@/components/kit";
import { ApiError, apiErrorMessage } from "@/lib/api";
import { bootstrapQuery, rDetailQuery, rKeys } from "@/lib/query";
import { useRPublicationRefresh } from "@/lib/r-publication-refresh";
import { rOwnerAnswer, rOwnerRetry, type RPending } from "@/lib/r-v2-api";
import { useApp } from "@/lib/store";

type Answer = RPending["answers"][number];

const SLOT_LABEL: Record<string, string> = { entity: "대상", predicate: "물어본 내용", temperature: "온도", size: "크기" };

// O7 답하기 → O8 카드로 남았어요. 원문 전달과 카드 반영은 다른 단계다 (MVP §13-2).
export default function OwnerAnswerPage() {
  const { pendingId } = useParams<{ pendingId: string }>();
  const { state } = useApp();
  const client = useQueryClient();
  const detail = useQuery(rDetailQuery(state.token, state.storeId, state.userId, pendingId));
  const [answer, setAnswer] = useState("");
  const [editing, setEditing] = useState(false);

  const latest = detail.data?.answers.at(-1);
  useRPublicationRefresh(
    state.storeId,
    detail.data?.answers
      .filter((a) => ["PUBLISHED", "LINKED"].includes(a.knowledge_status))
      .map((a) => `${a.owner_answer_id}:${a.revision}:${a.knowledge_status}`)
      .join("|") ?? ""
  );

  const submit = useMutation({
    mutationFn: (body: { request_id: string; answer: string; expected_revision: number }) =>
      rOwnerAnswer(state.token!, pendingId, body),
    onSuccess: async () => {
      setAnswer("");
      setEditing(false);
      await Promise.all([
        client.invalidateQueries({ queryKey: rKeys.pending(state.storeId, state.userId) }),
        client.invalidateQueries({ queryKey: bootstrapQuery(state.token, state.userId, state.storeId).queryKey }),
      ]);
    },
  });

  if (detail.isLoading) {
    return (
      <Screen>
        <BackButton href="/owner" label="오늘 매장" />
        <Skeleton className="h-20" />
        <Skeleton className="h-8 w-1/2" />
      </Screen>
    );
  }

  if (detail.error || !detail.data) {
    const missing = detail.error instanceof ApiError && [403, 404].includes(detail.error.status);
    return (
      <Screen>
        <BackButton href="/owner" label="오늘 매장" />
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
  const title = first?.original_question ?? "직원 질문";
  const askedCount = data.occurrences.length;
  const slots = Object.entries(first?.resolved_query.confirmed_slots ?? {});
  const showComposer = !latest || editing;

  const send = () =>
    submit.mutate({ request_id: crypto.randomUUID(), answer, expected_revision: latest?.revision ?? 0 });

  if (latest && !editing && latest.knowledge_status === "PUBLISHED") {
    return <PublishedResult question={title} answer={latest.answer} onEdit={() => setEditing(true)} />;
  }

  return (
    <Screen
      footer={
        showComposer ? (
          <div className="flex flex-col gap-2">
            {submit.error && (
              <ErrorInline
                message={
                  submit.error instanceof ApiError && submit.error.status === 409
                    ? "그사이 답이 바뀌었어요. 최신 답을 확인한 뒤 다시 보내 주세요. 입력 내용은 그대로 두었어요."
                    : apiErrorMessage(submit.error, "답이 전달되지 않았어요. 입력 내용은 그대로 두었어요.")
                }
                onRetry={() => (submit.error instanceof ApiError && submit.error.status === 409 ? void detail.refetch() : send())}
                retrying={submit.isPending || detail.isRefetching}
              />
            )}
            <Composer
              label="직원에게 보낼 답"
              value={answer}
              onChange={(value) => {
                setAnswer(value);
                if (submit.isError) submit.reset();
              }}
              onSubmit={send}
              submitting={submit.isPending}
              submitLabel={latest ? "고쳐 보내기" : "넣기"}
              placeholder={latest ? "바뀐 내용을 적어 주세요" : "직원에게 보낼 답을 적어 주세요"}
            />
            {editing && (
              <TextButton onClick={() => setEditing(false)} className="self-center">
                고치지 않기
              </TextButton>
            )}
          </div>
        ) : (
          <ButtonLink href="/owner">오늘 매장으로</ButtonLink>
        )
      }
    >
      <BackButton href="/owner" label="오늘 매장" />
      <PageHeader title={title} />
      <Caption className="-mt-2 text-[13px]">
        {askedCount > 1 ? `직원이 ${askedCount}번 물어봤어요` : "직원이 물어본 질문"}
      </Caption>
      {slots.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {slots.map(([slot, value]) => (
            <Chip key={slot} tone="neutral">
              {SLOT_LABEL[slot] ?? "조건"} · {value}
            </Chip>
          ))}
        </div>
      )}
      {latest && <AnswerStatus answer={latest} pendingId={pendingId} onEdit={() => setEditing(true)} editing={editing} />}
    </Screen>
  );
}

/** 저장된 답 + 카드 반영 상태. PUBLISHED 는 O8 전용 화면으로 따로 그린다. */
function AnswerStatus({
  answer,
  pendingId,
  onEdit,
  editing,
}: {
  answer: Answer;
  pendingId: string;
  onEdit: () => void;
  editing: boolean;
}) {
  const status: Record<string, { chip: string; tone: "brand" | "warn" | "danger" | "neutral"; text: string }> = {
    PENDING: { chip: "카드로 정리하는 중", tone: "neutral", text: "답은 물어본 직원에게 전달했어요. 카드로 정리하고 있어요." },
    LINKED: { chip: "이미 있는 카드와 같아요", tone: "brand", text: "답은 직원에게 전달했어요. 같은 내용의 카드가 있어서 새로 만들지 않았어요." },
    REVIEW: { chip: "확인이 필요해요", tone: "warn", text: "기존 카드와 다른 부분이 있어요. 공개하기 전에 카드에서 확인해 주세요." },
    FAILED: { chip: "카드 반영 실패", tone: "danger", text: "답은 직원에게 전달했어요. 카드로 정리하지는 못했어요." },
  };
  const view = status[answer.knowledge_status] ?? status.PENDING;
  return (
    <Surface className="flex flex-col gap-2 px-[18px] py-4">
      <div className="flex items-center justify-between gap-2">
        <Chip tone={view.tone}>{view.chip}</Chip>
        {!editing && (
          <TextButton onClick={onEdit} className="self-auto">
            답 고치기
          </TextButton>
        )}
      </div>
      <p className="whitespace-pre-wrap text-[15px] leading-[1.45] tracking-[-0.15px] text-ink">{answer.answer}</p>
      <Caption>{view.text}</Caption>
      {answer.knowledge_status === "REVIEW" && <ButtonLink href="/owner/cards" variant="secondary">카드에서 확인하기</ButtonLink>}
      {answer.knowledge_status === "FAILED" && answer.retry_available && answer.event_id && (
        <RetryKnowledge eventId={answer.event_id} pendingId={pendingId} />
      )}
    </Surface>
  );
}

function RetryKnowledge({ eventId, pendingId }: { eventId: string; pendingId: string }) {
  const { state } = useApp();
  const client = useQueryClient();
  const retry = useMutation({
    // API 가 재처리 사유를 요구한다. 점주에게 사유를 쓰게 하지 않고 고정 사유를 남긴다.
    mutationFn: () => rOwnerRetry(state.token!, eventId, { request_id: crypto.randomUUID(), reason: "점주가 화면에서 다시 시도" }),
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

/** O8: 점주 답이 새 카드로 공개됐을 때. */
function PublishedResult({ question, answer, onEdit }: { question: string; answer: string; onEdit: () => void }) {
  return (
    <Screen footer={<ButtonLink href="/owner">오늘 매장으로</ButtonLink>}>
      <BackButton href="/owner" />
      <div className="flex flex-1 flex-col items-center justify-center gap-4">
        <div className="relative flex w-full flex-col gap-1.5 rounded-[20px] border-[1.5px] border-accent-500 bg-surface px-[18px] py-4 shadow-[0_16px_36px_-6px_rgba(240,122,138,0.25)]">
          <span className="absolute right-4 top-3.5 rounded-full bg-accent-500 px-2.5 py-1 text-[12px] font-bold tracking-[-0.24px] text-white">
            새 카드
          </span>
          <p className="pr-16 text-[17px] font-bold leading-[1.45] tracking-[-0.34px] text-ink [word-break:keep-all]">{question}</p>
          <p className="whitespace-pre-wrap text-[14px] leading-[1.45] tracking-[-0.14px] text-ink-muted">{answer}</p>
        </div>
        <p className="text-center text-[24px] font-black leading-[1.45] tracking-[-0.48px] text-ink">카드로 남았어요</p>
        <p className="text-center text-[14px] leading-[1.45] tracking-[-0.14px] text-ink-muted">같은 질문은 이제 버디가 바로 답해요</p>
        <TextButton onClick={onEdit} className="self-center">
          답 고치기
        </TextButton>
      </div>
    </Screen>
  );
}
