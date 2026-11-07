"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, Suspense, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { enterOf, nextStack, NAV_STACK_KEY, readStack, type NavEnter, type NavMode } from "@/lib/nav-stack";

type NavHistory = {
  /** 앱 안에서 이동해 온 기록이 있는가. 없으면 뒤로 버튼은 부모로 간다. */
  canGoBack: () => boolean;
  /** 지금 화면이 어떻게 들어왔는가. Screen 진입 모션이 쓴다. */
  enter: NavEnter;
  /** 다음 주소 변화를 replace 로 기록한다. router.replace·탭 전환 직전에 부른다. */
  markReplace: () => void;
};

const NavHistoryContext = createContext<NavHistory>({ canGoBack: () => false, enter: "initial", markReplace: () => {} });

function storage() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

// useSearchParams 는 Suspense 경계가 있어야 해서 기록 추적만 따로 떼어 둔다.
// 레이아웃 이펙트라 새 화면이 그려지기 전에 진입 방향(enter)이 정해져, 모션 없이 한 번 보였다가 움직이는 깜빡임이 없다
function NavTracker({ onUrl }: { onUrl: (url: string) => void }) {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const url = search ? `${pathname}?${search}` : pathname;
  useLayoutEffect(() => onUrl(url), [url, onUrl]);
  return null;
}

// 다음 주소 변화가 어떤 방식인지. 라우터가 부르는 history.pushState·replaceState 를 직접 보고 정한다.
// 그래서 router.replace 를 부르는 쪽(가드·로그인·필터·대화 생성)이 따로 표시하지 않아도 replace 로 기록된다.
let pendingMode: NavMode | null = null;
let historyPatched = false;

function urlOf(href: string | URL | null | undefined) {
  if (href === null || href === undefined) return null;
  const next = new URL(String(href), window.location.href);
  return next.pathname + next.search;
}

function patchHistory() {
  if (historyPatched) return;
  historyPatched = true;
  const current = () => window.location.pathname + window.location.search;
  const push = window.history.pushState.bind(window.history);
  const replace = window.history.replaceState.bind(window.history);
  window.history.pushState = (data, unused, href) => {
    const target = urlOf(href);
    if (target !== null && target !== current()) pendingMode = "push";
    push(data, unused, href);
  };
  // 라우터는 같은 주소로도 상태를 덮어쓰므로 주소가 바뀔 때만 replace 로 본다
  window.history.replaceState = (data, unused, href) => {
    const target = urlOf(href);
    if (target !== null && target !== current()) pendingMode = "replace";
    replace(data, unused, href);
  };
  window.addEventListener("popstate", () => {
    pendingMode = "pop";
  });
}

export function NavHistoryProvider({ children }: { children: ReactNode }) {
  const stack = useRef<string[] | null>(null);
  const [enter, setEnter] = useState<NavEnter>("initial");

  useEffect(() => {
    patchHistory();
  }, []);

  const onUrl = useCallback((url: string) => {
    if (stack.current === null) {
      stack.current = readStack(storage(), url);
      pendingMode = null;
      setEnter("initial");
    } else {
      const mode = pendingMode ?? "push";
      pendingMode = null;
      if (stack.current.at(-1) === url) return;
      stack.current = nextStack(stack.current, url, mode);
      setEnter(enterOf(mode));
    }
    try {
      storage()?.setItem(NAV_STACK_KEY, JSON.stringify(stack.current));
    } catch {
      // 저장 못 해도 이 탭 안에서는 메모리 기록으로 동작한다
    }
  }, []);

  const value = useMemo<NavHistory>(
    () => ({
      canGoBack: () => (stack.current?.length ?? 0) > 1,
      enter,
      markReplace: () => {
        pendingMode = "replace";
      },
    }),
    [enter],
  );

  return (
    <NavHistoryContext.Provider value={value}>
      <Suspense fallback={null}>
        <NavTracker onUrl={onUrl} />
      </Suspense>
      {children}
    </NavHistoryContext.Provider>
  );
}

export function useNavHistory() {
  return useContext(NavHistoryContext);
}

/** 앱 뒤로: 앱 안 기록이 있으면 브라우저 뒤로, 없으면(링크로 바로 열림) 부모로 replace. */
export function useBack(parent: string) {
  const router = useRouter();
  const { canGoBack, markReplace } = useNavHistory();
  return useCallback(() => {
    if (canGoBack()) {
      router.back();
      return;
    }
    markReplace();
    router.replace(parent);
  }, [canGoBack, markReplace, parent, router]);
}
