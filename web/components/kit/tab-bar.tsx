"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { focusRing, pressable } from "@/components/kit/buttons";
import { Icon, type IconName } from "@/components/kit/icon";
import { useNavHistory } from "@/lib/nav-history";
import { CountBadge } from "@/components/kit/feedback";

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

/**
 * Figma TabBar: 아래에서 20 띄운 68 높이 알약, 활성 탭은 연초록 배경.
 * 탭끼리는 기록을 쌓지 않는다(폰 뒤로가 탭을 되짚지 않게). 지금 탭을 다시 누르면 맨 위로.
 */
export function TabBar({ tabs, badges = {} }: { tabs: Tab[]; badges?: Record<string, number> }) {
  const pathname = usePathname();
  const { markReplace } = useNavHistory();
  const activeIndex = Math.max(0, tabs.findIndex((tab) => isActive(tab, pathname)));
  return (
    <nav
      aria-label="주요 메뉴"
      className="absolute inset-x-4 bottom-[max(20px,env(safe-area-inset-bottom,0px))] z-20 flex h-[68px] items-center gap-1.5 rounded-[26px] bg-surface p-2 shadow-card"
    >
      {/* 활성 배경은 알약 하나가 탭 사이를 스프링으로 미끄러진다(o01f) */}
      <span
        aria-hidden
        data-tab-pill=""
        className="absolute inset-y-2 left-2 rounded-[20px] bg-empty transition-transform duration-[var(--dur-base)] ease-[var(--ease-spring)]"
        style={{ width: `calc((100% - 16px - ${(tabs.length - 1) * 6}px) / ${tabs.length})`, transform: `translateX(calc(${activeIndex} * (100% + 6px)))` }}
      />
      {tabs.map((tab) => {
        const active = isActive(tab, pathname);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            replace
            onNavigate={(event) => {
              if (pathname === tab.href) {
                event.preventDefault();
                document.querySelector("main")?.scrollTo({ top: 0, behavior: "smooth" });
                return;
              }
              markReplace();
            }}
            aria-current={active ? "page" : undefined}
            className={`relative flex h-full min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-[20px] text-[15px] leading-[1.45] tracking-[-0.15px] ${
              active ? "font-bold text-primary" : "font-medium text-ink-muted"
            } ${pressable} ${focusRing}`}
          >
            <span className="relative">
              <Icon name={tab.icon} size={20} />
              {(badges[tab.href] ?? 0) > 0 && (
                <span className="absolute -right-3.5 -top-2">
                  <CountBadge n={badges[tab.href]} tone="danger" />
                </span>
              )}
            </span>
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
