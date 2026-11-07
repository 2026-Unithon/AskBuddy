"use client";

import { useLayoutEffect, useRef, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { focusRing } from "@/components/kit/buttons";

type Item = { key: string; label: string };

/**
 * 수정 모드에서 끌어서 순서 바꾸기(o06d). 줄 오른쪽 손잡이를 끌면 줄 높이 절반을 넘을 때마다 한 칸씩 옮기고,
 * 옮길 수 없는 자리(canMove 가 거짓, 예: 선행 단계 앞)면 그대로 둔다. 손잡이에 포커스하고 위·아래 화살표로도 옮긴다.
 */
export function SortableList<T extends Item>({
  items,
  canMove,
  onMove,
  renderItem,
  onEnd,
}: {
  items: T[];
  canMove: (from: number, to: number) => boolean;
  onMove: (key: string, dir: -1 | 1) => void;
  renderItem: (item: T, index: number) => ReactNode;
  /** 끌기를 놓았을 때, 키보드로 한 칸 옮겼을 때. 저장은 여기서 한 번만 하면 된다 */
  onEnd?: () => void;
}) {
  // 끄는 동안 순서가 바뀌므로 최신 목록·규칙을 ref 로 본다
  const latest = useRef({ items, canMove, onMove, onEnd });
  useLayoutEffect(() => {
    latest.current = { items, canMove, onMove, onEnd };
  });
  const drag = useRef<{ key: string; y: number; height: number } | null>(null);

  const step = (key: string, dir: -1 | 1) => {
    const { items: list, canMove: allowed, onMove: move } = latest.current;
    const index = list.findIndex((item) => item.key === key);
    const target = index + dir;
    if (index < 0 || target < 0 || target >= list.length || !allowed(index, target)) return false;
    move(key, dir);
    return true;
  };

  // 줄이 옮겨지면 React 가 그 <li> 를 DOM 에서 옮겨 포인터 붙잡기가 풀린다. 그래서 누른 순간부터 놓을 때까지 window 에서 듣는다
  const onPointerDown = (key: string) => (event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const pointerId = event.pointerId;
    const row = event.currentTarget.closest("li");
    drag.current = { key, y: event.clientY, height: row?.getBoundingClientRect().height ?? 48 };
    const move = (e: globalThis.PointerEvent) => {
      const d = drag.current;
      if (!d || e.pointerId !== pointerId) return;
      const dy = e.clientY - d.y;
      if (Math.abs(dy) < d.height / 2) return;
      const dir = dy < 0 ? -1 : 1;
      // 옮겼든 막혔든 기준점을 한 줄만큼 옮겨, 계속 끌면 다음 칸을 다시 따진다
      step(d.key, dir);
      d.y += dir * d.height;
    };
    const end = (e: globalThis.PointerEvent) => {
      if (e.pointerId !== pointerId) return;
      drag.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      latest.current.onEnd?.();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  };
  const onKeyDown = (key: string) => (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    if (step(key, event.key === "ArrowUp" ? -1 : 1)) latest.current.onEnd?.();
  };

  return (
    <ul className="flex flex-col">
      {items.map((item, index) => (
        <li key={item.key} className="flex items-start gap-1 border-b border-background last:border-b-0">
          <div className="min-w-0 flex-1">{renderItem(item, index)}</div>
          <button
            type="button"
            aria-label={`${item.label.slice(0, 12)} 옮기기`}
            onPointerDown={onPointerDown(item.key)}
            onKeyDown={onKeyDown(item.key)}
            className={`mt-2 flex size-11 shrink-0 cursor-grab touch-none select-none items-center justify-center rounded-[12px] text-[20px] text-ink-muted active:cursor-grabbing ${focusRing}`}
          >
            <span aria-hidden>≡</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
