"use client";

import { focusRing } from "@/components/kit/buttons";
import { CountBadge } from "@/components/kit/feedback";

/** 얇은 세그먼트(o09a). 한 덩어리 알약 안에서 하나만 고른다. */
export function Segmented({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string; badge?: number }[];
  onChange: (value: string) => void;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex h-10 w-full rounded-full bg-empty p-1">
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(option.value)}
            className={`flex flex-1 items-center justify-center rounded-full text-[14px] font-bold transition-colors duration-150 ${
              selected ? "bg-surface text-ink shadow-card" : "text-ink-muted"
            } ${focusRing}`}
          >
            {option.label}
            {option.badge ? <CountBadge n={option.badge} /> : null}
          </button>
        );
      })}
    </div>
  );
}
