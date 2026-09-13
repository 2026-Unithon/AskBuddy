"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Buddy } from "@/components/ui";
import { notificationsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";
import { BackgroundRefreshIndicator } from "./background-refresh-indicator";

export function OwnerPageHeader({
  title,
  subtitle,
  isFetching = false,
  isLoading = false,
}: {
  title: string;
  subtitle: string;
  isFetching?: boolean;
  isLoading?: boolean;
}) {
  const { state } = useApp();
  const notifications = useQuery(notificationsQuery(state.token, state.storeId));
  const unreadCount = notifications.data?.unread_count ?? 0;

  return (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border bg-surface px-4 py-3.5 shadow-2xs">
      <div className="flex min-w-0 items-center gap-2">
        <Buddy size={34} className="shrink-0" />
        <div className="min-w-0">
          <h1 className="truncate text-sm font-bold text-foreground">{title}</h1>
          <p className="truncate text-[11px] text-muted">{subtitle}</p>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <BackgroundRefreshIndicator
          isFetching={isFetching}
          isLoading={isLoading}
          label="갱신 중"
        />
        <Link
          href="/owner/notifications"
          aria-label={`알림${unreadCount > 0 ? ` ${unreadCount}개 읽지 않음` : ""}`}
          className="relative flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-base text-muted transition-colors hover:bg-surface-muted hover:text-foreground active:scale-[0.95]"
        >
          🔔
          {unreadCount > 0 && (
            <span className="absolute right-0.5 top-0.5 flex min-h-4 min-w-4 items-center justify-center rounded-full bg-danger-500 px-1 text-[9px] font-bold text-white">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </Link>
        <Link
          href="/role"
          className="flex min-h-[44px] items-center justify-center rounded-xl px-2 text-[11px] font-bold text-muted transition-colors hover:bg-surface-muted hover:text-foreground active:scale-[0.95]"
        >
          나가기
        </Link>
      </div>
    </header>
  );
}
