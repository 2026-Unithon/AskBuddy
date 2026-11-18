// 카드 제목 옆 금액(2026-11-08 사용자 스케치, 계획 10 뒤 2026-11-18 다시 요청).
// 금액 사실은 칸 이름(금액·판매 가격…)이 제각각이라 낱말이 아니라 단위 칸이 원인 수치 사실로 고른다.

const CURRENCY = "원";

/** 금액 사실이면 '2,000원', 아니면 null. value 는 서버가 뒤 0 없이 준 수치 글이다 */
export function priceOfFact(fact: { value: string | null; unit: string | null }): string | null {
  if (fact.unit !== CURRENCY || fact.value === null) return null;
  const n = Number(fact.value);
  if (!Number.isFinite(n)) return null;
  return `${n.toLocaleString("ko-KR")}${CURRENCY}`;
}

/** 줄이 인용한 사실이 모두 금액이면 그 금액(값이 여럿이면 쉼표로), 하나라도 아니면 null */
export function priceOfLine(prices: (string | null)[]): string | null {
  if (prices.length === 0 || prices.some((p) => p === null)) return null;
  return [...new Set(prices)].join(", ");
}

type PricedBlock<L> = { key: string; heading: string | null; lines: (L & { price?: string | null })[] };

/**
 * 금액 줄을 본문에서 빼고 제목 옆에 둘 금액 글(한 줄에 하나)을 만든다. 금액만 있던 구역은 통째로 빠진다.
 * 규격마다 금액이 다르면 'HOT 1,500원' 처럼 구역 제목을 붙여 줄마다 하나 — 한 줄로 이으면 제목이 밀려 꺾인다.
 */
export function splitPrice<L, B extends PricedBlock<L>>(blocks: B[]): { price: string[]; blocks: B[] } {
  const found: { heading: string | null; price: string }[] = [];
  for (const block of blocks) for (const line of block.lines) if (line.price) found.push({ heading: block.heading, price: line.price });
  if (found.length === 0) return { price: [], blocks };
  const same = new Set(found.map((f) => f.price)).size === 1;
  const price = same ? [found[0].price] : [...new Set(found.map((f) => (f.heading ? `${f.heading} ${f.price}` : f.price)))];
  const rest = blocks
    .map((block) => ({ ...block, lines: block.lines.filter((line) => !line.price) }))
    .filter((block) => block.lines.length > 0);
  return { price, blocks: rest };
}
