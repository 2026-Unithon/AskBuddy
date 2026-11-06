"use client";

import { useCallback, useEffect, useRef, type MouseEvent, type PointerEvent } from "react";

/**
 * 길게 누르기. ms 동안 누른 채 있으면 한 번 부른다. 그 사이 moveTolerance px 넘게 움직이면(스크롤) 취소.
 * 길게 누르기가 일어난 뒤 이어지는 click 은 막는다(카드 링크로 넘어가지 않게).
 */
export function useLongPress(onLongPress: () => void, { ms = 500, moveTolerance = 10 } = {}) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const fired = useRef(false);

  const cancel = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    start.current = null;
  }, []);
  useEffect(() => cancel, [cancel]);

  return {
    onPointerDown: (event: PointerEvent) => {
      fired.current = false;
      start.current = { x: event.clientX, y: event.clientY };
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        timer.current = null;
        fired.current = true;
        onLongPress();
      }, ms);
    },
    onPointerMove: (event: PointerEvent) => {
      if (!start.current) return;
      if (Math.hypot(event.clientX - start.current.x, event.clientY - start.current.y) > moveTolerance) cancel();
    },
    onPointerUp: cancel,
    onPointerCancel: cancel,
    onContextMenu: (event: MouseEvent) => {
      // 모바일 길게 누르기의 기본 메뉴 대신 우리 시트를 연다
      if (timer.current || fired.current) event.preventDefault();
    },
    // 캡처 단계에서 막아야 안쪽 링크(카드 상세)보다 먼저 멈춘다
    onClickCapture: (event: MouseEvent) => {
      if (!fired.current) return;
      fired.current = false;
      event.preventDefault();
      event.stopPropagation();
    },
  };
}
