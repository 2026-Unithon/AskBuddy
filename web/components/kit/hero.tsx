import type { ReactNode } from "react";
import { BuddyImage } from "@/components/kit/buddy";
import { Icon } from "@/components/kit/icon";

/** Figma StoreNow(O6) · Hero(A2): 진한 초록 카드, 오른쪽 위 Buddy. */
export function HeroCard({
  children,
  buddySize = 64,
  className = "",
}: {
  children: ReactNode;
  buddySize?: number;
  className?: string;
}) {
  return (
    <section
      className={`relative flex w-full flex-col overflow-hidden rounded-[24px] bg-primary px-[22px] py-5 text-white shadow-hero ${className}`}
    >
      <BuddyImage size={buddySize} className="absolute right-3 top-2" />
      {children}
    </section>
  );
}

/** 히어로 안 시계 줄 (예: "지금 · 미들 진행 중"). pill=true 면 A2 의 근무조 칩. */
export function HeroClock({ children, pill = false }: { children: ReactNode; pill?: boolean }) {
  return (
    <p
      className={`inline-flex items-center self-start pr-20 text-[13px] font-medium tracking-[-0.26px] ${
        pill ? "gap-[5px] rounded-full bg-white/15 px-2.5 py-[5px] text-[12px] font-bold" : "gap-1.5"
      }`}
    >
      <Icon name="clock" size={pill ? 13 : 14} />
      {children}
    </p>
  );
}

/**
 * 히어로 안의 진행 막대. 실제 count(done/total)로만 그린다 — 추정 퍼센트 금지.
 * total 이 0 이면 빈 막대.
 */
export function HeroProgress({
  done,
  total,
  height = 6,
  label,
}: {
  done: number;
  total: number;
  height?: 6 | 8;
  label: string;
}) {
  const ratio = total > 0 ? Math.min(1, Math.max(0, done / total)) : 0;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={done}
      className="w-full overflow-hidden rounded-full bg-white/25"
      style={{ height }}
    >
      <div className="h-full rounded-full bg-white transition-[width] duration-500" style={{ width: `${ratio * 100}%` }} />
    </div>
  );
}
