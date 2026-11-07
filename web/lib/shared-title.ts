"use client";

/**
 * 목록 제목 → 상세 제목 공유 요소 전환(o05c). React <ViewTransition> 은 상세가 데이터를 받기 전(스켈레톤)이라
 * 짝을 못 찾아 시작하지 않으므로, 브라우저 View Transitions API 를 직접 쓴다.
 * 지원하지 않거나 모션 줄이기면 그냥 이동한다.
 */
export function navigateWithSharedTitle(navigate: () => void, from: HTMLElement | null, name: string) {
  const doc = document as Document & { startViewTransition?: (update: () => Promise<void>) => unknown };
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (!doc.startViewTransition || !from || reduce) {
    navigate();
    return;
  }
  from.style.viewTransitionName = name;
  doc.startViewTransition(async () => {
    from.style.viewTransitionName = "";
    navigate();
    await waitFor(`[data-shared-title="${name}"]`, 600);
  });
}

/** 상세 쪽 제목에 붙이는 속성. 같은 이름이면 브라우저가 둘을 이어 움직인다. */
export function sharedTitleProps(name: string) {
  return { "data-shared-title": name, style: { viewTransitionName: name } };
}

function waitFor(selector: string, timeoutMs: number) {
  return new Promise<void>((resolve) => {
    if (document.querySelector(selector)) return resolve();
    const observer = new MutationObserver(() => {
      if (!document.querySelector(selector)) return;
      observer.disconnect();
      resolve();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    setTimeout(() => {
      observer.disconnect();
      resolve();
    }, timeoutMs);
  });
}
