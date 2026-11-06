"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

/**
 * 당겨서 새로고침. 스크롤 영역이 맨 위일 때만 아래로 끄는 것을 잡고, threshold 넘게 끌고 놓으면 onRefresh 를 기다린다.
 * 끄는 거리는 손가락 이동의 절반(저항감).
 * - 손가락: touch 이벤트를 non-passive 로 들어 아래로 당기기 시작하면 기본 동작(브라우저 새로고침·튕김)을 막는다.
 *   pointer 이벤트는 브라우저가 몸짓을 가져가며 pointercancel 을 보내 폰에서 동작하지 않는다.
 * - 마우스: pointer 이벤트, 누른 버튼이 있을 때만, 영역 밖에서 놓아도 끝나게 붙잡는다.
 */
export function usePullToRefresh(
  target: RefObject<HTMLElement | null>,
  onRefresh: (() => Promise<unknown>) | undefined,
  { threshold = 64 } = {},
) {
  const [pull, setPull] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const latest = useRef({ onRefresh, refreshing, pull });
  useEffect(() => {
    latest.current = { onRefresh, refreshing, pull };
  });

  // onRefresh 는 화면마다 매번 새 함수라 의존성에 넣지 않는다(당기는 중 다시 붙으면 몸짓을 잃는다). 최신 값은 ref 로 읽는다
  const enabled = Boolean(onRefresh);
  useEffect(() => {
    const el = target.current;
    if (!el || !enabled) return;
    let startY: number | null = null;
    let current = 0;
    const begin = (y: number) => {
      if (latest.current.refreshing || el.scrollTop > 0) return false;
      startY = y;
      current = 0;
      return true;
    };
    const update = (y: number) => {
      if (startY === null) return false;
      const dy = (y - startY) * 0.5;
      current = dy > 0 ? Math.min(dy, threshold * 1.5) : 0;
      setPull(current);
      return current > 0;
    };
    const finish = () => {
      if (startY === null) return;
      const reached = current >= threshold;
      startY = null;
      current = 0;
      setPull(0);
      const run = latest.current.onRefresh;
      if (!reached || !run) return;
      setRefreshing(true);
      void run().finally(() => setRefreshing(false));
    };
    const cancel = () => {
      startY = null;
      current = 0;
      setPull(0);
    };

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length === 1) begin(e.touches[0].clientY);
    };
    const onTouchMove = (e: TouchEvent) => {
      // 아래로 당기는 중이면 페이지 튕김·브라우저 새로고침 대신 우리 표시를 쓴다
      if (update(e.touches[0].clientY) && e.cancelable) e.preventDefault();
    };
    const onPointerDown = (e: PointerEvent) => {
      if (e.pointerType !== "mouse" || e.button !== 0 || !begin(e.clientY)) return;
      const pointerId = e.pointerId;
      const move = (m: PointerEvent) => {
        if (m.pointerId !== pointerId) return;
        if (m.buttons === 0) return stop(m);
        update(m.clientY);
      };
      const stop = (m: PointerEvent) => {
        if (m.pointerId !== pointerId) return;
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
        window.removeEventListener("pointercancel", stop);
        if (m.type === "pointercancel") cancel();
        else finish();
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
      window.addEventListener("pointercancel", stop);
    };

    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: false });
    el.addEventListener("touchend", finish);
    el.addEventListener("touchcancel", cancel);
    el.addEventListener("pointerdown", onPointerDown);
    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", finish);
      el.removeEventListener("touchcancel", cancel);
      el.removeEventListener("pointerdown", onPointerDown);
    };
  }, [target, enabled, threshold]);

  return { pull, refreshing, threshold };
}

/** 위쪽 새로고침 표시. 끄는 동안은 끈 만큼 돌고, 새로고침 중엔 계속 돈다. */
export function PullIndicator({ pull, refreshing, threshold }: { pull: number; refreshing: boolean; threshold: number }) {
  if (!pull && !refreshing) return null;
  return (
    <div role="status" aria-label="새로고침 중" className="pointer-events-none flex justify-center" style={{ height: refreshing ? 36 : pull * 0.6 }}>
      <span
        aria-hidden
        className={`mt-2 size-5 rounded-full border-2 border-primary border-r-transparent ${refreshing ? "motion-safe:animate-spin" : ""}`}
        style={refreshing ? undefined : { transform: `rotate(${(pull / threshold) * 270}deg)`, opacity: Math.min(1, pull / threshold) }}
      />
    </div>
  );
}
