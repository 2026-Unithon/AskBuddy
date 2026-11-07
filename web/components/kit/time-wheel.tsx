"use client";

import { useEffect, useMemo, useRef, type KeyboardEvent } from "react";
import { focusRing } from "@/components/kit/buttons";

const ITEM = 44;
const pad = (n: number) => String(n).padStart(2, "0");
const HOURS = Array.from({ length: 24 }, (_, i) => pad(i));
const MINUTES = Array.from({ length: 12 }, (_, i) => pad(i * 5));

/** 한 열 휠. 스크롤 스냅으로 굴리고 멈추면 가운데 칸을 고른다. 칸을 누르거나 위·아래 키로도 고른다. */
function Column({ label, options, value, onChange }: { label: string; options: string[]; value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const settle = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 휠을 코드로 움직이는 중에는 스크롤 끝 판정을 하지 않는다(누른 값이 지나가는 칸으로 바뀌지 않게)
  const programmatic = useRef(false);
  const mounted = useRef(false);

  // 값이 바뀌면 그 칸을 가운데로(브라우저 스크롤 위치 동기화)
  useEffect(() => {
    const el = ref.current;
    const index = options.indexOf(value);
    if (!el || index < 0) return;
    const top = index * ITEM;
    if (Math.abs(el.scrollTop - top) < 2) return;
    // 처음 열 때는 바로 그 자리에, 그 뒤 바뀔 때만 부드럽게
    const smooth = mounted.current;
    mounted.current = true;
    programmatic.current = true;
    el.scrollTo({ top, behavior: smooth ? "smooth" : "auto" });
    const done = setTimeout(() => {
      programmatic.current = false;
    }, smooth ? 400 : 50);
    return () => {
      clearTimeout(done);
      // 다음 effect 가 일찍 끝나도 표시가 굳지 않게 되돌린다
      programmatic.current = false;
    };
  }, [value, options]);

  useEffect(() => () => {
    if (settle.current) clearTimeout(settle.current);
  }, []);

  const onScroll = () => {
    if (programmatic.current) return;
    if (settle.current) clearTimeout(settle.current);
    settle.current = setTimeout(() => {
      const el = ref.current;
      if (!el) return;
      const next = options[Math.min(options.length - 1, Math.max(0, Math.round(el.scrollTop / ITEM)))];
      if (next !== value) onChange(next);
    }, 120);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const index = options.indexOf(value) + (event.key === "ArrowUp" ? -1 : 1);
    if (index >= 0 && index < options.length) onChange(options[index]);
  };

  return (
    <div className="relative flex-1">
      {/* 가운데 칸 띠 */}
      <div aria-hidden className="pointer-events-none absolute inset-x-1 top-[44px] h-[44px] rounded-[12px] bg-empty" />
      <div
        ref={ref}
        role="listbox"
        aria-label={label}
        tabIndex={0}
        onScroll={onScroll}
        onKeyDown={onKeyDown}
        className={`relative h-[132px] snap-y snap-mandatory overflow-y-auto overscroll-contain rounded-[12px] py-[44px] [scrollbar-width:none] ${focusRing}`}
      >
        {options.map((option) => (
          <div
            key={option}
            role="option"
            aria-selected={option === value}
            onClick={() => onChange(option)}
            className={`flex h-[44px] cursor-pointer snap-center items-center justify-center text-[20px] tabular-nums ${
              option === value ? "font-bold text-ink" : "text-ink-muted"
            }`}
          >
            {option}
          </div>
        ))}
      </div>
    </div>
  );
}

/** 시간 휠(o14c). value 는 "HH:MM". 분은 5분 간격이고, 지금 값의 분이 그 사이면 그 분도 넣는다. */
export function TimeWheel({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const [hour = "00", minute = "00"] = value.split(":");
  const minutes = useMemo(() => (MINUTES.includes(minute) ? MINUTES : [...MINUTES, minute].sort()), [minute]);
  return (
    <div className="flex items-center gap-2" role="group" aria-label={label}>
      <Column label={`${label} 시`} options={HOURS} value={hour} onChange={(h) => onChange(`${h}:${minute}`)} />
      <span aria-hidden className="text-[20px] font-bold text-ink">:</span>
      <Column label={`${label} 분`} options={minutes} value={minute} onChange={(m) => onChange(`${hour}:${m}`)} />
    </div>
  );
}
