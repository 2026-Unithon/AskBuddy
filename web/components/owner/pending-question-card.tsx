"use client";

import { Card } from "@/components/ui";
import { QuestionStatusBadge } from "./status-badge";

export interface AggregatedQuestionItem {
  key: string;
  waitingQuestionId: number | null;
  questionText: string;
  firstAskedAt: string;
  lastAskedAt: string;
  distinctStaffCount: number;
  occurrenceCount: number;
  status: "WAITING" | "OWNER_ANSWERED" | "HIT";
  answerText: string | null;
  messageId: number;
}

function formatWaitingDuration(isoString: string): string {
  const diffMs = Date.now() - new Date(isoString).getTime();
  if (diffMs < 0) return "방금 전";
  const diffMins = Math.floor(diffMs / (1000 * 60));
  if (diffMins < 60) return `${Math.max(1, diffMins)}분째 대기`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}시간째 대기`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}일째 대기`;
}

function formatTime(isoString: string): string {
  return new Date(isoString).toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function PendingQuestionCard({
  item,
  onSelect,
  isSelected = false,
}: {
  item: AggregatedQuestionItem;
  onSelect: (item: AggregatedQuestionItem) => void;
  isSelected?: boolean;
}) {
  const isWaiting = item.status === "WAITING";
  const waitingDuration = formatWaitingDuration(item.firstAskedAt);

  const content = (
    <Card
      className={`p-4 space-y-3 transition-all border ${
        isSelected
          ? "border-brand-500 ring-2 ring-brand-500/20 bg-brand-50/20"
          : isWaiting
          ? "cursor-pointer border-warn-500/40 bg-surface hover:border-warn-500 active:scale-[0.98]"
          : "border-border bg-surface hover:border-brand-200"
      }`}
    >
      {/* 상단 메타데이터: 대기시간 / 발생횟수 / 배지 */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          {isWaiting && (
            <span className="inline-flex items-center gap-1 rounded-md bg-warn-50 px-2 py-0.5 text-xs font-bold text-warn-700 border border-warn-200/60">
              <span className="h-1.5 w-1.5 rounded-full bg-warn-500 motion-safe:animate-pulse" />
              {waitingDuration}
            </span>
          )}
          {item.occurrenceCount > 1 && (
            <span className="rounded-md bg-accent-50 px-2 py-0.5 text-xs font-bold text-accent-700 border border-accent-200/60">
              {item.occurrenceCount}회 반복
            </span>
          )}
          <span className="text-xs font-medium text-muted">
            직원 {item.distinctStaffCount}명 질문
          </span>
        </div>
        <QuestionStatusBadge status={item.status} />
      </div>

      {/* 질문 본문 */}
      <p className="text-base font-bold text-foreground leading-snug select-text">
        Q. {item.questionText}
      </p>

      {!isWaiting && item.answerText && (
        <p className="rounded-xl bg-surface-muted/50 p-3 text-base leading-relaxed text-foreground/80">
          A. {item.answerText}
        </p>
      )}

      {/* 하단 시각 및 원터치 답변 CTA */}
      <div className="flex items-center justify-between pt-1 border-t border-border/50 text-xs">
        <span className="text-xs text-muted">
          최근: {formatTime(item.lastAskedAt)}
        </span>
        {isWaiting && (
          <span className="font-bold text-xs text-brand-600 group-hover:text-brand-700 flex items-center gap-1">
            답변하기 →
          </span>
        )}
      </div>
    </Card>
  );

  if (!isWaiting) return content;

  return (
    <button
      type="button"
      className="block w-full text-left"
      onClick={() => onSelect(item)}
    >
      {content}
    </button>
  );
}
