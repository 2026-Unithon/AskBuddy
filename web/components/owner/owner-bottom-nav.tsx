"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useApp } from "@/lib/store";
import { bootstrapQuery } from "@/lib/query";

export type OwnerTabKey = "upload" | "questions" | "cards";

interface OwnerTabItem {
  key: OwnerTabKey;
  label: string;
  href: string;
  isActive: (pathname: string) => boolean;
  renderIcon: (active: boolean) => React.ReactNode;
}

const TABS: OwnerTabItem[] = [
  {
    key: "upload",
    label: "업로드",
    href: "/owner/upload",
    isActive: (pathname: string) =>
      pathname === "/owner/upload" || pathname.startsWith("/owner/jobs"),
    renderIcon: (active: boolean) => (
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={active ? "2.3" : "1.8"}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="17 8 12 3 7 8" />
        <line x1="12" y1="3" x2="12" y2="15" />
      </svg>
    ),
  },
  {
    key: "questions",
    label: "답변 대기",
    href: "/owner/questions",
    isActive: (pathname: string) => pathname.startsWith("/owner/questions"),
    renderIcon: (active: boolean) => (
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={active ? "2.3" : "1.8"}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
        <line x1="12" y1="17" x2="12.01" y2="17" strokeWidth="2.5" />
      </svg>
    ),
  },
  {
    key: "cards",
    label: "카드 목록",
    href: "/owner/cards",
    isActive: (pathname: string) =>
      pathname === "/owner/cards" || pathname.startsWith("/owner/cards/"),
    renderIcon: (active: boolean) => (
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={active ? "2.3" : "1.8"}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <rect width="18" height="18" x="3" y="3" rx="2" />
        <path d="M7 8h10" />
        <path d="M7 12h10" />
        <path d="M7 16h6" />
      </svg>
    ),
  },
];

export function OwnerBottomNav() {
  const pathname = usePathname();
  const { state } = useApp();

  // layout의 bootstrap 캐시를 공유한다. 배지 때문에 목록 API 네 개를 따로 호출하지 않는다.
  const bootstrap = useQuery(bootstrapQuery(state.token, state.userId, state.storeId, 30_000));
  const waitingQuestionsCount = bootstrap.data?.badges.waiting_questions ?? 0;
  const cardsNeedAttentionCount = bootstrap.data?.badges.pending_cards ?? 0;

  return (
    <nav
      aria-label="사장님 하단 내비게이션"
      className="fixed bottom-0 left-0 right-0 z-30 mx-auto w-full max-w-[480px] border-t border-border bg-surface/95 backdrop-blur-md shadow-[0_-2px_10px_rgba(0,0,0,0.04)]"
    >
      <div className="flex h-16 items-center justify-around px-2 pb-[calc(env(safe-area-inset-bottom,0px))]">
        {TABS.map((tab) => {
          const active = tab.isActive(pathname);

          // 탭별 배지 개수
          let badgeCount = 0;
          if (tab.key === "questions") badgeCount = waitingQuestionsCount;
          if (tab.key === "cards") badgeCount = cardsNeedAttentionCount;

          return (
            <Link
              key={tab.key}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={`group flex min-h-[48px] min-w-[72px] flex-1 flex-col items-center justify-center gap-1 rounded-xl py-1 text-xs font-medium transition-all active:scale-[0.96] ${
                active ? "text-brand-700 font-bold" : "text-muted hover:text-foreground"
              }`}
            >
              <div
                className={`relative flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
                  active ? "bg-brand-50 text-brand-700" : "text-muted group-hover:text-foreground"
                }`}
              >
                {tab.renderIcon(active)}
                {/* 배지 표시 */}
                {badgeCount > 0 ? (
                  <span
                    className="absolute -top-1 -right-1.5 flex min-h-[16px] min-w-[16px] items-center justify-center rounded-full bg-danger-500 px-1 text-[10px] font-extrabold text-white shadow-xs"
                    aria-label={`${badgeCount}개 대기`}
                  >
                    {badgeCount > 99 ? "99+" : badgeCount}
                  </span>
                ) : active ? (
                  <span
                    className="absolute -top-0.5 right-0.5 h-1.5 w-1.5 rounded-full bg-brand-500"
                    aria-hidden="true"
                  />
                ) : null}
              </div>
              <span className="leading-none tracking-tight">{tab.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
