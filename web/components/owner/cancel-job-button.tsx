"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog, useFeedback } from "@/components/kit";
import { focusRing } from "@/components/kit/buttons";
import { apiErrorMessage, cancelIngestJob } from "@/lib/api";
import { queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

/**
 * 자료 줄 옆 '정리 취소'(2026-11-08 사용자: 화면 아래 작은 글이 아니라 자료 옆에).
 * 서버는 작업 단위로 멈춘다. 한 작업에 자료가 여럿이면 확인 창이 함께 멈춘다고 알린다.
 */
export function CancelJobButton({ jobId, sourceCount = 1 }: { jobId: number; sourceCount?: number }) {
  const { state } = useApp();
  const client = useQueryClient();
  const feedback = useFeedback();
  const [confirm, setConfirm] = useState(false);
  const cancel = useMutation({
    mutationFn: () => cancelIngestJob(jobId, state.token!),
    onSuccess: async () => {
      setConfirm(false);
      feedback.toast("정리를 취소했어요");
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.ingestJob(state.storeId, jobId) }),
        client.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) }),
      ]);
    },
  });
  return (
    <>
      <button
        type="button"
        onClick={(event) => {
          // 줄 전체가 링크일 때 작업 화면으로 넘어가지 않게
          event.preventDefault();
          event.stopPropagation();
          setConfirm(true);
        }}
        className={`flex min-h-11 shrink-0 items-center rounded-full bg-surface px-3.5 text-[13px] font-bold text-danger-700 shadow-card ${focusRing}`}
      >
        정리 취소
      </button>
      <ConfirmDialog
        open={confirm}
        title="정리를 취소할까요?"
        description={
          sourceCount > 1
            ? `같이 올린 자료 ${sourceCount}개의 정리를 함께 멈춰요. 올린 자료는 남아 있어 나중에 다시 정리할 수 있어요.`
            : "올린 자료는 남아 있어 나중에 다시 정리할 수 있어요."
        }
        confirmLabel="취소하기"
        cancelLabel="계속 정리"
        tone="danger"
        loading={cancel.isPending}
        error={cancel.error ? apiErrorMessage(cancel.error, "취소하지 못했어요.") : null}
        onConfirm={() => cancel.mutate()}
        onCancel={() => {
          cancel.reset();
          setConfirm(false);
        }}
      />
    </>
  );
}
