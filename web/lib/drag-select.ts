// 사진 앱처럼 끌어서 여러 장 고르기(계획 7 Task 5). node --test 가 바로 읽도록 import 없이 둔다.

/**
 * 끌기 시작 카드(anchor)부터 지금 손가락 아래 카드(current)까지 범위를 고른다.
 * 시작 카드가 처음에 골라져 있지 않았으면 범위를 더하고, 골라져 있었으면 범위를 뺀다.
 * base 는 끌기 시작 전 선택이라, 되돌아 끌면 범위 밖 칸은 처음 상태로 돌아간다.
 */
export function rangeSelect(order: number[], anchor: number, current: number, base: Set<number>): Set<number> {
  const from = order.indexOf(anchor);
  const to = order.indexOf(current);
  if (from < 0 || to < 0) return new Set(base);
  const adding = !base.has(anchor);
  const next = new Set(base);
  for (const id of order.slice(Math.min(from, to), Math.max(from, to) + 1)) {
    if (adding) next.add(id);
    else next.delete(id);
  }
  return next;
}
