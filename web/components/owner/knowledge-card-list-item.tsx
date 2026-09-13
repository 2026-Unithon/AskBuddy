"use client";

import Link from "next/link";
import { Badge, Card } from "@/components/ui";
import type { CardListItem } from "@/lib/api";
import { CardStatusBadge } from "./status-badge";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ko-KR", {
    month: "numeric",
    day: "numeric",
  });
}

export function KnowledgeCardListItem({
  card,
  onApprove,
  onExclude,
  isActing = false,
}: {
  card: CardListItem;
  onApprove?: (cardId: number) => void;
  onExclude?: (cardId: number) => void;
  isActing?: boolean;
}) {
  const isPendingReview = card.review_status === "PENDING" || card.review_status === "NEEDS_REVIEW";

  return (
    <Card className="p-3.5 space-y-2.5 border border-border bg-surface transition-all active:scale-[0.99] hover:border-brand-300 shadow-2xs">
      {/* 상단 메타: 카테고리 + 검토 상태 */}
      <div className="flex items-center justify-between gap-1.5 flex-wrap">
        <div className="flex items-center gap-1.5 min-w-0">
          <Badge tone="neutral">
            {card.category?.name ?? "기타"}
          </Badge>
          {card.assignment_type === "MANUAL" && (
            <span className="text-[10px] text-muted">수동분류</span>
          )}
        </div>
        <CardStatusBadge status={card.review_status} />
      </div>

      {/* 카드 제목 및 내용 미리보기 */}
      <Link href={`/owner/cards/${card.card_id}`} className="block group">
        <h3 className="text-xs font-bold text-foreground leading-snug group-hover:text-brand-700 transition-colors line-clamp-1 select-text">
          {card.title}
        </h3>
        <p className="mt-1 text-[11px] text-muted line-clamp-2 leading-relaxed select-text">
          {card.content}
        </p>
      </Link>

      {/* 하단 메타 및 빠른 액션 */}
      <div className="flex items-center justify-between pt-1.5 border-t border-border/50 text-xs">
        <div className="flex items-center gap-2 text-[10px] text-muted truncate">
          <span>{card.source?.title ?? "매장 자료"}</span>
          <span>·</span>
          <span>{formatDate(card.updated_at)}</span>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {isPendingReview && onApprove && (
            <button
              type="button"
              disabled={isActing}
              onClick={() => onApprove(card.card_id)}
              className="min-h-[44px] px-3 rounded-lg bg-brand-500 text-white font-bold text-xs hover:bg-brand-600 active:scale-[0.95] transition-all disabled:opacity-50"
            >
              공개
            </button>
          )}
          {card.review_status !== "EXCLUDED" && onExclude && (
            <button
              type="button"
              disabled={isActing}
              onClick={() => onExclude(card.card_id)}
              className="min-h-[44px] px-3 rounded-lg bg-surface-muted text-muted font-bold text-xs hover:text-danger-500 active:scale-[0.95] transition-all disabled:opacity-50"
            >
              제외
            </button>
          )}
          <Link
            href={`/owner/cards/${card.card_id}`}
            className="inline-flex min-h-[44px] items-center px-2 text-xs font-bold text-brand-700 hover:text-brand-800"
          >
            상세 →
          </Link>
        </div>
      </div>
    </Card>
  );
}
