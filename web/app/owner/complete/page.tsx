"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Buddy, Button, LinkButton, Shell } from "@/components/ui";
import { ApiError, createInvite } from "@/lib/api";
import { useApp } from "@/lib/store";

export default function CompletePage() {
  const { state } = useApp();
  const [copied, setCopied] = useState(false);
  const invite = useMutation({ mutationFn: () => createInvite(state.token!) });
  const code = invite.data?.code;

  async function copyCode() {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Shell>
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <div className="relative mb-6"><Buddy size={130} /><span className="absolute -right-4 -top-5 animate-bounce text-4xl">🎉</span><span className="absolute -left-5 top-0 text-2xl">✨</span></div>
        <h1 className="mb-2 text-3xl font-bold text-brand-700">카드 준비 완료!</h1>
        <p className="mb-8 text-sm font-medium leading-relaxed text-muted">공개한 카드로 직원 학습을 시작할 수 있어요.<br />새 카드는 카드 목록에서 계속 검토할 수 있습니다.</p>
        <div className="w-full space-y-3">
          {code ? <button onClick={() => void copyCode()} className="flex w-full items-center gap-3 rounded-2xl bg-surface px-4 py-3.5 text-left shadow-sm"><span className="text-xl">📱</span><div><p className="text-sm font-bold text-brand-700">신입 초대 코드</p><p className="text-xs text-muted">{copied ? "복사했어요 ✓" : "탭해서 복사"}</p></div><div className="ml-auto shrink-0 rounded-xl bg-accent-500 px-3 py-1.5"><span className="text-xs font-bold text-brand-900">{code}</span></div></button> : <Button className="w-full" disabled={!state.token || invite.isPending} onClick={() => invite.mutate()}>{invite.isPending ? "발급 중…" : "신입 초대 코드 발급"}</Button>}
          {invite.error && <p role="alert" className="text-xs text-danger-500">{invite.error instanceof ApiError ? invite.error.detail || "초대 코드를 발급하지 못했어요." : "서버에 연결할 수 없습니다."}</p>}
          <LinkButton href="/owner/dashboard" className="w-full h-13 text-base">대시보드 보기 →</LinkButton>
        </div>
      </div>
    </Shell>
  );
}
