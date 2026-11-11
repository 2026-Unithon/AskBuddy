"use client";

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button, ErrorInline, Sheet, focusRing, useFeedback } from "@/components/kit";
import { apiErrorMessage, postFeedback } from "@/lib/api";
import { useApp } from "@/lib/store";

const TITLE = { INQUIRY: "문의하기", IDEA: "의견 보내기" } as const;

/** 문의하기, 의견 보내기 시트(계획 8). 보내기 실패면 쓴 글을 그대로 둔다 */
export function FeedbackSheet({ kind, onClose }: { kind: "INQUIRY" | "IDEA"; onClose: () => void }) {
  const { state } = useApp();
  const { toast } = useFeedback();
  // 입력 초안(서버 값 아님)
  const [body, setBody] = useState("");
  // 연타 막기: 버튼 비활성은 다음 그리기 뒤라 그 사이 두 번째 누름이 들어온다. 보내는 중인지 바로 기록한다
  const inFlight = useRef(false);
  const send = useMutation({
    mutationFn: () => postFeedback(kind, body.trim(), state.token!),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: () => {
      toast("보냈어요");
      onClose();
    },
  });
  return (
    <Sheet open onClose={() => !send.isPending && onClose()} title={TITLE[kind]}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!body.trim() || inFlight.current) return;
          inFlight.current = true;
          send.mutate();
        }}
      >
        <textarea
          aria-label={TITLE[kind]}
          value={body}
          maxLength={2000}
          rows={6}
          onChange={(event) => setBody(event.target.value)}
          className={`min-h-36 resize-none rounded-[14px] bg-surface px-4 py-3 text-[16px] leading-[1.5] text-ink shadow-card outline-none ${focusRing}`}
        />
        {send.error && <ErrorInline message={apiErrorMessage(send.error, "보내지 못했어요. 다시 눌러 주세요.")} />}
        <Button type="submit" loading={send.isPending} disabled={!body.trim() || !state.token}>
          보내기
        </Button>
      </form>
    </Sheet>
  );
}
