"use client";

import { useState, type ReactNode } from "react";
import { Caption, Composer, ErrorInline } from "@/components/kit";
import { useOwnerAnswer } from "@/components/owner/use-owner-answer";
import { ApiError, apiErrorMessage } from "@/lib/api";

/** 답 입력·보내기(o01d·o10c). 충돌(409)·오류는 입력을 그대로 두고 알린다. */
export function QuestionAnswerForm({
  pendingId,
  onSent,
  tools,
  attachments,
  below,
}: {
  pendingId: string;
  onSent?: () => void;
  /** 입력창 도구 자리(📎 등) */
  tools?: ReactNode;
  /** 입력창 첨부 자리 */
  attachments?: ReactNode;
  /** 입력창 아래(종류 칩 등) */
  below?: ReactNode;
}) {
  const form = useOwnerAnswer(pendingId, { onSent });
  const [focused, setFocused] = useState(false);
  const { submit } = form;
  const conflict = submit.error instanceof ApiError && submit.error.status === 409;
  return (
    <div className="flex flex-col gap-2" onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}>
      {submit.error && (
        <ErrorInline
          message={
            conflict
              ? "그사이 답이 바뀌었어요. 최신 답을 확인한 뒤 다시 보내 주세요. 입력 내용은 그대로 두었어요."
              : apiErrorMessage(submit.error, "답이 전달되지 않았어요. 입력 내용은 그대로 두었어요.")
          }
          onRetry={() => (conflict ? void form.resetAfterConflict() : form.send())}
          retrying={submit.isPending || form.detail.isRefetching}
        />
      )}
      <Composer
        label="직원에게 보낼 답"
        value={form.answer}
        onChange={form.setAnswer}
        onSubmit={form.send}
        submitting={submit.isPending}
        disabled={submit.isPending}
        canSubmit={form.answer.trim().length > 0}
        submitLabel={form.latest ? "고쳐 보내기" : "넣기"}
        placeholder={form.latest ? "바뀐 내용을 적어 주세요" : "직원에게 보낼 답을 적어 주세요"}
        tools={tools}
        attachments={attachments}
      />
      {focused && !form.answer.trim() && <Caption className="px-1">답을 적으면 보낼 수 있어요</Caption>}
      {below}
    </div>
  );
}
