"use client";

import { useState } from "react";
import { Buddy, LinkButton, Shell } from "@/components/ui";
import { useApp } from "@/lib/store";

export default function CompletePage() {
  const { state } = useApp();
  const [copied, setCopied] = useState(false);

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(state.inviteCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // 클립보드 권한이 없어도 코드는 화면에 그대로 보인다
    }
  }

  return (
    <Shell>
      <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
        <div className="relative mb-6">
          <Buddy size={130} />
          <span className="absolute -top-5 -right-4 text-4xl animate-bounce">🎉</span>
          <span className="absolute top-0 -left-5 text-2xl">✨</span>
        </div>
        <h1 className="text-3xl font-bold text-brand-700 mb-2">학습 완료!</h1>
        <p className="text-sm font-medium text-muted leading-relaxed mb-8">
          Buddy가 업무를 잘 익혔어요.
          <br />
          이제 신입 직원이 학습을 시작할 수 있어요!
          <br />
          <span className="text-brand-500 font-semibold">사장님께 완료 알림을 보냈어요 ✓</span>
        </p>

        <div className="w-full space-y-3">
          <button
            onClick={copyCode}
            className="w-full bg-surface rounded-2xl px-4 py-3.5 shadow-sm flex items-center gap-3 text-left"
          >
            <span className="text-xl">📱</span>
            <div>
              <p className="text-sm font-bold text-brand-700">신입 초대 코드</p>
              <p className="text-xs text-muted">{copied ? "복사했어요 ✓" : "탭해서 복사"}</p>
            </div>
            <div className="ml-auto bg-accent-500 rounded-xl px-3 py-1.5 shrink-0">
              <span className="text-xs font-bold text-brand-900">{state.inviteCode}</span>
            </div>
          </button>
          <LinkButton href="/owner/dashboard" className="w-full h-13 text-base">
            대시보드 보기 →
          </LinkButton>
        </div>
      </div>
    </Shell>
  );
}
