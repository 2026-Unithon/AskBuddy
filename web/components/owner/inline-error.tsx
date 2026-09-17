"use client";

import { Button } from "@/components/ui";

interface InlineErrorProps {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  isRetrying?: boolean;
  onAction?: () => void;
  actionLabel?: string;
  className?: string;
}

export function InlineError({
  message,
  onRetry,
  retryLabel = "다시 시도",
  isRetrying = false,
  onAction,
  actionLabel,
  className = "",
}: InlineErrorProps) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      data-testid="inline-error"
      className={`rounded-2xl border border-danger-500/30 bg-danger-50 p-4 text-sm text-danger-700 shadow-xs ${className}`}
    >
      <div className="flex items-start gap-2.5">
        <span className="text-base leading-none shrink-0" aria-hidden="true">
          ⚠️
        </span>
        <div className="flex-1 min-w-0 space-y-1">
          <p className="font-semibold text-danger-900 leading-snug">{message}</p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {onRetry && (
              <Button
                variant="secondary"
                size="md"
                loading={isRetrying}
                loadingLabel="다시 확인 중"
                className="!px-3 !text-sm !bg-white !text-danger-700 hover:!bg-danger-50/80 border border-danger-200"
                onClick={onRetry}
              >
                {retryLabel}
              </Button>
            )}
            {onAction && actionLabel && (
              <button
                type="button"
                onClick={onAction}
                className="min-h-11 rounded-lg px-3 text-sm font-bold text-danger-800 underline hover:text-danger-950 active:scale-95"
              >
                {actionLabel}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
