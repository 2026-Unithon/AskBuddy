import Link from "next/link";
import { focusRing } from "@/components/kit/buttons";
import { Icon } from "@/components/kit/icon";

/** Figma A2 Row: 24px 둥근 네모 + 16 본문. 행 전체가 눌린다. saving 중엔 다시 누를 수 없다. */
export function CheckRow({
  label,
  checked,
  onToggle,
  saving = false,
  error,
  href,
}: {
  label: string;
  checked: boolean;
  onToggle: () => void;
  saving?: boolean;
  error?: string;
  /** 있으면 체크박스는 체크만 하고, 제목은 이 주소로 가는 링크가 된다. */
  href?: string;
}) {
  if (href)
    return (
      <li>
        <div className="flex min-h-[52px] w-full items-center gap-1.5">
          <button
            type="button"
            role="checkbox"
            aria-checked={checked}
            aria-busy={saving || undefined}
            aria-label={label}
            disabled={saving}
            onClick={onToggle}
            className={`flex size-11 shrink-0 items-center justify-center rounded-[7px] ${focusRing}`}
          >
            <span
              aria-hidden
              className={`flex size-6 items-center justify-center rounded-[7px] border-2 ${
                checked ? "border-primary bg-primary text-white" : "border-primary-weak"
              } ${saving ? "animate-pulse" : ""}`}
            >
              {checked && <Icon name="check" size={14} />}
            </span>
          </button>
          <Link
            href={href}
            className={`flex min-h-11 min-w-0 flex-1 items-center py-2 text-[16px] leading-[1.45] tracking-[-0.16px] [word-break:keep-all] ${focusRing} ${
              checked ? "text-ink-muted line-through" : "text-ink"
            }`}
          >
            {label}
          </Link>
        </div>
        {error && <p className="pb-2 pl-[50px] text-[12px] text-danger-700">{error}</p>}
      </li>
    );
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
