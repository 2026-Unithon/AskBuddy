// 줄 타일 끌기의 순서 계산(계획 10 Task 9). node --test 가 바로 읽도록 import 없이 둔다.

/** from 자리의 타일을 to 자리로. 범위 밖이면 그대로. */
export function moveTile<T>(order: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= order.length || to >= order.length) return [...order];
  const next = [...order];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

/** 타일 자리(들린 타일은 뺀 나머지): 가운데 x 와 위·아래 y. 화면 좌표든 상자 안 좌표든 손가락과 같은 기준이면 된다 */
export type TileBox = { cx: number; top: number; bottom: number };

// 줄 높이 판정의 여유(px). 타일 사이 세로 간격보다 작게
const ROW_SLACK = 8;

/**
 * 손가락(x, y)이 들어갈 자리. 같은 줄에 있는 타일의 앞쪽 절반이면 그 타일 앞,
 * 그 타일 줄보다 위면 그 타일 앞, 어디에도 해당하지 않으면 맨 끝.
 * wrapped: 화살표 줄처럼 한 줄에 여럿이 감기는 모양이면 true(가운데 x 로 가른다),
 * 번호·목록처럼 한 줄에 하나면 false(타일 위·아래 절반으로 가른다). 남은 타일 수로는 알 수 없어 부르는 쪽이 정한다.
 */
export function slotAt(tiles: TileBox[], x: number, y: number, wrapped: boolean): number {
  for (let i = 0; i < tiles.length; i++) {
    const t = tiles[i];
    if (y < t.top - ROW_SLACK) return i;
    if (y > t.bottom + ROW_SLACK) continue;
    // 감긴 줄은 가운데 x 왼쪽이 그 앞, 목록은 위 절반이 그 앞
    if (wrapped ? x < t.cx : y < (t.top + t.bottom) / 2) return i;
  }
  return tiles.length;
}
