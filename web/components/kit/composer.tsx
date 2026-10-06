"use client";

import type { ReactNode } from "react";
import { focusRing } from "@/components/kit/buttons";
import { Icon, type IconName } from "@/components/kit/icon";

/** Composer 안의 말하기·찍기·파일 알약 버튼. */
export function ComposerTool({
  icon,
  label,
  onClick,
  active = false,
  disabled,
}: {
  icon: IconName;
  label: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active || undefined}
      className={`inline-flex min-h-8 items-center gap-[5px] rounded-full px-2.5 py-1.5 text-[12px] font-medium leading-[1.45] tracking-[-0.12px] disabled:opacity-50 ${
        active ? "bg-primary text-white" : "bg-background text-ink-muted"
      } ${focusRing}`}
    >
      <Icon name={icon} size={14} />
      {label}
    </button>
  );
}

/**
 * Figma Composer (O3·O6·O7): 여러 줄 입력 + 아래 도구 줄 + 오른쪽 "넣기".
 * 도구(tools)와 첨부 목록(attachments)은 화면이 채운다 — 업로드·녹음 수명은 화면 밖 hook 이 가진다.
 */
export function Composer({
  value,
  onChange,
  onSubmit,
  placeholder,
  submitLabel = "넣기",
  canSubmit,
  submitting = false,
  tools,
  attachments,
  disabled,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
  submitLabel?: string;
  canSubmit?: boolean;
  submitting?: boolean;
  tools?: ReactNode;
  attachments?: ReactNode;
  disabled?: boolean;
  label: string;
}) {
  const ready = (canSubmit ?? value.trim().length > 0) && !submitting && !disabled;
  return (
    <form
      className="flex w-full flex-col gap-3.5 rounded-[22px] bg-surface pb-3 pl-[18px] pr-3.5 pt-4 shadow-card"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) onSubmit();
      }}
    >
      <textarea
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        rows={2}
        className="max-h-40 min-h-[52px] w-full resize-none bg-transparent text-[15px] leading-[1.45] tracking-[-0.15px] text-ink outline-none placeholder:text-ink-muted [field-sizing:content]"
      />
      {attachments}
      <div className="flex items-center gap-2.5">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{tools}</div>
        <button
          type="submit"
          disabled={!ready}
          aria-busy={submitting || undefined}
          className={`inline-flex min-h-10 shrink-0 items-center gap-1 rounded-[14px] bg-primary px-3 py-2 text-[13px] font-bold leading-[1.45] tracking-[-0.13px] text-white shadow-primary disabled:opacity-40 ${focusRing}`}
        >
          {submitting ? (
            <span aria-hidden className="size-[15px] animate-spin rounded-full border-2 border-current border-r-transparent" />
          ) : null}
          {submitLabel}
          {!submitting && <Icon name="up" size={15} />}
        </button>
      </div>
    </form>
  );
}

/** Figma AskBar (A2·A5): 한 줄 질문 입력. 비어 있으면 말하기, 글이 있으면 보내기 버튼. */
export function AskBar({
  value,
  onChange,
  onSubmit,
  onVoice,
  placeholder = "모르는 거 물어보기",
  submitting = false,
  voiceActive = false,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onVoice?: () => void;
  placeholder?: string;
  submitting?: boolean;
  voiceActive?: boolean;
  disabled?: boolean;
}) {
  const hasText = value.trim().length > 0;
  const showVoice = !hasText && onVoice;
  return (
    <form
      className="flex h-14 w-full items-center gap-2 rounded-[28px] bg-surface py-2 pl-[18px] pr-2 shadow-card"
      onSubmit={(event) => {
        event.preventDefault();
        if (hasText && !submitting && !disabled) onSubmit();
      }}
    >
      <input
        aria-label={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        enterKeyHint="send"
        className="min-w-0 flex-1 bg-transparent text-[15px] leading-[1.45] tracking-[-0.15px] text-ink outline-none placeholder:text-ink-muted"
      />
      {showVoice ? (
        <button
          type="button"
          onClick={onVoice}
          disabled={disabled}
          aria-label={voiceActive ? "녹음 멈추기" : "말로 물어보기"}
          aria-pressed={voiceActive || undefined}
          className={`flex h-10 min-w-11 items-center justify-center rounded-[16px] px-3 text-white shadow-primary disabled:opacity-40 ${
            voiceActive ? "bg-danger-600" : "bg-primary"
          } ${focusRing}`}
        >
          <Icon name="mic" size={18} />
        </button>
      ) : (
        <button
          type="submit"
          disabled={!hasText || submitting || disabled}
          aria-label="보내기"
          aria-busy={submitting || undefined}
          className={`flex h-10 min-w-11 items-center justify-center rounded-[16px] bg-primary px-3 text-white shadow-primary disabled:opacity-40 ${focusRing}`}
        >
          {submitting ? (
            <span aria-hidden className="size-[18px] animate-spin rounded-full border-2 border-current border-r-transparent" />
          ) : (
            <Icon name="up" size={18} />
          )}
        </button>
      )}
    </form>
  );
}
