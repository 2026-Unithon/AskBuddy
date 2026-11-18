// 카드 줄 보기 모양(계획 10, D23). 모양은 줄 길이와 구역 종류로만 정한다 — 사실 모양으로 추측하지 않는다.
export type LineLayout = "ARROW" | "NUMBERED" | "LIST";

// 이 길이 이하의 단계만 있으면 화살표 한 줄(2샷 → 얼음 가득 → 물 붓기)로 보인다
export const ARROW_MAX_CHARS = 16;

export function lineLayout(lines: string[], kind: string): LineLayout {
  if (kind !== "STEPS") return "LIST";
  return lines.every((line) => [...line].length <= ARROW_MAX_CHARS) ? "ARROW" : "NUMBERED";
}

/** 구역 제목을 보일지. 제목이 없거나 바로 앞 구역과 같으면 보이지 않는다(한 규격이 여러 구역이어도 제목은 한 번) */
export function headingShown(blocks: { heading: string | null }[], index: number): boolean {
  const heading = blocks[index]?.heading;
  return Boolean(heading) && (index === 0 || blocks[index - 1]?.heading !== heading);
}
