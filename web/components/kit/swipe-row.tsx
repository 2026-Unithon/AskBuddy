"use client";

import { useRef, useState, type PointerEvent, type ReactNode } from "react";
import { focusRing } from "@/components/kit/buttons";

export type SwipeAction = { label: string; tone: "danger" | "primary" | "neutral"; onAction: () => void };

const TRIGGER = 72;
const toneClass = { danger: "bg-danger-500 text-white", primary: "bg-primary text-white", neutral: "bg-ink-muted text-white" } as const;

/**
 * 밀어서 동작. left 는 왼쪽으로 밀 때(오른쪽에서 드러남), right 는 오른쪽으로 밀 때.
 * 72px 넘게 밀고 놓으면 동작, 덜 밀면 제자리. 세로 스크롤은 막지 않는다(가로가 더 클 때만 밀기).
 * 드러나는 버튼은 늘 DOM 에 있어 키보드, 스크린리더로도 누를 수 있다(포커스하면 내용이 밀려 보인다).
 */
export function SwipeRow({ children, left, right }: { children: ReactNode; left?: SwipeAction; right?: SwipeAction }) {
  const [dx, setDx] = useState(0);
  // 손을 뗄 때는 렌더 시점 값이 아니라 마지막으로 민 값을 본다
  const latest = useRef(0);
  const move = (value: number) => {
    latest.current = value;
    setDx(value);
  };
  const [dragging, setDragging] = useState(false);
  const start = useRef<{ x: number; y: number; horizontal: boolean | null } | null>(null);
  const moved = useRef(false);

  const clamp = (value: number) => Math.max(left ? -120 : 0, Math.min(right ? 120 : 0, value));
  const onDown = (event: PointerEvent) => {
    start.current = { x: event.clientX, y: event.clientY, horizontal: null };
    moved.current = false;
  };
  const onMove = (event: PointerEvent) => {
    const s = start.current;
    if (!s) return;
    const x = event.clientX - s.x, y = event.clientY - s.y;
    if (s.horizontal === null && Math.hypot(x, y) > 6) s.horizontal = Math.abs(x) > Math.abs(y);
    if (!s.horizontal) return;
    moved.current = true;
    setDragging(true);
    try {
      (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    } catch {
      // 이미 끝난 포인터면 붙잡지 못해도 밀기는 계속한다
    }
    move(clamp(x));
  };
  const onUp = () => {
    const value = latest.current;
    start.current = null;
    setDragging(false);
    move(0);
    if (value <= -TRIGGER) left?.onAction();
    else if (value >= TRIGGER) right?.onAction();
  };
  // 브라우저가 몸짓을 가져가면(세로 스크롤, 끌기) 동작 없이 제자리로
  const onCancel = () => {
    start.current = null;
    moved.current = false;
    setDragging(false);
    move(0);
  };

  return (
    <div className="relative overflow-hidden rounded-[20px]">
      <div
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onCancel}
        onClickCapture={(event) => {
          // 밀다가 놓은 것은 누르기가 아니다
          if (moved.current) {
            event.preventDefault();
            event.stopPropagation();
            moved.current = false;
          }
        }}
        className="relative z-10 touch-pan-y"
        style={{ transform: `translateX(${dx}px)`, transition: dragging ? "none" : "transform var(--dur-base) var(--ease-out)" }}
      >
        {children}
      </div>
      {/* 동작 버튼은 내용 뒤(아래 층)에 두고, 키보드로 포커스하면 내용을 밀어 드러낸다 */}
      {right && (
        <button type="button" aria-label={right.label} onClick={right.onAction} onFocus={() => move(120)} onBlur={() => move(0)}
          className={`absolute inset-y-0 left-0 z-0 flex w-[120px] items-center justify-start pl-5 text-[14px] font-bold ${toneClass[right.tone]} ${focusRing}`}>
          {right.label}
        </button>
      )}
      {left && (
        <button type="button" aria-label={left.label} onClick={left.onAction} onFocus={() => move(-120)} onBlur={() => move(0)}
          className={`absolute inset-y-0 right-0 z-0 flex w-[120px] items-center justify-end pr-5 text-[14px] font-bold ${toneClass[left.tone]} ${focusRing}`}>
          {left.label}
        </button>
      )}
    </div>
  );
}
