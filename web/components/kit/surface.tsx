import Link from "next/link";
import type { ReactNode } from "react";
import { focusRing } from "@/components/kit/buttons";
import { Icon } from "@/components/kit/icon";

/** 흰 카드 (모서리 20 · 카드 그림자). */
export function Surface({
  children,
  className = "",
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "li";
}) {
  return <Tag className={`w-full rounded-[20px] bg-surface shadow-card ${className}`}>{children}</Tag>;
}

export type ChipTone = "brand" | "accent" | "warn" | "danger" | "neutral";

const chipTones: Record<ChipTone, string> = {
  brand: "bg-empty text-primary",
  accent: "bg-accent-500 text-white",
  warn: "bg-warn-50 text-warn-700",
  danger: "bg-danger-50 text-danger-700",
  neutral: "bg-background text-ink-muted",
};

/** 카테고리·상태 칩. size sm = 목록 행 안의 11px 상태 칩. */
export function Chip({
  children,
  tone = "brand",
  size = "md",
  className = "",
}: {
  children: ReactNode;
  tone?: ChipTone;
  size?: "sm" | "md";
  className?: string;
}) {
  const sizes = {
    sm: "px-2 py-1 text-[11px] tracking-[-0.11px]",
    md: "px-2.5 py-1 text-[12px] tracking-[-0.12px]",
  };
  return (
    <span
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full font-bold leading-[1.45] ${sizes[size]} ${chipTones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

/** Figma Group: 위에 칩 라벨, 아래에 행 목록. */
export function ListGroup({ label, children }: { label?: ReactNode; children: ReactNode }) {
  return (
    <Surface as="section" className="flex flex-col px-[18px] pb-1.5 pt-2.5">
      {label && <div className="flex">{typeof label === "string" ? <Chip>{label}</Chip> : label}</div>}
      <ul className="flex flex-col">{children}</ul>
    </Surface>
  );
}

/** Figma Item: 제목 16 Bold · 부제 13 · 상태 칩 · 오른쪽 화살표. href 가 없으면 누를 수 없는 행. */
export function ListRow({
  title,
  subtitle,
  badge,
  href,
  onClick,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  badge?: ReactNode;
  href?: string;
  onClick?: () => void;
}) {
  const body = (
    <>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5 text-left leading-[1.45]">
        <span className="truncate text-[16px] font-bold tracking-[-0.16px] text-ink">{title}</span>
        {subtitle && <span className="truncate text-[13px] tracking-[-0.13px] text-ink-muted">{subtitle}</span>}
      </span>
      {badge}
      {(href || onClick) && <Icon name="right" size={18} className="text-ink-muted" />}
    </>
  );
  const rowClass = `flex w-full items-center gap-2 py-3.5 ${focusRing}`;
  return (
    <li>
      {href ? (
        <Link href={href} className={rowClass}>
          {body}
        </Link>
      ) : onClick ? (
        <button type="button" onClick={onClick} className={rowClass}>
          {body}
        </button>
      ) : (
        <div className={rowClass}>{body}</div>
      )}
    </li>
  );
}

/** O6 "확인해 주세요" 같은 단독 카드 링크 (제목 15 Medium + 보조 12). */
export function CardLink({ href, title, meta }: { href: string; title: ReactNode; meta?: ReactNode }) {
  return (
    <Link
      href={href}
      className={`flex w-full flex-col gap-1.5 rounded-[20px] bg-surface px-[18px] py-4 text-left leading-[1.45] shadow-card ${focusRing}`}
    >
      <span className="text-[15px] font-medium tracking-[-0.15px] text-ink [word-break:keep-all]">{title}</span>
      {meta && <span className="text-[12px] tracking-[-0.12px] text-ink-muted">{meta}</span>}
    </Link>
  );
}
