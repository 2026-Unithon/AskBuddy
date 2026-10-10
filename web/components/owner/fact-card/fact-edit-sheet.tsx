"use client";

// 고치기 시트: 사실 한 줄의 문장·조건·예외·부정·값·단위. 규격은 읽기 전용.
// "문장으로 다시 분석" 은 서버 분석(상태 없음)으로 칸만 채운다. 저장은 하단 "고친 내용 저장" 에서.
import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Button, Caption, ErrorInline, Sheet, focusRing } from "@/components/kit";
import { parseCardFacts, type FactFields, type FactParseResponse } from "@/lib/api";
import { useApp } from "@/lib/store";
import { NO_FACT_TEXT, VALUE_CLEAR_TEXT, parseErrorMessage, warningText } from "./fact-messages";
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
      <button
        type="button"
        aria-pressed={fields.polarity === "NEGATE"}
        disabled={disabled}
        onClick={() => set({ polarity: fields.polarity === "NEGATE" ? "AFFIRM" : "NEGATE" })}
        className={`flex min-h-11 items-center gap-2 self-start rounded-full px-3.5 text-[13px] font-bold ${
          fields.polarity === "NEGATE" ? "bg-danger-50 text-danger-700" : "bg-background text-ink-muted"
        } ${focusRing}`}
      >
        {fields.polarity === "NEGATE" ? "하지 않음 · 켜짐" : "하지 않음 · 꺼짐"}
      </button>
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
      <Caption>규격 · {variantLabel(fields.variant)} (바꿀 수 없어요)</Caption>
    </div>
  );
}

export function FactEditSheet({
  cardId,
  baseRevisionId,
  initial,
  hadValue,
  onApply,
  onClose,
}: {
  cardId: number;
  /** 카드에 고정된 판. 새로 넣은 줄이면 null(다시 분석 없음) */
  baseRevisionId: number | null;
  initial: FactFields;
  /** 원래 값이 있던 줄만 값·단위를 고친다. 값 지우기는 서버가 거절한다 */
  hadValue: boolean;
  onApply: (fields: FactFields) => void;
  onClose: () => void;
}) {
  const { state } = useApp();
  const [form, setForm] = useState<FactFields>(initial);
  const [notices, setNotices] = useState<string[]>([]);
  const parse = useMutation({
    mutationFn: (text: string) =>
      parseCardFacts(cardId, { text, mode: "MODIFY", base_fact_revision_id: baseRevisionId }, state.token!),
    onSuccess: (result: FactParseResponse) => {
      const first = result.proposals[0];
      if (!first) {
        setNotices([NO_FACT_TEXT]);
        return;
      }
      if (first.warnings.includes("STEP_CHANGED")) {
        setNotices([warningText("STEP_CHANGED")]);
        return;
      }
      // 규격·속성·단계 번호는 이 줄 값 그대로. 원래 값이 없던 줄은 값을 붙이지 않는다
      setForm((prev) => ({
        ...prev,
        sentence: first.fact.sentence,
        polarity: first.fact.polarity,
        value: hadValue ? first.fact.value : prev.value,
        unit: hadValue ? first.fact.unit : prev.unit,
        conditions: first.fact.conditions,
        exceptions: first.fact.exceptions,
      }));
      setNotices([...result.warnings, ...first.warnings].filter((w) => w !== "MULTIPLE_FACTS").map((w) => warningText(w)));
    },
  });
  const valueMissing = hadValue && !(form.value ?? "").trim();
  const sentenceMissing = !form.sentence.trim();

  return (
    <Sheet open onClose={onClose} title="이 사실 고치기" description="문장이 기준이에요. 숫자를 바꾸면 문장 속 숫자도 같이 고쳐 주세요.">
      <FactFieldsEditor fields={form} onChange={setForm} showValue={hadValue} disabled={parse.isPending} />
      {valueMissing && <Caption className="text-danger-700">{VALUE_CLEAR_TEXT}</Caption>}
      {baseRevisionId !== null && (
        <Button variant="secondary" loading={parse.isPending} disabled={sentenceMissing} onClick={() => parse.mutate(form.sentence)}>
          {parse.isPending ? "분석하는 중" : "문장으로 다시 분석"}
        </Button>
      )}
      {parse.error && <ErrorInline message={parseErrorMessage(parse.error)} onRetry={() => parse.mutate(form.sentence)} retrying={parse.isPending} />}
      {notices.length > 0 && (
        <ul className="flex flex-col gap-1" data-testid="parse-notices">
          {notices.map((text, i) => (
            <li key={i} className="rounded-[14px] bg-warn-50 px-3.5 py-2.5 text-[13px] leading-[1.45] text-warn-700 [word-break:keep-all]">
              {text}
            </li>
          ))}
        </ul>
      )}
      <Button disabled={parse.isPending || valueMissing || sentenceMissing} onClick={() => onApply(form)}>
        이대로 고치기
      </Button>
      <Button variant="secondary" onClick={onClose}>
        그만두기
      </Button>
    </Sheet>
  );
}
