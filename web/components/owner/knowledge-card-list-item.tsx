"use client";

import Link from "next/link";
import { Badge, Button, Card } from "@/components/ui";
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
  actingAction = null,
}: {
  card: CardListItem;
  onApprove?: (cardId: number) => void;
  onExclude?: (cardId: number) => void;
  isActing?: boolean;
  actingAction?: "approve" | "exclude" | "restore" | null;
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
            <span className="text-xs text-muted">수동분류</span>
          )}
        </div>
        <CardStatusBadge status={card.review_status} />
      </div>

      {/* 카드 제목 및 내용 미리보기 */}
      <Link href={`/owner/cards/${card.card_id}`} className="block group">
        <h3 className="text-base font-bold text-foreground leading-snug group-hover:text-brand-700 transition-colors line-clamp-1 select-text">
          {card.title}
        </h3>
        <p className="mt-1 text-sm text-muted line-clamp-2 leading-relaxed select-text">
          {card.content}
        </p>
      </Link>

      {/* 하단 메타 및 빠른 액션 */}
      <div className="flex items-center justify-between pt-1.5 border-t border-border/50 text-xs">
        <div className="flex items-center gap-2 text-xs text-muted truncate">
          <span>{card.source?.title ?? "매장 자료"}</span>
          <span>·</span>
          <span>{formatDate(card.updated_at)}</span>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {isPendingReview && onApprove && (
            <Button
              loading={isActing && actingAction === "approve"}
              loadingLabel="공개 중"
              disabled={isActing}
              onClick={() => onApprove(card.card_id)}
              className="px-3 text-sm"
            >
              공개
            </Button>
          )}
          {card.review_status !== "EXCLUDED" && onExclude && (
            <Button
              variant="secondary"
              loading={isActing && actingAction === "exclude"}
              loadingLabel="제외 중"
              disabled={isActing}
              onClick={() => {
                if (window.confirm("이 카드를 직원 화면과 검색에서 제외할까요? 나중에 다시 복원할 수 있습니다.")) {
                  onExclude(card.card_id);
                }
              }}
              className="px-3 text-sm"
            >
              제외
            </Button>
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
