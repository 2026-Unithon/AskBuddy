"use client";

import { useEffect, useId, type ReactNode } from "react";

/** Figma A3 바텀시트: 어두운 덮개 + 아래에서 올라오는 패널. Escape·덮개로 닫는다. */
export function Sheet({
  open,
  onClose,
  title,
  description,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="absolute inset-0 z-40 flex flex-col justify-end">
      <button type="button" aria-label="닫기" onClick={onClose} className="absolute inset-0 bg-ink/40" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative flex flex-col gap-3 rounded-t-[28px] bg-background px-5 pb-[max(24px,env(safe-area-inset-bottom,0px))] pt-3 min-[375px]:px-6 motion-safe:animate-[slideUp_200ms_ease-out]"
      >
        <span aria-hidden className="mx-auto mb-2 h-1 w-10 rounded-full bg-empty" />
        <h2 id={titleId} className="text-[22px] font-bold leading-[1.3] tracking-[-0.44px] text-ink">
          {title}
        </h2>
        {description && (
          <p className="text-[13px] leading-[1.45] tracking-[-0.13px] text-ink-muted [word-break:keep-all]">{description}</p>
        )}
        {children}
      </div>
    </div>
  );
}
