"use client";

import Link from "next/link";
import { Button, Card } from "@/components/ui";

interface EmptyStateProps {
  icon?: string;
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
}

export function EmptyState({
  icon = "📋",
  title,
  description,
  actionHref,
  actionLabel,
  onAction,
  className = "",
}: EmptyStateProps) {
  return (
    <Card className={`p-8 text-center space-y-3 bg-surface/90 border-dashed border-2 border-border/80 ${className}`}>
      <span className="sr-only" data-testid="empty-state">빈 상태</span>
      <span className="text-3xl block select-none" aria-hidden="true">
        {icon}
      </span>
      <div className="space-y-1 max-w-xs mx-auto">
        <h3 className="text-base font-bold text-foreground leading-snug">{title}</h3>
        <p className="text-sm text-muted leading-relaxed whitespace-pre-line">{description}</p>
      </div>
      {(actionHref || onAction) && actionLabel && (
        <div className="pt-2">
          {actionHref ? (
            <Link
              href={actionHref}
              className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-brand-500 px-5 text-sm font-bold text-white shadow-xs transition-transform active:scale-95 hover:bg-brand-600"
            >
              {actionLabel}
            </Link>
          ) : (
            <Button
              variant="primary"
              size="md"
              className="min-h-[44px] text-sm font-bold active:scale-95"
              onClick={onAction}
            >
              {actionLabel}
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
