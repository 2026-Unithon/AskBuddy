"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { cardQuery } from "@/lib/query";
import { useApp } from "@/lib/store";
import { navigateWithSharedTitle } from "@/lib/shared-title";
import { focusRing, pressable } from "@/components/kit/buttons";
import { SwipeRow, type SwipeAction } from "@/components/kit/swipe-row";
import type { CardListItem } from "@/lib/api";

export type TileStatus = "approved" | "review" | "pending";

const STATUS_WORD: Record<TileStatus, string> = { approved: "공개", review: "검수 필요", pending: "미공개" };

// 상태는 글자가 아니라 모양으로(o05c): 공개는 흰 카드와 초록 점, 검수 필요는 주황 테두리, 미공개는 점선
const STATUS_CLASS: Record<TileStatus, string> = {
  approved: "bg-surface shadow-card",
  review: "border-2 border-warn-500 bg-warn-50",
  // 밀기 버튼이 뒤에 깔려 있어 배경은 불투명해야 한다(투명이면 '공개'·'삭제' 판이 비친다)
  pending: "border-2 border-dashed border-ink-muted/40 bg-background",
};
const DOT_CLASS: Record<TileStatus, string | null> = { approved: "bg-primary", review: "bg-warn-500", pending: null };

export function tileStatus(card: CardListItem, hasProposal: boolean): TileStatus {
  if (card.review_status === "NEEDS_REVIEW" || hasProposal) return "review";
  return card.review_status === "APPROVED" ? "approved" : "pending";
}

/** 카드 목록 2열의 한 장. 이름과 꺾쇠만 보이고, 제안이 걸렸으면 아래에 톤온톤 띠. 이름은 상세 제목으로 이어진다. */
export function CardTile({
  card,
  status,
  proposal = false,
  left,
  right,
  select,
}: {
  card: CardListItem;
  status: TileStatus;
  proposal?: boolean;
  left?: SwipeAction;
  right?: SwipeAction;
  /** 선택 모드(계획 7 Task 5): 누르면 고르기, 상세로 가지 않고 밀기도 없다 */
  select?: { selected: boolean; onToggle: () => void };
}) {
  const router = useRouter();
  const client = useQueryClient();
  const { state } = useApp();
  const title = useRef<HTMLSpanElement>(null);
  const href = proposal ? `/owner/cards/proposals?card_id=${card.card_id}` : `/owner/cards/${card.card_id}`;
  const dot = DOT_CLASS[status];
  if (select) {
    return (
      <button
        type="button"
        data-card-tile=""
        data-card-id={card.card_id}
        aria-pressed={select.selected}
        aria-label={`${card.title}, ${STATUS_WORD[status]}`}
        onClick={select.onToggle}
        className={`relative flex min-h-[72px] w-full touch-pan-y select-none flex-col justify-between gap-2 rounded-[18px] px-3.5 py-3 text-left ${STATUS_CLASS[status]} ${
          select.selected ? "outline-2 outline-solid outline-primary -outline-offset-2" : ""
        } ${focusRing}`}
      >
        {dot && <span aria-hidden className={`absolute left-2.5 top-2.5 size-2 rounded-full ${dot}`} />}
        <span className="flex items-start gap-2 pl-2">
          <span className={`line-clamp-2 min-w-0 flex-1 text-[15px] font-bold leading-[1.4] [word-break:keep-all] ${status === "pending" ? "text-ink-muted" : "text-ink"}`}>
            {card.title}
          </span>
          {/* 사진 앱처럼 오른쪽 위 동그라미에 체크 */}
          <span
            aria-hidden
            className={`flex size-[22px] shrink-0 items-center justify-center rounded-full border-2 text-[12px] font-bold ${
              select.selected ? "border-primary bg-primary text-white" : "border-ink-muted/40 bg-surface"
            }`}
          >
            {select.selected ? "✓" : ""}
          </span>
        </span>
      </button>
    );
  }
  const tile = (
    <Link
      href={href}
      draggable={false}
      onNavigate={(event) => {
        // 상세로 갈 때만 제목을 이어 움직인다(제안 화면은 제목이 없다)
        if (proposal) return;
        event.preventDefault();
        navigateWithSharedTitle(() => router.push(href), title.current, `card-title-${card.card_id}`);
      }}
      data-status={status}
      data-card-tile=""
      data-card-id={card.card_id}
      aria-label={`${card.title}, ${STATUS_WORD[status]}${proposal ? ", 다른 답이 있어요" : ""}`}
      // 누르는 순간 상세를 미리 받아 둔다(제목이 이어 움직이는 동안 기다리지 않게)
      onPointerDown={() => {
        if (!proposal) void client.prefetchQuery(cardQuery(state.token, state.storeId, card.card_id));
      }}
      className={`relative flex min-h-[72px] flex-col justify-between gap-2 rounded-[18px] px-3.5 py-3 ${STATUS_CLASS[status]} ${pressable} ${focusRing}`}
    >
      {dot && <span aria-hidden className={`absolute left-2.5 top-2.5 size-2 rounded-full ${dot}`} />}
      <span className="flex items-start gap-1 pl-2">
        <span ref={title} className={`line-clamp-2 min-w-0 flex-1 text-[15px] font-bold leading-[1.4] [word-break:keep-all] ${status === "pending" ? "text-ink-muted" : "text-ink"}`}>
            {card.title}
          </span>
        <span aria-hidden className="text-[18px] leading-none text-ink-muted">
          ›
        </span>
      </span>
      {proposal && <span className="rounded-[8px] bg-brand-100 px-2 py-1 text-[12px] font-bold text-brand-800">다른 답이 있어요</span>}
    </Link>
  );
  if (!left && !right) return tile;
  return (
    <SwipeRow left={left} right={right}>
      {tile}
    </SwipeRow>
  );
}
