"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { focusRing, pressable } from "@/components/kit/buttons";
import { apiErrorMessage, chooseReviewValue, type ReviewItem } from "@/lib/api";
import { queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

/**
 * 검수 필요 카드를 열자마자 고르는 상자(계획 7 Task 6, 2026-11-08 사용자 스케치).
 * '맞는 것을 골라 주세요!' 아래 충돌한 두 값을 나란히 버튼으로. 누르면 고르지 않은 값은 '틀린 값'으로 카드에서 빠진다.
 */
export function ReviewPicker({ cardId, versionId, items }: { cardId: number; versionId: number; items: ReviewItem[] }) {
  const { state } = useApp();
  const client = useQueryClient();
  const pick = useMutation({
    mutationFn: ({ item, factId }: { item: ReviewItem; factId: number }) =>
      chooseReviewValue(
        cardId,
        item.conflict_id,
        { keep_fact_id: factId, expected_version_id: versionId, idempotency_key: `pick-${item.conflict_id}-${factId}-${versionId}` },
        state.token!,
      ),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.cardFacts(state.storeId, cardId) }),
        client.invalidateQueries({ queryKey: queryKeys.card(state.storeId, cardId) }),
        client.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
      ]),
  });
  if (items.length === 0) return null;
  return (
    <div role="group" aria-labelledby={`pick-${cardId}`} className="flex flex-col gap-3 rounded-[20px] border-2 border-warn-500 bg-warn-50 px-4 py-4">
      <p id={`pick-${cardId}`} className="text-[17px] font-bold text-ink">
        맞는 것을 골라 주세요!
      </p>
      {items.map((item) => (
        <div key={item.item_id} className="flex flex-col gap-2">
          {item.label && <p className="text-[14px] font-bold text-warn-700">{item.label}</p>}
          <div className="grid grid-cols-2 gap-2">
            {item.options.map((option) => {
              const busy = pick.isPending && pick.variables?.factId === option.fact_id;
              return (
                <button
                  key={option.fact_id}
                  type="button"
                  disabled={pick.isPending}
                  aria-busy={busy || undefined}
                  onClick={() => pick.mutate({ item, factId: option.fact_id })}
                  className={`min-h-14 rounded-[14px] border-2 border-primary/30 bg-surface px-3 py-2 text-[16px] font-bold text-ink shadow-card [word-break:keep-all] disabled:opacity-60 ${pressable} ${focusRing}`}
                >
                  {option.text}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      {pick.error && (
        <p role="alert" className="text-[13px] font-semibold text-danger-700 [word-break:keep-all]">
          {apiErrorMessage(pick.error, "고른 값을 저장하지 못했어요. 다시 골라 주세요.")}
        </p>
      )}
    </div>
  );
}
