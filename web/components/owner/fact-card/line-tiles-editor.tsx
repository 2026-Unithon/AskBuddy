"use client";

import { Fragment, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { focusRing } from "@/components/kit/buttons";
import { headingShown, lineLayout } from "@/lib/line-layout";
import { slotAt } from "@/lib/tile-order";
import type { DraftBlock } from "./line-draft";

// 손가락이 이만큼 움직여야 끌기로 본다(그 전에 떼면 누르기 = 고치기)
const DRAG_PX = 5;
// 상자 밖으로 이만큼 넘게 나가서 놓으면 끌기 전 자리로 돌아간다
const OUTSIDE_PX = 24;

type Drag = {
  block: string;
  key: string;
  startIndex: number;
  x0: number;
  y0: number;
  offX: number;
  offY: number;
  x: number;
  y: number;
  moved: boolean;
  pointerId: number;
};

/**
 * 카드 수정(계획 10, 모션 A): 보기와 같은 모양의 줄 타일을 끌어 순서를 바꾼다.
 * 들린 타일은 손가락을 따라오고, 다른 타일은 220ms 스프링으로 빈자리로 미끄러진다(FLIP).
 * 타일을 누르면 그 줄을 고치고, 키보드는 ←·→(↑·↓)로 옮긴다. 동작 줄이기 설정이면 움직임 없이 바로 바뀐다.
 */
export function LineTilesEditor({
  blocks,
  locked,
  onMove,
  onEdit,
}: {
  blocks: DraftBlock[];
  locked: boolean;
  onMove: (block: string, from: number, to: number) => void;
  onEdit: (lineKey: string) => void;
}) {
  const tiles = useRef(new Map<string, HTMLButtonElement>());
  const boxes = useRef(new Map<string, HTMLDivElement>());
  // 자리를 바꾸기 직전 타일 위치. 다시 그린 뒤 그 차이만큼 되돌렸다가 흘려 보낸다
  const before = useRef<Map<string, DOMRect> | null>(null);
  const drag = useRef<Drag | null>(null);
  const swallowClick = useRef(false);
  const [lifted, setLifted] = useState<string | null>(null);

  const snapshot = () => {
    before.current = new Map([...tiles.current].map(([key, el]) => [key, el.getBoundingClientRect()]));
  };

  // 손가락을 따라오게: 타일의 제자리를 다시 재서 손가락까지의 차이만큼 옮겨 그린다
  const follow = () => {
    const d = drag.current;
    const el = d && tiles.current.get(d.key);
    if (!d || !el || !d.moved) return;
    el.style.transition = "none";
    el.style.transform = "";
    const home = el.getBoundingClientRect();
    el.style.transform = `translate(${d.x - d.offX - home.left}px, ${d.y - d.offY - home.top}px)`;
  };

  const order = blocks.map((b) => `${b.key}=${b.lines.map((l) => l.key).join(",")}`).join("|");
  useLayoutEffect(() => {
    const prev = before.current;
    before.current = null;
    if (prev) {
      const dragged = drag.current?.moved ? drag.current.key : null;
      for (const [key, el] of tiles.current) {
        const was = prev.get(key);
        if (!was || key === dragged) continue;
        const now = el.getBoundingClientRect();
        const dx = was.left - now.left;
        const dy = was.top - now.top;
        if (!dx && !dy) continue;
        // 바뀐 자리에서 옛 자리만큼 되돌려 놓고, 다음 프레임에 원래 transition 으로 0 까지 미끄러진다
        el.style.transition = "none";
        el.style.transform = `translate(${dx}px, ${dy}px)`;
        void el.offsetWidth;
        el.style.transition = "";
        el.style.transform = "";
      }
    }
    follow();
  }, [order]);

  const indexIn = (block: string, key: string) => blocks.find((b) => b.key === block)?.lines.findIndex((l) => l.key === key) ?? -1;

  const onPointerDown = (block: string, key: string) => (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (locked || event.button !== 0) return;
    const box = event.currentTarget.getBoundingClientRect();
    drag.current = {
      block, key, startIndex: indexIn(block, key),
      x0: event.clientX, y0: event.clientY, offX: event.clientX - box.left, offY: event.clientY - box.top,
      x: event.clientX, y: event.clientY, moved: false, pointerId: event.pointerId,
    };
  };

  const onPointerMove = (block: string) => (event: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.block !== block) return;
    d.x = event.clientX;
    d.y = event.clientY;
    if (!d.moved) {
      // 상자 밖에서 손을 뗀 누르기는 끝난 것으로 본다(떠다니는 포인터로 끌기가 시작되지 않게)
      if (event.buttons === 0) {
        drag.current = null;
        return;
      }
      if (Math.hypot(d.x - d.x0, d.y - d.y0) < DRAG_PX) return;
      d.moved = true;
      setLifted(d.key);
      // 끌기로 정해진 뒤에만 손가락을 구역 상자가 쥔다(타일은 자리를 옮길 때 다시 그려진다).
      // 누르기에서 쥐면 click 이 상자로 가서 타일 고치기가 열리지 않는다
      boxes.current.get(block)?.setPointerCapture(d.pointerId);
    }
    const container = event.currentTarget;
    const origin = container.getBoundingClientRect();
    const lines = blocks.find((b) => b.key === block)?.lines ?? [];
    // 자리는 움직이는 중인 모습이 아니라 제자리(offset)로 잰다
    const others = lines
      .filter((l) => l.key !== d.key)
      .map((l) => tiles.current.get(l.key))
      .filter((el): el is HTMLButtonElement => Boolean(el))
      .map((el) => ({ cx: el.offsetLeft + el.offsetWidth / 2, top: el.offsetTop, bottom: el.offsetTop + el.offsetHeight }));
    const wrapped = lineLayout(lines.map((l) => l.text), blocks.find((b) => b.key === block)?.kind ?? "NOTES") === "ARROW";
    const slot = slotAt(others, d.x - origin.left, d.y - origin.top, wrapped);
    const current = indexIn(block, d.key);
    if (slot !== current && current >= 0) {
      snapshot();
      onMove(block, current, slot);
    } else follow();
  };

  const finish = (block: string, cancel: boolean) => (event: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.block !== block) return;
    const el = tiles.current.get(d.key);
    const box = event.currentTarget.getBoundingClientRect();
    const outside =
      d.x < box.left - OUTSIDE_PX || d.x > box.right + OUTSIDE_PX || d.y < box.top - OUTSIDE_PX || d.y > box.bottom + OUTSIDE_PX;
    const moved = d.moved;
    drag.current = null;
    setLifted(null);
    if (!moved) return;
    swallowClick.current = true;
    const current = indexIn(block, d.key);
    if ((cancel || outside) && current !== d.startIndex && current >= 0) {
      snapshot();
      onMove(block, current, d.startIndex);
    }
    // 놓으면 제자리로 들어간다(따라오던 자리에서 0 까지 같은 곡선으로)
    if (el) {
      el.style.transition = "";
      el.style.transform = "";
    }
  };

  const onKeyDown = (block: string, key: string) => (event: KeyboardEvent<HTMLButtonElement>) => {
    if (locked) return;
    const step = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : 0;
    if (!step) return;
    event.preventDefault();
    const lines = blocks.find((b) => b.key === block)?.lines ?? [];
    const from = indexIn(block, key);
    const to = from + step;
    if (from < 0 || to < 0 || to >= lines.length) return;
    snapshot();
    onMove(block, from, to);
  };

  return (
    <div className="flex flex-col gap-3" data-line-tiles="">
      {blocks.map((block, index) => {
        const layout = lineLayout(block.lines.map((l) => l.text), block.kind);
        const arrow = layout === "ARROW";
        return (
          <section key={block.key} className="flex flex-col gap-1.5">
            {headingShown(blocks, index) && <h3 className="px-1 text-[17px] font-bold leading-[1.4] tracking-[-0.34px] text-ink [word-break:keep-all]">{block.heading}</h3>}
            <div
              ref={(el) => {
                if (el) boxes.current.set(block.key, el);
                else boxes.current.delete(block.key);
              }}
              data-layout={layout}
              onPointerMove={onPointerMove(block.key)}
              onPointerUp={finish(block.key, false)}
              onPointerCancel={finish(block.key, true)}
              className={`relative rounded-[18px] bg-surface px-3 py-3 shadow-card ${arrow ? "flex flex-wrap items-center gap-x-1.5 gap-y-2" : "flex flex-col gap-2"}`}
            >
              {block.lines.map((line, i) => (
                <Fragment key={line.key}>
                  {arrow && i > 0 && (
                    <span aria-hidden className="text-[15px] font-bold text-primary">
                      →
                    </span>
                  )}
                  <button
                    type="button"
                    data-tile=""
                    ref={(el) => {
                      if (el) tiles.current.set(line.key, el);
                      else tiles.current.delete(line.key);
                    }}
                    aria-label={`${line.text} 옮기기`}
                    aria-describedby="line-tiles-help"
                    disabled={locked}
                    onPointerDown={onPointerDown(block.key, line.key)}
                    onKeyDown={onKeyDown(block.key, line.key)}
                    onClick={() => {
                      if (swallowClick.current) {
                        swallowClick.current = false;
                        return;
                      }
                      onEdit(line.key);
                    }}
                    className={`relative touch-none select-none rounded-[14px] border-[1.5px] px-3.5 py-2.5 text-left text-[15px] font-semibold leading-[1.4] text-ink [word-break:keep-all] transition-[transform,box-shadow] duration-[220ms] ease-[var(--ease-spring)] motion-reduce:duration-0 disabled:opacity-60 ${
                      arrow ? "max-w-full" : "w-full"
                    } ${lifted === line.key ? "z-10 cursor-grabbing border-primary bg-surface shadow-[0_10px_24px_rgb(0_0_0/0.18)]" : "cursor-grab border-transparent bg-empty"} ${focusRing}`}
                  >
                    {line.text}
                  </button>
                </Fragment>
              ))}
            </div>
          </section>
        );
      })}
      <p id="line-tiles-help" className="sr-only">
        끌거나 화살표 키로 순서를 바꾸고, 누르면 글을 고쳐요.
      </p>
    </div>
  );
}
