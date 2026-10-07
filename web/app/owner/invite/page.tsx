"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button, ButtonLink, Caption, ErrorInline, PageHeader, Screen, Surface } from "@/components/kit";
import { apiErrorMessage, createInvite } from "@/lib/api";
import { useApp } from "@/lib/store";

// O5 알바 초대. 초대 링크·QR·카톡 공유는 카카오 작업(계획 U7)에서 바꾼다.
// 그 전까지는 지금 서버에 있는 초대 코드를 같은 자리에 보여준다.
export default function OwnerInvitePage() {
  const { state } = useApp();
  const [copied, setCopied] = useState<"idle" | "done" | "failed">("idle");
  const invite = useMutation({ mutationFn: () => createInvite(state.token!) });
  const code = invite.data?.code;

  async function copy() {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied("done");
    } catch {
      setCopied("failed");
    }
  }

  return (
    <Screen
      footer={
        <>
          {invite.error && (
            <ErrorInline message={apiErrorMessage(invite.error, "초대 코드를 만들지 못했어요.")} onRetry={() => invite.mutate()} retrying={invite.isPending} />
          )}
          {code ? (
            <Button onClick={() => void copy()}>{copied === "done" ? "복사했어요" : "코드 복사하기"}</Button>
          ) : (
            <Button loading={invite.isPending} disabled={!state.token} onClick={() => invite.mutate()}>
              초대 코드 만들기
            </Button>
          )}
          <ButtonLink href="/owner" variant="secondary">
            나중에
          </ButtonLink>
        </>
      }
    >
      <PageHeader title="첫 준비 끝났어요" description="이제 알바생에게 초대 코드만 알려주면 돼요." />
      <Surface className="flex flex-col items-center gap-1.5 px-[18px] py-4">
        <div className="flex size-[140px] items-center justify-center rounded-[12px] bg-empty px-2 text-center">
          {code ? (
            <span className="break-all text-[22px] font-black tracking-[-0.44px] text-primary" aria-live="polite">
              {code}
            </span>
          ) : (
            <span className="text-[13px] text-ink-muted">코드를 만들면 여기에 보여요</span>
          )}
        </div>
        <p className="text-[13px] leading-[1.45] tracking-[-0.13px] text-ink-muted">카운터 안쪽에 붙여두세요</p>
      </Surface>
      {copied === "failed" && <Caption>복사하지 못했어요. 코드를 길게 눌러 직접 복사해 주세요.</Caption>}
    </Screen>
  );
}
