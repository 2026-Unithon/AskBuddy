"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-background";

// Buddy 마스코트(러브버드) — 누끼딴 투명 PNG라 배경 없이 바로 얹으면 된다.
// unoptimized 필수: Next/Image 최적화 파이프라인이 포맷 협상 과정에서
// 알파 채널을 흰 배경으로 눌러버리는 경우가 있다 — 원본 PNG를 그대로 내려준다.
export function Buddy({ size = 64, className = "" }: { size?: number; className?: string }) {
  return (
    <Image
      src="/images/buddy.png"
      alt="Buddy"
      width={size}
      height={size}
      unoptimized
      draggable={false}
      className={`object-contain shrink-0 select-none ${className}`}
      style={{ width: size, height: size }}
    />
  );
}

export function BuddyBubble({
  text,
  size = 40,
  className = "",
}: {
  text: string;
  size?: number;
  className?: string;
}) {
  return (
    <div className={`flex items-end gap-2 ${className}`}>
      <Buddy size={size} />
      <div className="rounded-2xl rounded-bl-sm px-4 py-2.5 shadow-sm max-w-[80%] bg-accent-100">
        <p className="text-base font-medium text-foreground leading-relaxed">{text}</p>
      </div>
    </div>
  );
}

// 온보딩·로드맵·채팅처럼 손에 든 화면은 모바일 폭으로 가운데 정렬한다 (레퍼런스가 폰 목업 기준).
export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="app-page">
      <div className="app-mobile-frame">
        {children}
      </div>
    </div>
  );
}

// 대시보드처럼 데이터가 많은 화면은 데스크탑에서 넓게 쓴다.
export function WideShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-page">
      <div className="mx-auto flex h-full min-h-0 w-full max-w-5xl flex-col gap-6 overflow-y-auto px-5 py-6 sm:px-8">{children}</div>
    </div>
  );
}

export function TopBar({
  title,
  onBack,
  backHref,
  right,
}: {
  title?: string;
  onBack?: () => void;
  /** 화면 흐름상 정해진 이전 화면. 직접 URL로 들어오거나 새로고침해도 항상 같은 곳으로 간다 —
   *  router.back()은 브라우저 히스토리가 없으면 엉뚱한 곳으로 가거나 아무 반응이 없다. */
  backHref?: string;
  right?: ReactNode;
}) {
  const router = useRouter();
  const backButtonClass =
    `min-h-11 min-w-11 rounded-xl flex items-center justify-center text-foreground hover:bg-surface-muted active:bg-surface-muted active:scale-[0.96] transition ${focusRing}`;
  return (
    <div className="sticky top-0 z-10 flex items-center gap-2 px-4 py-3 bg-background/90 backdrop-blur">
      {backHref ? (
        <Link href={backHref} aria-label="뒤로가기" className={backButtonClass}>
          ←
        </Link>
      ) : (
        <button
          type="button"
          aria-label="뒤로가기"
          onClick={onBack ?? (() => router.back())}
          className={backButtonClass}
        >
          ←
        </button>
      )}
      {/* -ml-9 로 화살표 위까지 겹쳐 가운데 정렬을 맞춘다. 그대로 두면 제목이 클릭을
          가로채 뒤로가기가 눌리지 않는다 — 제목은 누를 일이 없으니 통과시킨다. */}
      {title && (
        <h1 className="text-base font-semibold flex-1 text-center -ml-11 pointer-events-none">
          {title}
        </h1>
      )}
      <div className="min-w-9 flex justify-end">{right}</div>
    </div>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`bg-surface border border-border rounded-[var(--radius-lg)] shadow-[0_1px_2px_-1px_rgba(0,0,0,0.10),0_1px_3px_rgba(0,0,0,0.10)] ${className}`}
    >
      {children}
    </div>
  );
}

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  loading = false,
  loadingLabel,
  disabled,
  type = "button",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "md" | "lg";
  loading?: boolean;
  loadingLabel?: string;
}) {
  const base =
    `inline-flex min-w-11 items-center justify-center gap-2 rounded-2xl font-semibold select-none touch-manipulation transition active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 ${focusRing}`;
  const sizes = {
    md: "h-11 px-5 text-sm",
    lg: "h-13 px-6 text-base",
  };
  const variants = {
    primary: "bg-brand-600 text-white hover:bg-brand-700",
    secondary: "bg-brand-50 text-brand-700 hover:bg-brand-100",
    ghost: "bg-transparent text-muted hover:bg-surface-muted",
    danger: "bg-danger-50 text-danger-700 hover:bg-danger-50/70",
  };
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      data-loading={loading || undefined}
      className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
      {...props}
    >
      {loading && (
        <span
          aria-hidden="true"
          className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-current border-r-transparent"
        />
      )}
      <span>{loading && loadingLabel ? loadingLabel : children}</span>
    </button>
  );
}

export function LinkButton({
  href,
  children,
  variant = "primary",
  className = "",
}: {
  href: string;
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost";
  className?: string;
}) {
  const base =
    `inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-2xl font-semibold select-none touch-manipulation transition active:scale-[0.97] h-11 px-5 text-sm ${focusRing}`;
  const variants = {
    primary: "bg-brand-600 text-white hover:bg-brand-700",
    secondary: "bg-brand-50 text-brand-700 hover:bg-brand-100",
    ghost: "bg-transparent text-muted hover:bg-surface-muted",
  };
  return (
    <Link href={href} className={`${base} ${variants[variant]} ${className}`}>
      {children}
    </Link>
  );
}

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`w-full min-h-12 px-4 rounded-[var(--radius-md)] border border-border bg-surface text-base text-foreground placeholder:text-muted transition-shadow hover:border-brand-300 focus:border-brand-500 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:opacity-70 aria-invalid:border-danger-500 aria-invalid:ring-danger-500 ${focusRing} ${className}`}
      {...props}
    />
  );
}

export function Textarea({ className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`w-full rounded-[var(--radius-md)] border border-border bg-surface p-3 text-base leading-relaxed text-foreground placeholder:text-muted transition-shadow hover:border-brand-300 focus:border-brand-500 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:opacity-70 aria-invalid:border-danger-500 aria-invalid:ring-danger-500 ${focusRing} ${className}`}
      {...props}
    />
  );
}

export function Select({ className = "", ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`min-h-12 rounded-[var(--radius-md)] border border-border bg-surface px-3 text-base text-foreground transition-shadow hover:border-brand-300 focus:border-brand-500 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:opacity-70 aria-invalid:border-danger-500 aria-invalid:ring-danger-500 ${focusRing} ${className}`}
      {...props}
    />
  );
}

export function ProgressBar({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="w-full h-2 rounded-full bg-surface-muted overflow-hidden">
      <div
        className="h-full rounded-full bg-brand-500 transition-[width] duration-500"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

export function Badge({
  children,
  tone = "brand",
}: {
  children: ReactNode;
  tone?: "brand" | "warn" | "danger" | "neutral";
}) {
  const tones = {
    brand: "bg-brand-50 text-brand-700",
    warn: "bg-warn-50 text-warn-700",
    danger: "bg-danger-50 text-danger-700",
    neutral: "bg-surface-muted text-muted",
  };
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function BottomCta({ children }: { children: ReactNode }) {
  return (
    <div className="sticky bottom-0 z-20 mt-auto bg-gradient-to-t from-background via-background to-transparent px-4 pt-4 pb-[calc(1rem+env(safe-area-inset-bottom,0px))]">
      {children}
    </div>
  );
}
