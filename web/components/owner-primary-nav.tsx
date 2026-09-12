"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  { href: "/owner/upload?from=dashboard", match: "/owner/upload", label: "업로드", icon: "＋" },
  { href: "/owner/questions", match: "/owner/questions", label: "답변 대기", icon: "?" },
  { href: "/owner/cards", match: "/owner/cards", label: "카드 목록", icon: "▤" },
];

export function OwnerPrimaryNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="사장님 주요 메뉴" className="grid grid-cols-3 gap-2 rounded-2xl bg-surface-muted p-1.5">
      {tabs.map((tab) => {
        const active = pathname.startsWith(tab.match);
        return (
          <Link
            key={tab.match}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 items-center justify-center gap-1.5 rounded-xl px-2 text-xs font-bold transition-colors ${
              active ? "bg-surface text-brand-700 shadow-sm" : "text-muted hover:text-foreground"
            }`}
          >
            <span aria-hidden>{tab.icon}</span>{tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
