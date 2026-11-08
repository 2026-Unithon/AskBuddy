"use client";

import { focusRing } from "@/components/kit/buttons";
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
  label,
}: {
  value: IntakeHint[];
  onChange: (next: IntakeHint[]) => void;
  disabled?: boolean;
  /** 칩 위에 보이는 이름. 답 첨부처럼 '다음에 붙일 파일'에만 쓰이는 칩이면 그렇게 말한다 */
  label?: string;
}) {
  const toggle = (hint: IntakeHint) =>
    onChange(value.includes(hint) ? value.filter((h) => h !== hint) : [...value, hint]);

  return (
    <div className="flex flex-col gap-1.5" role="group" aria-label={label ?? "자료 종류"}>
      <p className="text-[12px] font-medium text-ink-muted">{label ?? "이건 어떤 자료인가요? (선택, 여러 개 가능)"}</p>
      {/* 한 줄로 두고 넘치면 옆으로 민다. 칩은 작게, 누르는 자리는 위아래 6px 넓혀 44px 를 지킨다 */}
      <div className="-mx-1 flex shrink-0 flex-nowrap gap-1.5 overflow-x-auto px-1 py-1.5">
        {ORDER.map((hint) => {
          const on = value.includes(hint);
          return (
            <button
              key={hint}
              type="button"
              aria-pressed={on}
              disabled={disabled}
              onClick={() => toggle(hint)}
              className={`relative h-8 shrink-0 rounded-[8px] px-3 text-[12px] font-medium transition-colors duration-150 before:absolute before:inset-x-0 before:-inset-y-1.5 disabled:opacity-50 ${focusRing} ${on ? "bg-primary text-white" : "bg-empty text-ink"}`}
            >
              {INTAKE_HINT_LABELS[hint]}
            </button>
          );
        })}
      </div>
    </div>
  );
}
