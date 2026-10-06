import { focusRing } from "@/components/kit/buttons";
import { Icon } from "@/components/kit/icon";

/** Figma A2 Row: 24px 둥근 네모 + 16 본문. 행 전체가 눌린다. saving 중엔 다시 누를 수 없다. */
export function CheckRow({
  label,
  checked,
  onToggle,
  saving = false,
  error,
}: {
  label: string;
  checked: boolean;
  onToggle: () => void;
  saving?: boolean;
  error?: string;
}) {
  return (
    <li>
      <button
        type="button"
        role="checkbox"
        aria-checked={checked}
        aria-busy={saving || undefined}
        disabled={saving}
        onClick={onToggle}
        className={`flex min-h-[52px] w-full items-center gap-3.5 py-3.5 text-left ${focusRing}`}
      >
        <span
          aria-hidden
          className={`flex size-6 shrink-0 items-center justify-center rounded-[7px] border-2 ${
            checked ? "border-primary bg-primary text-white" : "border-primary-weak"
          } ${saving ? "animate-pulse" : ""}`}
        >
          {checked && <Icon name="check" size={14} />}
        </span>
        <span
          className={`min-w-0 flex-1 text-[16px] leading-[1.45] tracking-[-0.16px] [word-break:keep-all] ${
            checked ? "text-ink-muted line-through" : "text-ink"
          }`}
        >
          {label}
        </span>
      </button>
      {error && <p className="pb-2 pl-[38px] text-[12px] text-danger-700">{error}</p>}
    </li>
  );
}
