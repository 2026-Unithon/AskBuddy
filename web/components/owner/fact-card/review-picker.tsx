"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/kit/buttons";
import { focusRing, pressable } from "@/components/kit/buttons";
import { apiErrorMessage, chooseReviewValue, writeReviewValue, type ReviewItem } from "@/lib/api";
import { queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

type Choose = Extract<ReviewItem, { kind: "CHOOSE" }>;
type Write = Extract<ReviewItem, { kind: "WRITE" }>;

/**
 * 검수 필요 카드를 열자마자 하는 상자(계획 7 Task 6, 2026-11-08 사용자 스케치).
 * 충돌은 '맞는 것을 골라 주세요!' 아래 두 값 버튼, 근거 없는 줄은 그 자리 글 입력칸.
 */
export function ReviewPicker({ cardId, versionId, items }: { cardId: number; versionId: number; items: ReviewItem[] }) {
  const { state } = useApp();
  const client = useQueryClient();
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: queryKeys.cardFacts(state.storeId, cardId) }),
      client.invalidateQueries({ queryKey: queryKeys.card(state.storeId, cardId) }),
      client.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
    ]);
  const pick = useMutation({
    mutationFn: ({ item, factId }: { item: Choose; factId: number }) =>
      chooseReviewValue(
        cardId,
        item.conflict_id,
        { keep_fact_id: factId, expected_version_id: versionId, idempotency_key: `pick-${item.conflict_id}-${factId}-${versionId}` },
        state.token!,
      ),
    onSuccess: refresh,
  });
  const write = useMutation({
    mutationFn: ({ item, text }: { item: Write; text: string }) =>
      writeReviewValue(
        cardId,
        { fact_revision_id: item.fact_revision_id, text, expected_version_id: versionId, idempotency_key: `write-${item.fact_revision_id}-${versionId}` },
        state.token!,
      ),
    onSuccess: refresh,
  });
  const chooses = items.filter((i): i is Choose => i.kind === "CHOOSE");
  const writes = items.filter((i): i is Write => i.kind === "WRITE");
  if (items.length === 0) return null;
  const title = chooses.length > 0 ? "맞는 것을 골라 주세요!" : "고쳐 적어 주세요";
  const error = pick.error ?? write.error;
  return (
    <div role="group" aria-labelledby={`pick-${cardId}`} className="flex flex-col gap-3 rounded-[20px] border-2 border-warn-500 bg-warn-50 px-4 py-4">
      <p id={`pick-${cardId}`} className="text-[17px] font-bold text-ink">
        {title}
      </p>
      {chooses.map((item) => (
        <div key={item.item_id} className="flex flex-col gap-2">
          {item.label && <p className="text-[14px] font-bold text-warn-700">{item.label}</p>}
          <div className="grid grid-cols-2 gap-2">
            {item.options.map((option) => (
              <button
                key={option.fact_id}
                type="button"
                disabled={pick.isPending || write.isPending}
                onClick={() => pick.mutate({ item, factId: option.fact_id })}
                className={`min-h-14 rounded-[14px] border-2 border-primary/30 bg-surface px-3 py-2 text-[16px] font-bold text-ink shadow-card [word-break:keep-all] disabled:opacity-60 ${pressable} ${focusRing}`}
              >
                {option.text}
              </button>
            ))}
          </div>
        </div>
      ))}
      {writes.map((item) => (
        <WriteRow key={item.item_id} item={item} busy={pick.isPending || write.isPending} onSave={(text) => write.mutate({ item, text })} />
      ))}
      {error && (
        <p role="alert" className="text-[13px] font-semibold text-danger-700 [word-break:keep-all]">
          {apiErrorMessage(error, "저장하지 못했어요. 다시 해 주세요.")}
        </p>
      )}
    </div>
  );
}

function WriteRow({ item, busy, onSave }: { item: Write; busy: boolean; onSave: (text: string) => void }) {
  // 입력 초안(서버 값 아님)
  const [text, setText] = useState(item.text);
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (text.trim() && !busy) onSave(text.trim());
      }}
    >
      {item.label && <p className="text-[14px] font-bold text-warn-700 [word-break:keep-all]">{item.label}</p>}
      <textarea
        aria-label="고쳐 적을 내용"
        value={text}
        rows={2}
        maxLength={2000}
        onChange={(event) => setText(event.target.value)}
        className={`rounded-[14px] bg-surface px-4 py-3 text-[16px] leading-[1.5] text-ink shadow-card outline-none ${focusRing}`}
      />
      <Button type="submit" loading={busy} disabled={!text.trim()}>
        저장
      </Button>
    </form>
  );
}
