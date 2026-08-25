"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/staff/roadmap", label: "로드맵", icon: "🗺️" },
  { href: "/staff/chat", label: "Buddy 채팅", icon: "💬" },
];

export function StaffTabBar() {
  const pathname = usePathname();
  return (
    <nav className="sticky bottom-0 border-t border-border bg-surface/95 backdrop-blur flex">
      {TABS.map((tab) => {
        const active = pathname?.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`flex-1 flex flex-col items-center gap-1 py-2.5 text-xs font-medium transition-colors ${
              active ? "text-brand-700" : "text-muted"
            }`}
          >
            <span className="text-lg">{tab.icon}</span>
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
