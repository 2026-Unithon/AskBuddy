"use client";

import { focusRing } from "@/components/kit/buttons";
import { CountBadge } from "@/components/kit/feedback";

/**
 * 얇은 세그먼트(o09a). 한 덩어리 알약 안에서 하나만 고른다.
 * 탭 패널을 따로 두지 않는 보기 바꾸기라 탭이 아니라 누름 버튼 묶음이다. 숫자는 이름과 함께 읽힌다("답변 대기 2").
 */
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
    <div role="group" aria-label={label} className="flex h-10 w-full rounded-full bg-empty p-1">
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            aria-label={option.badge ? `${option.label} ${option.badge}` : undefined}
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
