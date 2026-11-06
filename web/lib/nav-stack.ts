// 앱 안 이동 기록. 뒤로 버튼이 "왔던 곳"으로 갈지 "부모"로 갈지 정하는 근거다.
// node --test 가 바로 읽도록 import 없이 순수 함수만 둔다.

export type NavMode = "push" | "replace" | "pop";
export type NavEnter = "forward" | "back" | "fade" | "initial";

export const NAV_STACK_KEY = "askbuddy:nav-stack";
export const NAV_STACK_LIMIT = 50;

/** 주소가 바뀐 방식에 따라 기록을 갱신한다. pop 은 기록 안에서 그 주소가 있는 자리까지 자르고, 없으면 브라우저 앞으로 가기로 보고 쌓는다. */
export function nextStack(stack: string[], url: string, mode: NavMode): string[] {
  const top = stack.at(-1);
  if (top === url) return stack;
  let next: string[];
  if (mode === "replace") next = [...stack.slice(0, -1), url];
  else if (mode === "pop" && stack.lastIndexOf(url, -2) >= 0) next = stack.slice(0, stack.lastIndexOf(url, -2) + 1);
  else next = [...stack, url];
  return next.length > NAV_STACK_LIMIT ? next.slice(next.length - NAV_STACK_LIMIT) : next;
}

/** 화면 진입 모션 방향. 탭 전환처럼 replace 는 방향 없이 페이드. */
export function enterOf(mode: NavMode | "initial"): NavEnter {
  if (mode === "push") return "forward";
  if (mode === "pop") return "back";
  if (mode === "replace") return "fade";
  return "initial";
}

/** 새로고침이면 저장된 기록을 잇고, 다른 주소로 새로 열렸거나 저장소를 못 쓰면 지금 주소 하나로 시작한다. */
export function readStack(storage: Pick<Storage, "getItem"> | null, url: string): string[] {
  try {
    const raw = storage?.getItem(NAV_STACK_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (Array.isArray(parsed) && parsed.every((item) => typeof item === "string") && parsed.at(-1) === url) {
      return parsed;
    }
  } catch {
    // 개인 모드 등에서 sessionStorage 가 막혀도 기록 없음으로 동작한다
  }
  return [url];
}
