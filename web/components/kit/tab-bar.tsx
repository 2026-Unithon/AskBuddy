"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { focusRing } from "@/components/kit/buttons";
import { Icon, type IconName } from "@/components/kit/icon";

export type Tab = {
  href: string;
  label: string;
  icon: IconName;
  /** 이 경로들 아래에 있으면 활성으로 본다 (href 자신은 정확히 같을 때만). */
  match: string[];
};

export const OWNER_TABS: Tab[] = [
  { href: "/owner", label: "오늘 매장", icon: "home", match: ["/owner/questions"] },
  { href: "/owner/cards", label: "카드", icon: "layers", match: ["/owner/cards"] },
];

export const STAFF_TABS: Tab[] = [
  { href: "/staff", label: "오늘 할 일", icon: "checks", match: [] },
  { href: "/staff/recipes", label: "레시피", icon: "coffee", match: ["/staff/recipes"] },
];

function isActive(tab: Tab, pathname: string) {
  return pathname === tab.href || tab.match.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

/** Figma TabBar: 아래에서 20 띄운 68 높이 알약, 활성 탭은 연초록 배경. */
export function TabBar({ tabs }: { tabs: Tab[] }) {
  const pathname = usePathname();
  return (
    <nav
      aria-label="주요 메뉴"
      className="absolute inset-x-4 bottom-[max(20px,env(safe-area-inset-bottom,0px))] z-20 flex h-[68px] items-center gap-1.5 rounded-[26px] bg-surface p-2 shadow-card"
    >
      {tabs.map((tab) => {
        const active = isActive(tab, pathname);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`flex h-full min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-[20px] text-[15px] leading-[1.45] tracking-[-0.15px] ${
              active ? "bg-empty font-bold text-primary" : "font-medium text-ink-muted"
            } ${focusRing}`}
          >
            <Icon name={tab.icon} size={20} />
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
