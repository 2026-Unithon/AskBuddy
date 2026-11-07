"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { bootstrapQuery, queryKeys, rDetailQuery, rKeys } from "@/lib/query";
import { rOwnerAnswer, type ROwnerInput } from "@/lib/r-v2-api";
import { useApp } from "@/lib/store";

/**
 * 사장님 답 보내기(질문 상세·답하기 시트 공용). 같은 답을 다시 보내면 같은 request_id 로 보낸다(멱등).
 * 답을 고치거나 저장에 성공하면 새 request_id 를 만든다.
 */
export function useOwnerAnswer(pendingId: string, { onSent }: { onSent?: () => void } = {}) {
  const { state } = useApp();
  const client = useQueryClient();
  const detail = useQuery(rDetailQuery(state.token, state.storeId, state.userId, pendingId));
  const [answer, setAnswerText] = useState("");
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const submittedBody = useRef<ROwnerInput | null>(null);
  const latest = detail.data?.answers.at(-1);

  const submit = useMutation({
    mutationFn: (body: { request_id: string; answer: string; expected_revision: number }) => rOwnerAnswer(state.token!, pendingId, body),
    onSuccess: async () => {
      setAnswerText("");
      setRequestId(crypto.randomUUID());
      submittedBody.current = null;
      await Promise.all([
        client.invalidateQueries({ queryKey: rKeys.pending(state.storeId, state.userId) }),
        client.invalidateQueries({ queryKey: queryKeys.questions(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.pending(state.storeId) }),
        client.invalidateQueries({ queryKey: bootstrapQuery(state.token, state.userId, state.storeId).queryKey }),
      ]);
      onSent?.();
    },
  });

  const setAnswer = (value: string) => {
    setAnswerText(value);
    submittedBody.current = null;
    setRequestId(crypto.randomUUID());
    if (submit.isError) submit.reset();
  };
  const send = () => {
    if (submit.isPending || !answer.trim()) return;
    submittedBody.current ??= { request_id: requestId, answer, expected_revision: latest?.revision ?? 0 };
    submit.mutate(submittedBody.current);
  };
  /** 409 뒤 최신 답을 다시 읽고 새로 보낼 준비를 한다(입력은 그대로). */
  const resetAfterConflict = () =>
    detail.refetch().then(() => {
      submittedBody.current = null;
      setRequestId(crypto.randomUUID());
      submit.reset();
    });

  return { detail, latest, answer, setAnswer, send, submit, resetAfterConflict };
}
