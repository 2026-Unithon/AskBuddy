"use client";

// 사실 한 줄의 칸 편집기(추가 시트의 제안 카드가 쓴다). 규격은 읽기 전용.
import { useId } from "react";
import { Caption, Switch, focusRing } from "@/components/kit";
import type { FactFields } from "@/lib/api";
import { variantLabel } from "./fact-row";

const inputClass = `min-h-12 w-full rounded-[16px] bg-surface px-4 text-[16px] text-ink shadow-card disabled:opacity-60 ${focusRing}`;

function ListEditor({
  label,
  items,
  onChange,
  disabled,
}: {
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="pb-1.5 text-[13px] font-medium text-ink-muted">{label}</legend>
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            aria-label={`${label} ${i + 1}`}
            value={item}
            maxLength={200}
            disabled={disabled}
            onChange={(event) => onChange(items.map((v, j) => (j === i ? event.target.value : v)))}
            className={inputClass}
          />
          <button
            type="button"
            aria-label={`${label} ${i + 1} 지우기`}
            disabled={disabled}
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            className={`min-h-11 shrink-0 rounded-full bg-background px-3 text-[13px] font-bold text-ink-muted ${focusRing}`}
          >
            지우기
          </button>
        </div>
      ))}
      {items.length < 10 && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChange([...items, ""])}
          className={`min-h-11 self-start text-[13px] font-bold text-primary ${focusRing}`}
        >
          {label} 더하기
        </button>
      )}
    </fieldset>
  );
}

/** 사실 한 줄의 칸 편집기. 고치기 시트와 추가 시트의 제안 카드가 같이 쓴다. */
export function FactFieldsEditor({
  fields,
  onChange,
  showValue,
  disabled,
}: {
  fields: FactFields;
  onChange: (fields: FactFields) => void;
  showValue: boolean;
  disabled?: boolean;
}) {
  const id = useId();
  const set = (patch: Partial<FactFields>) => onChange({ ...fields, ...patch });
  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1.5" htmlFor={`${id}-sentence`}>
        <span className="text-[13px] font-medium text-ink-muted">문장</span>
        <textarea
          id={`${id}-sentence`}
          value={fields.sentence}
          maxLength={2000}
          rows={3}
          disabled={disabled}
          onChange={(event) => set({ sentence: event.target.value })}
          className={`rounded-[16px] bg-surface p-4 text-[16px] leading-[1.6] text-ink shadow-card disabled:opacity-60 ${focusRing}`}
        />
      </label>
      <Switch
        label="하지 않는 일이에요"
        checked={fields.polarity === "NEGATE"}
        disabled={disabled}
        onChange={(negate) => set({ polarity: negate ? "NEGATE" : "AFFIRM" })}
      />
      {showValue && (
        <div className="flex gap-2">
          <label className="flex min-w-0 flex-[2] flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink-muted">값</span>
            <input value={fields.value ?? ""} maxLength={500} disabled={disabled} onChange={(event) => set({ value: event.target.value })} className={inputClass} />
          </label>
          <label className="flex min-w-0 flex-1 flex-col gap-1.5">
            <span className="text-[13px] font-medium text-ink-muted">단위</span>
            <input value={fields.unit ?? ""} maxLength={20} disabled={disabled} onChange={(event) => set({ unit: event.target.value })} className={inputClass} />
          </label>
        </div>
      )}
      <ListEditor label="조건" items={fields.conditions} disabled={disabled} onChange={(conditions) => set({ conditions })} />
      <ListEditor label="예외" items={fields.exceptions} disabled={disabled} onChange={(exceptions) => set({ exceptions })} />
      <Caption>규격 {variantLabel(fields.variant)} (바꿀 수 없어요)</Caption>
    </div>
  );
}
