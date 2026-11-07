import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background";

type Variant = "primary" | "secondary" | "kakao" | "danger";

/** 누를 수 있는 모든 것: 누르는 동안 0.97 로 줄었다가 이즈 아웃으로 돌아온다(G2). */
export const pressable = "transition-transform duration-150 ease-[var(--ease-out)] active:scale-[0.97]";

// Figma Btn next / Btn email / Btn kakao: 세로 17 · 16 Bold · 모서리 12
const base = `inline-flex w-full select-none items-center justify-center gap-2 rounded-[12px] px-5 py-[17px] text-[16px] font-bold leading-[1.45] tracking-[-0.16px] ${pressable} disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 ${focusRing}`;

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
      data-variant={variant}
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
    <Link href={href} data-variant={variant} className={`${base} ${variants[variant]} ${className}`}>
      {children}
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
