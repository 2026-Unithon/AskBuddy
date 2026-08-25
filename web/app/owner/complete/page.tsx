"use client";

import { useEffect, useState } from "react";
import { BottomCta, Card, LinkButton, Shell } from "@/components/ui";
import { useApp } from "@/lib/store";
import { createInvite } from "@/lib/api";

export default function CompletePage() {
  const { state, dispatch } = useApp();

  // 실제 초대코드를 발급받는다. 토큰에 store_id 가 없으면 백엔드가 403 을 주므로
  // 그때는 mock 코드(CAFE-DEMO)를 그대로 보여준다 — 데모가 끊기지 않게.
  useEffect(() => {
    if (!state.token) return;
    let cancelled = false;
    createInvite(state.token)
      .then((res) => {
        if (!cancelled && res.code) dispatch({ type: "SET_INVITE_CODE", code: res.code });
      })
      .catch(() => {
        // 발급 실패 — 기존 코드 유지
      });
    return () => {
      cancelled = true;
    };
    // 초대코드는 화면 진입 시 한 번만 발급한다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
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
      <div className="flex-1 flex flex-col items-center justify-center px-8 text-center gap-6">
        <div className="w-20 h-20 rounded-full bg-brand-500 flex items-center justify-center text-4xl">
          🎉
        </div>
        <div className="space-y-2">
          <h1 className="text-xl font-bold">학습이 끝났어요!</h1>
          <p className="text-sm text-muted leading-relaxed">
            아래 초대코드를 신입 직원에게 알려주세요.
            <br />
            코드로 들어오면 바로 로드맵을 시작할 수 있어요.
          </p>
        </div>

        <Card className="w-full py-6 px-4">
          <p className="text-xs text-muted mb-2">초대코드</p>
          <button
            onClick={copyCode}
            className="text-2xl font-bold tracking-widest text-brand-700 w-full"
          >
            {state.inviteCode}
          </button>
          <p className="text-xs text-brand-600 mt-2">{copied ? "복사했어요 ✓" : "탭해서 복사"}</p>
        </Card>
      </div>
      <BottomCta>
        <LinkButton href="/owner/dashboard" className="w-full h-13 text-base">
          대시보드로 가기
        </LinkButton>
      </BottomCta>
    </Shell>
  );
}
