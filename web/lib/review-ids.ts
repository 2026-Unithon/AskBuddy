// 카드 '검수 필요' 대상 id: 검수 필요 카드와 다른 답 제안이 걸린 카드의 합집합.
// 삭제(EXCLUDED)된 카드에 걸린 제안은 어디에도 보이지 않으므로 세지 않는다(2026-11-08). node --test 가 바로 읽는다.

type Proposal = { target_card_id: number | null; target_review_status?: string | null };

export function reviewCardIds(review: { card_id: number }[], proposals: Proposal[]): Set<number> {
  return new Set<number>([
    ...review.map((card) => card.card_id),
    ...proposals.flatMap((p) => (p.target_card_id === null || p.target_review_status === "EXCLUDED" ? [] : [p.target_card_id])),
  ]);
}
