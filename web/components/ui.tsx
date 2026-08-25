"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

// Buddy 마스코트(러브버드) — 누끼딴 투명 PNG라 배경 없이 바로 얹으면 된다.
export function Buddy({ size = 64, className = "" }: { size?: number; className?: string }) {
  return (
    <Image
      src="/images/buddy.png"
      alt="Buddy"
      width={size}
      height={size}
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
        <p className="text-sm font-medium text-foreground leading-snug">{text}</p>
      </div>
    </div>
  );
}

// 온보딩·로드맵·채팅처럼 손에 든 화면은 모바일 폭으로 가운데 정렬한다 (레퍼런스가 폰 목업 기준).
export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh w-full flex justify-center bg-background">
      <div className="w-full max-w-[480px] min-h-dvh bg-background flex flex-col relative">
        {children}
      </div>
    </div>
  );
}

// 대시보드처럼 데이터가 많은 화면은 데스크탑에서 넓게 쓴다.
export function WideShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh w-full bg-background flex justify-center">
      <div className="w-full max-w-5xl px-5 sm:px-8 py-6 flex flex-col gap-6">{children}</div>
    </div>
  );
}

export function TopBar({
  title,
  onBack,
  right,
}: {
  title?: string;
  onBack?: () => void;
  right?: ReactNode;
}) {
  const router = useRouter();
  return (
    <div className="sticky top-0 z-10 flex items-center gap-2 px-4 py-3 bg-background/90 backdrop-blur">
      <button
        aria-label="뒤로가기"
        onClick={onBack ?? (() => router.back())}
        className="w-9 h-9 rounded-full flex items-center justify-center text-foreground hover:bg-surface-muted transition-colors"
      >
        ←
      </button>
      {title && <h1 className="text-base font-semibold flex-1 text-center -ml-9">{title}</h1>}
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
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "md" | "lg";
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-2xl font-semibold transition-colors disabled:opacity-40 disabled:pointer-events-none";
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
      className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
      {...props}
    />
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
    "inline-flex items-center justify-center gap-2 rounded-2xl font-semibold transition-colors h-11 px-5 text-sm";
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
      className={`w-full h-12 px-4 rounded-[var(--radius-md)] border border-border bg-surface text-foreground placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-brand-300 focus:border-brand-400 transition-shadow ${className}`}
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
    <div className="sticky bottom-0 mt-auto px-4 py-4 bg-gradient-to-t from-background via-background to-transparent">
      {children}
    </div>
  );
}
