"use client";

import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Button, focusRing } from "@/components/kit/buttons";

// 알림·피드백 기준(G4): 되돌릴 필요 없는 완료는 토스트, 되돌릴 수 있는 완료는 스낵바,
// 되돌릴 수 없는 일은 확인 창, 화면 전체 상태는 배너, 입력 칸 하나의 문제는 칸 아래 문구(ErrorInline).

const TOAST_MS = 2000;
const SNACKBAR_MS = 5000;

type SnackbarOptions = { message: string; actionLabel: string; onAction: () => void; durationMs?: number };
type Notice = { id: number; message: string; action?: { label: string; onClick: () => void }; keepOnNavigate?: boolean };
/** durationMs: 꼭 읽어야 하는 안내(일부 실패 등)는 기본 2초보다 길게 */
type ToastOptions = { keepOnNavigate?: boolean; durationMs?: number };
type Feedback = { toast: (message: string, opts?: ToastOptions) => void; snackbar: (opts: SnackbarOptions) => void; dismiss: () => void };

const FeedbackContext = createContext<Feedback>({ toast: () => {}, snackbar: () => {}, dismiss: () => {} });

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [notice, setNotice] = useState<Notice | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seq = useRef(0);
  const remaining = useRef(0);
  const startedAt = useRef(0);
  const pathname = usePathname();

  const dismiss = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    remaining.current = 0;
    setNotice(null);
  }, []);

  // 남은 시간. 손을 올리거나 포커스하면 멈추고 떼면 이어 간다(WCAG 2.2.1)
  const start = useCallback((ms: number) => {
    if (timer.current) clearTimeout(timer.current);
    remaining.current = ms;
    startedAt.current = Date.now();
    timer.current = setTimeout(() => {
      timer.current = null;
      setNotice(null);
    }, ms);
  }, []);
  const pause = useCallback(() => {
    if (!timer.current) return;
    clearTimeout(timer.current);
    timer.current = null;
    remaining.current = Math.max(0, remaining.current - (Date.now() - startedAt.current));
  }, []);
  const resume = useCallback(() => {
    if (timer.current || remaining.current <= 0) return;
    start(Math.max(remaining.current, 1500));
  }, [start]);

  // 한 번에 하나만 보이고 새 것이 옛 것을 바꾼다
  const show = useCallback(
    (next: Omit<Notice, "id">, ms: number) => {
      seq.current += 1;
      setNotice({ ...next, id: seq.current });
      start(ms);
    },
    [start],
  );

  // 다른 화면으로 가면 닫는다. 되돌리기가 떠난 화면의 상태를 건드리지 않게 한다.
  // 이동 직전에 띄운 완료 알림(keepOnNavigate)은 다음 화면에서도 보여야 하므로 남긴다
  const keep = useRef(false);
  useEffect(() => {
    keep.current = Boolean(notice?.keepOnNavigate);
  }, [notice]);
  useEffect(
    () => () => {
      if (!keep.current) dismiss();
    },
    [pathname, dismiss],
  );

  const value = useMemo<Feedback>(
    () => ({
      toast: (message, opts) => show({ message, keepOnNavigate: opts?.keepOnNavigate }, opts?.durationMs ?? TOAST_MS),
      snackbar: ({ message, actionLabel, onAction, durationMs = SNACKBAR_MS }) =>
        show(
          {
            message,
            action: {
              label: actionLabel,
              onClick: () => {
                dismiss();
                onAction();
              },
            },
          },
          durationMs,
        ),
      dismiss,
    }),
    [dismiss, show],
  );

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 z-50 flex justify-center px-4 bottom-[calc(100px+env(safe-area-inset-bottom,0px))]"
      >
        {notice && (
          <div
            key={notice.id}
            onPointerEnter={pause}
            onPointerLeave={resume}
            onFocus={pause}
            onBlur={resume}
            className="pointer-events-auto flex min-h-12 max-w-[420px] items-center gap-3 rounded-[14px] bg-ink px-4 py-2.5 text-[14px] font-medium tracking-[-0.14px] text-white shadow-card animate-[feedback-in_var(--dur-base)_var(--ease-out)]"
          >
            <span className="min-w-0 flex-1 [word-break:keep-all]">{notice.message}</span>
            {notice.action && (
              <button
                type="button"
                onClick={notice.action.onClick}
                className={`min-h-11 shrink-0 px-1 text-[14px] font-bold text-brand-300 ${focusRing}`}
              >
                {notice.action.label}
              </button>
            )}
          </div>
        )}
      </div>
    </FeedbackContext.Provider>
  );
}

export function useFeedback() {
  return useContext(FeedbackContext);
}

/** 되돌릴 수 없는 일을 하기 전 확인. 네이티브 dialog 라 포커스 가두기와 Esc 가 기본으로 된다. */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = "취소",
  tone = "primary",
  loading = false,
  error,
  onConfirm,
  onCancel,
}: {
  /** 확인한 일이 실패했을 때 창 안에 보일 이유(창이 떠 있으면 뒤 화면은 가려진다) */
  error?: string | null;
  open: boolean;
  title: string;
  description?: string;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "primary" | "danger";
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={`${id}-title`}
      aria-describedby={description ? `${id}-description` : undefined}
      onCancel={(event) => {
        event.preventDefault();
        if (!loading) onCancel();
      }}
      // 사용자 동작 없는 두 번째 Esc 는 크롬이 cancel 없이 바로 닫는다. 그때도 open 값을 맞춘다
      onClose={() => {
        // close 이벤트는 비동기로 늦게 온다. 앞 창을 닫은 이벤트가 같은 창을 다시 연 뒤에 도착하면
        // 지금 열린 창을 취소로 닫아 버린다(2026-11-11 CI: 연달아 삭제의 두 번째 확인 창이 사라짐). 실제로 닫혀 있을 때만 취소로 본다
        if (open && !ref.current?.open) onCancel();
      }}
      onClick={(event) => {
        // 바깥(덮개)을 누르면 취소
        if (event.target === event.currentTarget && !loading) onCancel();
      }}
      className="m-auto w-[min(340px,calc(100vw-32px))] rounded-[20px] bg-surface p-0 text-ink shadow-card backdrop:bg-black/40"
    >
      <div className="flex flex-col gap-2 p-5">
        <h2 id={`${id}-title`} className="text-[18px] font-bold leading-[1.4] tracking-[-0.36px] [word-break:keep-all]">{title}</h2>
        {description && <p id={`${id}-description`} className="text-[14px] leading-[1.5] text-ink-muted [word-break:keep-all]">{description}</p>}
        {error && (
          <p role="alert" className="text-[13px] font-semibold text-danger-700 [word-break:keep-all]">
            {error}
          </p>
        )}
        <div className="mt-3 flex gap-2">
          <Button variant="secondary" className="flex-1 py-3.5" disabled={loading} onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button variant={tone === "danger" ? "danger" : "primary"} className="flex-1 py-3.5" loading={loading} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  );
}

const bannerTone = {
  info: "bg-empty text-primary",
  warn: "bg-warn-50 text-warn-700",
  danger: "bg-danger-50 text-danger-700",
} as const;

/** 화면 전체에 걸린 상태(일부 실패, 알림 꺼짐 등). */
export function Banner({
  tone = "info",
  children,
  action,
  onDismiss,
  dismissLabel,
}: {
  tone?: "info" | "warn" | "danger";
  children: ReactNode;
  action?: { label: string; onClick: () => void };
  onDismiss?: () => void;
  /** 있으면 × 대신 이 글자로 닫는다(예: 알림 권유의 '나중에') */
  dismissLabel?: string;
}) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={`flex items-center gap-3 rounded-[16px] px-4 py-3 text-[14px] font-medium leading-[1.45] tracking-[-0.14px] ${bannerTone[tone]}`}
    >
      <div className="min-w-0 flex-1 [word-break:keep-all]">{children}</div>
      {action && (
        <button type="button" onClick={action.onClick} className={`min-h-11 shrink-0 rounded-full bg-surface px-3.5 font-bold ${focusRing}`}>
          {action.label}
        </button>
      )}
      {onDismiss && dismissLabel && (
        <button type="button" onClick={onDismiss} className={`min-h-11 shrink-0 px-1 text-[13px] font-medium opacity-80 ${focusRing}`}>
          {dismissLabel}
        </button>
      )}
      {onDismiss && !dismissLabel && (
        <button type="button" aria-label="닫기" onClick={onDismiss} className={`flex size-11 shrink-0 items-center justify-center text-[18px] ${focusRing}`}>
          ×
        </button>
      )}
    </div>
  );
}

/** 중간점 대신 쓰는 숫자 알약. 예) 확인해 주세요 <CountBadge n={2} /> */
export function CountBadge({ n, tone = "neutral" }: { n: number; tone?: "neutral" | "danger" }) {
  return (
    <span
      className={`ml-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 align-[2px] text-[12px] font-bold leading-none ${
        tone === "danger" ? "bg-danger-500 text-white" : "bg-empty text-primary"
      }`}
    >
      {n > 99 ? "99+" : n}
    </span>
  );
}
