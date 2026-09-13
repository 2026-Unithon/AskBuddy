"use client";

import { Badge } from "@/components/ui";
import type { UploadSourceType } from "@/lib/types";

export interface QueuedUploadFile {
  id: string;
  file: File;
  sourceType: UploadSourceType;
  status: "pending" | "uploading" | "registered" | "error";
  sourceId?: number;
  errorMessage?: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function sourceTypeBadge(type: UploadSourceType) {
  switch (type) {
    case "VOICE":
      return { tone: "brand" as const, label: "🎙 음성" };
    case "VIDEO":
      return { tone: "brand" as const, label: "🎥 영상" };
    case "KAKAO":
      return { tone: "warn" as const, label: "💬 카톡" };
    case "SCAN":
    default:
      return { tone: "neutral" as const, label: "📄 문서/사진" };
  }
}

export function UploadQueueItem({
  item,
  onRemove,
  disabled = false,
}: {
  item: QueuedUploadFile;
  onRemove: (id: string) => void;
  disabled?: boolean;
}) {
  const badge = sourceTypeBadge(item.sourceType);

  return (
    <div className="flex items-center justify-between gap-2.5 rounded-xl border border-border bg-surface p-3 shadow-2xs">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge tone={badge.tone}>{badge.label}</Badge>
          <span className="text-[11px] text-muted font-medium">
            {formatBytes(item.file.size)}
          </span>
          {item.status === "uploading" && (
            <span className="text-[11px] text-brand-600 font-bold animate-pulse">
              업로드 중…
            </span>
          )}
          {item.status === "registered" && (
            <span className="text-[11px] text-brand-600 font-bold">
              파일 등록 완료
            </span>
          )}
          {item.status === "error" && (
            <span className="text-[11px] text-danger-600 font-bold">
              {item.errorMessage ?? "실패"}
            </span>
          )}
        </div>
        <p className="text-xs font-semibold text-foreground truncate select-text">
          {item.file.name}
        </p>
      </div>

      {!disabled && item.status !== "uploading" && (
        <button
          type="button"
          onClick={() => onRemove(item.id)}
          aria-label={`${item.file.name} 대기열에서 삭제`}
          className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-muted hover:text-danger-600 active:scale-95 transition-colors"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  );
}
