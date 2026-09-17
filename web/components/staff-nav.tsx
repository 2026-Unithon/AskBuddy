"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export type StaffTabKey = "roadmap" | "chat" | "faqs";

interface TabItem {
  key: StaffTabKey;
  label: string;
  href: string;
  isActive: (pathname: string) => boolean;
  renderIcon: (active: boolean) => React.ReactNode;
}

const TABS: TabItem[] = [
  {
    key: "roadmap",
    label: "학습",
    href: "/staff/roadmap",
    isActive: (pathname: string) =>
      pathname === "/staff/roadmap" || pathname.startsWith("/staff/items"),
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
        <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
        <path d="M6 6h10" />
        <path d="M6 10h10" />
      </svg>
    ),
  },
  {
    key: "chat",
    label: "Buddy",
    href: "/staff/chat",
    isActive: (pathname: string) => pathname === "/staff/chat",
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
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        {active ? (
          <circle cx="12" cy="10" r="1.5" fill="currentColor" stroke="none" />
        ) : (
          <path d="M8 10h.01M12 10h.01M16 10h.01" />
        )}
      </svg>
    ),
  },
  {
    key: "faqs",
    label: "자주 묻는 질문",
    href: "/staff/faqs",
    isActive: (pathname: string) => pathname === "/staff/faqs",
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
];

export function StaffBottomNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="직원 하단 내비게이션"
      className="fixed bottom-0 left-0 right-0 z-30 mx-auto w-full max-w-[480px] border-t border-border bg-surface/95 backdrop-blur-md shadow-[0_-2px_10px_rgba(0,0,0,0.04)]"
    >
      <div className="flex min-h-16 items-center justify-around px-2 pt-1 pb-[calc(0.25rem+env(safe-area-inset-bottom,0px))]">
        {TABS.map((tab) => {
          const active = tab.isActive(pathname);
          return (
            <Link
              key={tab.key}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={`group flex min-h-[48px] min-w-[72px] flex-1 flex-col items-center justify-center gap-1 rounded-xl py-1 text-xs font-medium transition-all active:scale-[0.96] ${
                active
                  ? "text-brand-700 font-bold"
                  : "text-muted hover:text-foreground"
              }`}
            >
              <div
                className={`relative flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
                  active ? "bg-brand-50 text-brand-700" : "text-muted group-hover:text-foreground"
                }`}
              >
                {tab.renderIcon(active)}
                {active && (
                  <span
                    className="absolute -top-0.5 right-0.5 h-1.5 w-1.5 rounded-full bg-brand-500"
                    aria-hidden="true"
                  />
                )}
              </div>
              <span className="leading-none tracking-tight">{tab.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
