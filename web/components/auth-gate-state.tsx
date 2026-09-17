"use client";

import { Button } from "@/components/ui";

type Props = {
  state: "loading" | "redirecting" | "error";
  onRetry: () => void;
};

export function AuthGateState({ state, onRetry }: Props) {
  const isError = state === "error";

  return (
    <main
      className="min-h-dvh w-full bg-background px-6 flex items-center justify-center"
      aria-live="polite"
      data-testid="auth-gate-state"
    >
      <div className="w-full max-w-[360px] rounded-3xl border border-border bg-surface p-6 text-center shadow-sm">
        <div
          className={`mx-auto mb-4 h-10 w-10 rounded-full ${
            isError ? "bg-danger-50" : "bg-brand-100 motion-safe:animate-pulse"
          }`}
          aria-hidden
        />
        <h1 className="text-lg font-bold">
          {isError ? "앱 정보를 불러오지 못했어요" : "로그인 정보를 확인하고 있어요"}
        </h1>
        <p className="mt-2 text-sm leading-6 text-muted">
          {isError
            ? "인터넷 연결을 확인한 뒤 다시 시도해주세요."
            : state === "redirecting"
              ? "로그인 화면으로 이동합니다."
              : "잠시만 기다려주세요."}
        </p>
        {isError && (
          <Button className="mt-5 w-full" onClick={onRetry} data-testid="auth-gate-retry">
            다시 시도
          </Button>
        )}
      </div>
    </main>
  );
}
