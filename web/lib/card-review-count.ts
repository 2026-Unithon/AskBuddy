"use client";

import { useQuery } from "@tanstack/react-query";
import { cardsQuery, proposalsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";
import { reviewCardIds } from "@/lib/review-ids";

/** 카드 '검수 필요' 수: 검수 필요 카드와 다른 답 제안이 걸린 카드의 합집합(같은 카드를 두 번 세지 않는다). 카드 목록·탭 뱃지 공용. */
export function useCardReviewCount() {
  const { state } = useApp();
  const review = useQuery(cardsQuery(state.token, state.storeId, { status: "needs_review", limit: 100 }));
  const proposals = useQuery(proposalsQuery(state.token, state.storeId));
  const ids = reviewCardIds(review.data?.items ?? [], proposals.data?.items ?? []);
  return { count: ids.size, refetch: () => Promise.all([review.refetch(), proposals.refetch()]) };
}
