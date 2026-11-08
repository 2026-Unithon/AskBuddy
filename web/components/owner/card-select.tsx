"use client";

import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { focusRing } from "@/components/kit/buttons";
import { rangeSelect } from "@/lib/drag-select";

// 손가락이 이만큼 움직이면 어느 쪽 끌기인지 정한다. 가로로 먼저 움직이면 고르기, 세로면 스크롤
const DECIDE_PX = 8;
// 고르며 끄는 손가락이 스크롤 영역 위·아래 끝에서 이만큼 안이면 그쪽으로 저절로 스크롤한다(사진 앱처럼)
const EDGE_PX = 72;
const SCROLL_STEP = 12;

type Drag = { anchor: number; x: number; y: number; base: Set<number>; mode: "undecided" | "select" | "scroll" };

/**
 * 카드 선택 모드의 고른 카드(화면 상태). 사진 앱처럼 하나씩 누르거나 가로로 끌어 여러 장을 고른다.
 * order 는 화면에 보이는 카드 순서(끌기 범위와 전체 선택의 기준).
 */
export function useCardSelection(order: number[]) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const drag = useRef<Drag | null>(null);
  // 끌기로 고른 직후 손을 뗄 때 생기는 click 이 마지막 카드를 다시 뒤집지 않게 한 번 막는다
  const swallowClick = useRef(false);
  // 가장자리 자동 스크롤: 손가락 위치와 스크롤 영역, 돌고 있는 프레임
  const edge = useRef<{ x: number; y: number; scroller: HTMLElement | null; frame: number | null }>({ x: 0, y: 0, scroller: null, frame: null });

  const stopEdge = () => {
    if (edge.current.frame !== null) cancelAnimationFrame(edge.current.frame);
    edge.current.frame = null;
  };

  const cardAt = (x: number, y: number) => {
    const el = document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-card-id]");
    return el ? Number(el.dataset.cardId) : null;
  };

  const containerProps = {
    onPointerDown: (event: ReactPointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      const anchor = cardAt(event.clientX, event.clientY);
      drag.current = anchor === null ? null : { anchor, x: event.clientX, y: event.clientY, base: selected, mode: "undecided" };
    },
    onPointerMove: (event: ReactPointerEvent<HTMLElement>) => {
      const current = drag.current;
      if (!current || current.mode === "scroll") return;
      if (current.mode === "undecided") {
        const dx = Math.abs(event.clientX - current.x);
        const dy = Math.abs(event.clientY - current.y);
        if (dx < DECIDE_PX && dy < DECIDE_PX) return;
        current.mode = dx > dy ? "select" : "scroll";
        if (current.mode === "scroll") return;
        event.currentTarget.setPointerCapture(event.pointerId);
      }
      const over = cardAt(event.clientX, event.clientY);
      if (over !== null) setSelected(rangeSelect(order, current.anchor, over, current.base));
      // 위·아래 끝 가까이면 손가락을 멈춰도 계속 스크롤하며 그 아래 카드까지 고른다
      const scroller = edge.current.scroller ?? event.currentTarget.closest("main");
      edge.current = { ...edge.current, x: event.clientX, y: event.clientY, scroller };
      if (edge.current.frame === null && scroller) {
        const tick = () => {
          const box = scroller.getBoundingClientRect();
          const { x, y } = edge.current;
          const dir = y > box.bottom - EDGE_PX ? 1 : y < box.top + EDGE_PX ? -1 : 0;
          const live = drag.current;
          if (dir === 0 || !live || live.mode !== "select") {
            edge.current.frame = null;
            return;
          }
          scroller.scrollTop += dir * SCROLL_STEP;
          const under = cardAt(x, y);
          if (under !== null) setSelected(rangeSelect(order, live.anchor, under, live.base));
          edge.current.frame = requestAnimationFrame(tick);
        };
        edge.current.frame = requestAnimationFrame(tick);
      }
    },
    onPointerUp: () => {
      if (drag.current?.mode === "select") swallowClick.current = true;
      drag.current = null;
      stopEdge();
    },
    onPointerCancel: () => {
      drag.current = null;
      stopEdge();
    },
  };

  const toggle = (cardId: number) => {
    if (swallowClick.current) {
      swallowClick.current = false;
      return;
    }
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(cardId)) next.delete(cardId);
      else next.add(cardId);
      return next;
    });
  };

  const allSelected = order.length > 0 && order.every((id) => selected.has(id));
  return {
    selected,
    setSelected,
    toggle,
    allSelected,
    toggleAll: () => setSelected(allSelected ? new Set() : new Set(order)),
    clear: () => setSelected(new Set()),
    containerProps,
  };
}

/** 선택 모드 아래 동작 줄. 탭바 자리에 뜨고, 고른 카드가 없으면 꺼진다. */
export function SelectBar({
  count,
  busy,
  onMove,
  onPublish,
  onUnpublish,
  onDelete,
}: {
  count: number;
  busy: boolean;
  onMove: () => void;
  onPublish: () => void;
  onUnpublish: () => void;
  onDelete: () => void;
}) {
  const actions = [
    { label: "이동", onClick: onMove, tone: "text-primary" },
    { label: "공개", onClick: onPublish, tone: "text-primary" },
    { label: "미공개", onClick: onUnpublish, tone: "text-ink" },
    { label: "삭제", onClick: onDelete, tone: "text-danger-700" },
  ];
  return (
    <div
      role="toolbar"
      aria-label="고른 카드 처리"
      className="absolute inset-x-4 bottom-[max(20px,env(safe-area-inset-bottom,0px))] z-20 flex h-[68px] items-center gap-1 rounded-[26px] bg-surface p-2 shadow-card"
    >
      {actions.map((action) => (
        <button
          key={action.label}
          type="button"
          disabled={count === 0 || busy}
          onClick={action.onClick}
          className={`flex h-full flex-1 items-center justify-center rounded-[20px] text-[15px] font-bold ${action.tone} disabled:opacity-40 ${focusRing}`}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
