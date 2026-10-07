import type { ReactNode } from "react";
import { BuddyImage } from "@/components/kit/buddy";
import { focusRing } from "@/components/kit/buttons";

/** 빈 상태: 왜 비었는지 + 다음 행동 (MVP §17-5, §28). */
export function Empty({
  title,
  description,
  action,
  buddy = true,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  buddy?: boolean;
}) {
  return (
    <div className="flex w-full flex-col items-center gap-2 rounded-[20px] bg-surface px-6 py-8 text-center shadow-card">
      {buddy && <BuddyImage size={72} />}
      <p className="text-[15px] font-bold leading-[1.45] tracking-[-0.15px] text-ink [word-break:keep-all]">{title}</p>
      {description && (
        <p className="text-[13px] leading-[1.45] tracking-[-0.13px] text-ink-muted [word-break:keep-all]">{description}</p>
      )}
      {action && <div className="mt-2 w-full">{action}</div>}
    </div>
  );
}

/** 사라지지 않는 오류 + 재시도. 실패한 자리에 둔다. */
export function ErrorInline({
  message,
  onRetry,
  retrying = false,
  retryLabel = "다시 시도",
}: {
  message: ReactNode;
  onRetry?: () => void;
  retrying?: boolean;
  retryLabel?: string;
}) {
  return (
    <div role="alert" className="flex w-full items-center gap-3 rounded-[16px] bg-danger-50 px-4 py-3">
      <p className="min-w-0 flex-1 whitespace-pre-line text-[13px] leading-[1.45] tracking-[-0.13px] text-danger-800 [word-break:keep-all]">
        {message}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className={`min-h-11 shrink-0 rounded-full bg-surface px-3.5 text-[13px] font-bold text-danger-700 disabled:opacity-50 ${focusRing}`}
        >
          {retrying ? "확인 중" : retryLabel}
        </button>
      )}
    </div>
  );
}

/** 초기 로딩 자리표시. 미래 콘텐츠 모양(카드 높이)대로 둔다. */
export function Skeleton({ className = "h-16" }: { className?: string }) {
  return <div aria-hidden className={`w-full animate-pulse rounded-[20px] bg-surface/70 shadow-card ${className}`} />;
}

/** 기존 내용을 유지한 채 백그라운드 갱신 중임을 알린다. */
export function RefreshingHint({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <p aria-live="polite" className="text-[12px] leading-[1.45] text-ink-muted">
      새 내용을 확인하고 있어요
    </p>
  );
}
