import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon } from "@/components/kit/icon";

export const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background";

type Variant = "primary" | "secondary" | "kakao" | "danger";

// Figma Btn next / Btn email / Btn kakao: 세로 17 · 16 Bold · 모서리 12
const base = `inline-flex w-full select-none items-center justify-center gap-2 rounded-[12px] px-5 py-[17px] text-[16px] font-bold leading-[1.45] tracking-[-0.16px] transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 ${focusRing}`;

const variants: Record<Variant, string> = {
  primary: "bg-primary text-white shadow-primary",
  secondary: "border-[1.5px] border-empty bg-surface text-primary",
  kakao: "bg-kakao text-black/85",
  danger: "border-[1.5px] border-danger-200 bg-surface text-danger-700",
};

function Spinner() {
  return <span aria-hidden className="size-4 shrink-0 animate-spin rounded-full border-2 border-current border-r-transparent" />;
}

export function Button({
  variant = "primary",
  loading = false,
  className = "",
  disabled,
  type = "button",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`${base} ${variants[variant]} ${className}`}
      {...props}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export function ButtonLink({
  href,
  variant = "primary",
  className = "",
  children,
}: {
  href: string;
  variant?: Variant;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={`${base} ${variants[variant]} ${className}`}>
      {children}
    </Link>
  );
}

/** Figma BackBtn. 새로고침해도 같은 곳으로 가도록 목적지를 항상 명시한다. */
export function BackButton({ href, label = "뒤로" }: { href: string; label?: string }) {
  return (
    <Link
      href={href}
      className={`inline-flex min-h-11 items-center gap-0.5 self-start rounded-full bg-surface py-2 pl-2 pr-3.5 text-[14px] font-medium tracking-[-0.14px] text-ink shadow-card ${focusRing}`}
    >
      <Icon name="left" size={16} />
      {label}
    </Link>
  );
}

/** Figma SettingsBtn: 매장 이름 첫 글자를 넣은 40px 원. */
export function SettingsButton({ href, initial }: { href: string; initial: string }) {
  return (
    <Link
      href={href}
      aria-label="설정"
      className={`flex size-11 items-center justify-center rounded-full bg-surface text-[15px] font-bold tracking-[-0.3px] text-primary shadow-card ${focusRing}`}
    >
      {initial.slice(0, 1) || "·"}
    </Link>
  );
}

/** 글자만 있는 보조 버튼 (예: 시트의 "나중에", 설정의 "로그아웃"). */
export function TextButton({ className = "", type = "button", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      className={`min-h-11 self-start text-[13px] leading-[1.45] tracking-[-0.13px] text-ink-muted ${focusRing} ${className}`}
      {...props}
    />
  );
}
