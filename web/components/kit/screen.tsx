"use client";

import { usePathname } from "next/navigation";
import { useNavHistory } from "@/lib/nav-history";
import { useEffect, useRef, type ReactNode } from "react";

// 화면 오른쪽 위의 흐린 초록 빛. Figma: 380px 원, 프레임 오른쪽 밖으로 160px, 위로 160px.
export function Aurora() {
  return (
    <div aria-hidden className="pointer-events-none absolute right-[-160px] top-[-160px] size-[380px]">
      {/* eslint-disable-next-line @next/next/no-img-element -- 블러 필터 여백이 있는 장식 SVG라 원본 그대로 쓴다 */}
      <img alt="" src="/figma/aurora.svg" className="absolute inset-[-23.68%] block size-[147.36%] max-w-none" />
    </div>
  );
}

/**
 * 리브랜딩 화면 골격.
 * - children: 스크롤 영역 (세로 간격 16, 가로 여백 24 · 375 미만 20)
 * - footer: 스크롤과 무관하게 아래에 붙는 입력창·버튼
 * - tabBar: 있으면 맨 아래에 띄우고 footer 를 그 위로 올린다
 */
export function Screen({
  children,
  footer,
  tabBar,
  aurora = true,
  className = "",
}: {
  children: ReactNode;
  footer?: ReactNode;
  tabBar?: ReactNode;
  aurora?: boolean;
  className?: string;
}) {
  const main = useRef<HTMLElement>(null);
  const { enter } = useNavHistory();
  // 탭 화면은 스크롤 위치를 기억해 탭을 오갈 때 되살린다(NAV-3).
  const rememberScroll = Boolean(tabBar);
  const pathname = usePathname();
  useEffect(() => {
    const el = main.current;
    if (!rememberScroll || !el) return;
    const key = `askbuddy:scroll:${pathname}`;
    let saved = 0;
    try {
      saved = Number(sessionStorage.getItem(key)) || 0;
    } catch {
      // 저장소를 못 쓰면 맨 위에서 시작한다
    }
    // 데이터가 늦게 와 높이가 모자라면 잠깐(최대 1.5초) 다시 맞춰 본다. 사용자가 손대면 바로 멈춘다(끌고 가지 않게)
    let restoring = 0;
    const started = performance.now();
    const stopRestore = () => cancelAnimationFrame(restoring);
    const userInput = ["wheel", "touchstart", "pointerdown", "keydown"] as const;
    if (saved > 0) {
      const restore = () => {
        el.scrollTop = saved;
        if (Math.abs(el.scrollTop - saved) > 1 && performance.now() - started < 1500) restoring = requestAnimationFrame(restore);
      };
      restore();
      userInput.forEach((type) => el.addEventListener(type, stopRestore, { passive: true }));
    }
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        try {
          sessionStorage.setItem(key, String(Math.round(el.scrollTop)));
        } catch {
          // 저장 못 해도 화면 동작에는 영향 없다
        }
      });
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      stopRestore();
      userInput.forEach((type) => el.removeEventListener(type, stopRestore));
      cancelAnimationFrame(frame);
      el.removeEventListener("scroll", onScroll);
    };
  }, [rememberScroll, pathname]);
  const gutter = "px-5 min-[375px]:px-6";
  const bottomSpace = tabBar
    ? "pb-[calc(108px+env(safe-area-inset-bottom,0px))]"
    : "pb-[max(40px,calc(env(safe-area-inset-bottom,0px)+6px))]";
  return (
    <div data-enter={enter} className="relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-background text-ink">
      {aurora && <Aurora />}
      <main
        ref={main}
        className={`relative flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pt-[calc(28px+env(safe-area-inset-top,0px))] ${gutter} ${
          footer ? "pb-4" : bottomSpace
        } ${className}`}
      >
        {children}
      </main>
      {footer && <div className={`relative flex flex-col gap-3 pt-2 ${gutter} ${bottomSpace}`}>{footer}</div>}
      {tabBar}
    </div>
  );
}

/** 제목 묶음. eyebrow(매장명) · 제목 30 · 설명, 오른쪽 위 action(설정 버튼). */
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="relative flex flex-col gap-4">
      {eyebrow && (
        <p className="text-[14px] font-medium leading-[1.45] tracking-[-0.14px] text-ink-muted">{eyebrow}</p>
      )}
      <h1 className={`${action ? "pr-28" : ""} text-[30px] font-bold leading-[1.28] tracking-[-0.9px] text-ink [word-break:keep-all]`}>
        {title}
      </h1>
      {description && (
        <p className="-mt-2 text-[15px] leading-[1.45] tracking-[-0.15px] text-ink-muted [word-break:keep-all]">
          {description}
        </p>
      )}
      {action && <div className="absolute right-0 top-[-8px]">{action}</div>}
    </header>
  );
}

/** 섹션 제목 (예: "확인해 주세요 · 2"). */
export function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="text-[15px] font-bold leading-[1.45] tracking-[-0.15px] text-ink">{children}</h2>;
}

/** 작은 보조 문구 (12px). */
export function Caption({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <p className={`text-[12px] leading-[1.45] tracking-[-0.12px] text-ink-muted ${className}`}>{children}</p>;
}
