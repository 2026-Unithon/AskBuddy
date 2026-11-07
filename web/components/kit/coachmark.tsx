"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { focusRing } from "@/components/kit/buttons";

type Step = { target: string; text: string };
const WAIT_MS = 2000;

function read(id: string) {
  try {
    return localStorage.getItem(`askbuddy:coach:${id}`) === "done";
  } catch {
    // 저장소를 못 쓰면 안내를 보여 준다(안 보여 주면 처음 쓰는 사람이 길을 잃는다)
    return false;
  }
}
function markDone(id: string) {
  try {
    localStorage.setItem(`askbuddy:coach:${id}`, "done");
  } catch {
    // 저장 못 하면 다음에 한 번 더 보인다
  }
}

/** 대상이 그려질 때까지 기다린다. 끝내 없으면 null(그 단계는 건너뛴다). */
function findTarget(selector: string, timeoutMs: number) {
  return new Promise<HTMLElement | null>((resolve) => {
    const found = () => document.querySelector<HTMLElement>(selector);
    const now = found();
    if (now) return resolve(now);
    const observer = new MutationObserver(() => {
      const el = found();
      if (!el) return;
      observer.disconnect();
      clearTimeout(timer);
      resolve(el);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    const timer = setTimeout(() => {
      observer.disconnect();
      resolve(null);
    }, timeoutMs);
  });
}

/**
 * 처음 한 번 뜨는 안내(코치마크, o01a). 대상을 밝게 비우고 말풍선으로 설명한다.
 * 끝나거나 건너뛰면 이 기기에 '봤음'을 남겨 다시 띄우지 않는다(사용자 편의라 브라우저 저장소).
 */
export function Coachmark({ id, steps }: { id: string; steps: Step[] }) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const target = useRef<HTMLElement | null>(null);
  const nextButton = useRef<HTMLButtonElement>(null);
  const bubble = useRef<HTMLDivElement>(null);
  // 서버 렌더에는 창이 없어 꺼 둔 채 그린다(대상 위치를 찾기 전엔 아무것도 그리지 않아 화면이 어긋나지 않는다)
  const [active, setActive] = useState(() => typeof window !== "undefined" && !read(id));
  const finish = () => {
    markDone(id);
    setActive(false);
  };
  const next = () => {
    setRect(null);
    if (index + 1 >= steps.length) finish();
    else setIndex(index + 1);
  };

  useEffect(() => {
    if (!active || index >= steps.length) return;
    let cancelled = false;
    void findTarget(steps[index].target, WAIT_MS).then((el) => {
      if (cancelled) return;
      if (!el) {
        // 대상이 끝내 없으면 이 단계를 건너뛴다
        if (index + 1 >= steps.length) {
          markDone(id);
          setActive(false);
        } else setIndex(index + 1);
        return;
      }
      target.current = el;
      el.scrollIntoView({ block: "nearest" });
      setRect(el.getBoundingClientRect());
    });
    return () => {
      cancelled = true;
    };
  }, [active, index, id, steps]);

  // 화면 크기·방향이 바뀌거나 스크롤되면 대상 위치를 다시 잰다
  useEffect(() => {
    if (!active || !rect) return;
    const measure = () => {
      if (target.current) setRect(target.current.getBoundingClientRect());
    };
    window.addEventListener("resize", measure);
    window.visualViewport?.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.visualViewport?.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [active, rect]);

  // 단계마다 '다음'에 포커스해 키보드·스크린리더가 안내부터 읽게 한다
  useEffect(() => {
    if (rect) nextButton.current?.focus();
  }, [rect, index]);

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Tab" && bubble.current) {
        // 덮개 뒤로 포커스가 나가지 않게 말풍선 안에서만 돈다
        const buttons = Array.from(bubble.current.querySelectorAll<HTMLButtonElement>("button"));
        const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
        event.preventDefault();
        buttons[(at + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length]?.focus();
        return;
      }
      if (event.key !== "Escape") return;
      markDone(id);
      setActive(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, id]);

  if (!active || !rect || index >= steps.length) return null;
  const last = index === steps.length - 1;
  const pad = 6;
  const below = rect.bottom + 140 < window.innerHeight;
  const skip = finish;
  return createPortal(
    <div className="fixed inset-0 z-[60]">
      {/* 대상 둘레만 비우고 나머지를 어둡게 덮는다 */}
      <div
        aria-hidden
        data-coach-ring=""
        className="absolute rounded-[16px] ring-4 ring-white transition-all duration-[var(--dur-base)] ease-[var(--ease-out)]"
        style={{ left: rect.left - pad, top: rect.top - pad, width: rect.width + pad * 2, height: rect.height + pad * 2, boxShadow: "0 0 0 9999px rgba(30,42,34,0.5)" }}
      />
      <div
        ref={bubble}
        role="dialog"
        aria-modal="true"
        aria-label="안내"
        className="absolute left-4 right-4 mx-auto max-w-[360px] rounded-[18px] bg-surface p-4 shadow-card animate-[feedback-in_var(--dur-base)_var(--ease-out)]"
        style={below ? { top: rect.bottom + pad + 12 } : { bottom: window.innerHeight - rect.top + pad + 12 }}
      >
        <p className="text-[15px] font-bold leading-[1.5] text-ink [word-break:keep-all]">{steps[index].text}</p>
        <div className="mt-3 flex items-center justify-between">
          <button type="button" onClick={skip} className={`min-h-11 text-[13px] text-ink-muted ${focusRing}`}>
            건너뛰기
          </button>
          <button
            ref={nextButton}
            type="button"
            onClick={next}
            className={`min-h-11 rounded-full bg-primary px-4 text-[14px] font-bold text-white ${focusRing}`}
          >
            {last ? "알겠어요" : "다음"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
