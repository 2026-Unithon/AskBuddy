"use client";

import { Card } from "@/components/ui";

interface TaskCardDetailProps {
  title: string;
  content: string;
  categoryName?: string;
}

export function TaskCardDetail({
  title,
  content,
  categoryName = "업무",
}: TaskCardDetailProps) {
  const paragraphs = content.split("\n\n").map((p) => p.trim()).filter(Boolean);

  return (
    <Card className="p-4 space-y-4 border border-border bg-surface shadow-xs">
      <div className="flex items-center gap-2">
        <span className="text-xs font-bold text-foreground/80 bg-surface-muted px-2 py-0.5 rounded-full">
          📋 {categoryName}
        </span>
        <span className="text-[11px] text-muted font-medium">업무 지침</span>
      </div>

      <div>
        <h2 className="text-base font-extrabold text-foreground leading-snug">
          {title}
        </h2>
      </div>

      <div className="space-y-2 pt-1 border-t border-border/60">
        <h3 className="text-xs font-bold text-muted uppercase tracking-wider">
          업무 상세 내용
        </h3>
        <div className="space-y-2 text-xs leading-relaxed text-foreground/90 select-text">
          {paragraphs.map((para, idx) => (
            <p key={idx} className="whitespace-pre-wrap">
              {para}
            </p>
          ))}
        </div>
      </div>
    </Card>
  );
}

