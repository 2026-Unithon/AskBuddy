"use client";

import { focusRing } from "@/components/kit/buttons";

/** 켜고 끄는 스위치. 한 줄 전체가 누르는 자리이고, 손잡이는 상태가 바뀔 때만 스프링으로 움직인다. */
export function Switch({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (next: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`flex min-h-12 w-full items-center justify-between gap-3 text-left text-[16px] text-ink disabled:opacity-50 ${focusRing}`}
    >
      <span className="min-w-0 flex-1 [word-break:keep-all]">{label}</span>
      <span aria-hidden className={`relative h-8 w-[52px] shrink-0 rounded-full transition-colors duration-150 ${checked ? "bg-primary" : "bg-empty"}`}>
        <span
          className="absolute left-1 top-1 size-6 rounded-full bg-white shadow-card transition-transform duration-[var(--dur-base)] ease-[var(--ease-spring)]"
          style={{ transform: checked ? "translateX(20px)" : "translateX(0)" }}
        />
      </span>
    </button>
  );
}
