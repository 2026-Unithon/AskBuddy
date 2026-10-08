"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

/** Figma A3 바텀시트: 어두운 덮개 + 아래에서 올라오는 패널. Escape·덮개로 닫는다. */
export function Sheet({
  open,
  onClose,
  title,
  description,
  children,
  dismissible = true,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  dismissible?: boolean;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const dialog = panel.current;
    if (!dialog) return;
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    dialog.focus();
    const focusables = () =>
      Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href], [tabindex="0"]',
        ),
      );
    const onTab = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const elements = focusables();
      const first = elements[0],
        last = elements.at(-1);
      if (!first || !last) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      if (
        event.shiftKey &&
        (document.activeElement === first || document.activeElement === dialog)
      ) {
        event.preventDefault();
        last.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last || document.activeElement === dialog)
      ) {
        event.preventDefault();
        first.focus();
      }
    };
    const keepFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && !dialog.contains(event.target))
        dialog.focus();
    };
    document.addEventListener("keydown", onTab);
    document.addEventListener("focusin", keepFocus);
    return () => {
      document.removeEventListener("keydown", onTab);
      document.removeEventListener("focusin", keepFocus);
      if (previous?.isConnected) previous.focus();
    };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (dismissible && event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, dismissible]);

  if (!open) return null;
  return (
    <div className="absolute inset-0 z-40 flex flex-col justify-end">
      {dismissible ? (
        <button
          type="button"
          aria-label="닫기"
          onClick={onClose}
          className="absolute inset-0 bg-ink/40"
        />
      ) : (
        <div className="absolute inset-0 bg-ink/40" />
      )}
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative flex max-h-[90dvh] flex-col gap-3 overflow-y-auto rounded-t-[28px] bg-background px-5 pb-[max(24px,env(safe-area-inset-bottom,0px))] pt-3 min-[375px]:px-6 motion-safe:animate-[slideUp_200ms_ease-out]"
      >
        <span
          aria-hidden
          className="mx-auto mb-2 h-1 w-10 rounded-full bg-empty"
        />
        <h2
          id={titleId}
          className="text-[22px] font-bold leading-[1.3] tracking-[-0.44px] text-ink"
        >
          {title}
        </h2>
        {description && (
          <p className="text-[13px] leading-[1.45] tracking-[-0.13px] text-ink-muted [word-break:keep-all]">
            {description}
          </p>
        )}
        {children}
      </div>
    </div>
  );
}
