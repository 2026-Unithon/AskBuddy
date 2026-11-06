"use client";

import type { IntakeHint } from "@/lib/api";

export const INTAKE_HINT_LABELS: Record<IntakeHint, string> = {
  RECIPE: "레시피",
  PROCEDURE: "업무 순서",
  POLICY: "매장 규칙",
  REFERENCE: "매장 정보",
  NOTICE: "공지",
};

const ORDER: IntakeHint[] = ["RECIPE", "PROCEDURE", "POLICY", "REFERENCE", "NOTICE"];

/**
 * 점주가 자료 종류를 고르는 칩. 선택 사항이라 아무것도 안 골라도 제출된다.
 * 상태는 부모(화면 입력)가 들고 있고, 이 컴포넌트는 서버 상태를 모른다.
 */
export function IntakeHintChips({
  value,
  onChange,
  disabled = false,
}: {
  value: IntakeHint[];
  onChange: (next: IntakeHint[]) => void;
  disabled?: boolean;
}) {
  const toggle = (hint: IntakeHint) =>
    onChange(value.includes(hint) ? value.filter((h) => h !== hint) : [...value, hint]);

  return (
    <div className="flex flex-col gap-1.5" role="group" aria-label="자료 종류">
      <p className="text-[12px] font-medium text-ink-muted">이건 어떤 자료인가요? (선택, 여러 개 가능)</p>
      <div className="flex flex-wrap gap-1.5">
        {ORDER.map((hint) => {
          const on = value.includes(hint);
          return (
            <button
              key={hint}
              type="button"
              aria-pressed={on}
              disabled={disabled}
              onClick={() => toggle(hint)}
              className={`min-h-11 rounded-full border px-4 text-[13px] font-medium disabled:opacity-50 ${on ? "border-primary bg-primary text-white" : "border-transparent bg-empty text-ink"}`}
            >
              {INTAKE_HINT_LABELS[hint]}
            </button>
          );
        })}
      </div>
    </div>
  );
}
