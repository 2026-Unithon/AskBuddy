"use client";

export function BackgroundRefreshIndicator({
  isFetching,
  isLoading,
  label = "최신 정보 확인 중…",
}: {
  isFetching: boolean;
  isLoading: boolean;
  label?: string;
}) {
  if (!isFetching || isLoading) return null;

  return (
    <div
      role="status"
      className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-2.5 py-1 text-[11px] font-medium text-brand-700 border border-brand-200/60 shadow-xs"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-ping" />
      <span>{label}</span>
    </div>
  );
}

