"use client";

import Link from "next/link";
import { useId, type ReactNode } from "react";
import { focusRing, pressable } from "@/components/kit/buttons";
import { Icon } from "@/components/kit/icon";

/**
 * 설정 화면 구역(계획 8). 카드 목록 구역과 같은 모양: 굵은 제목 + 굵은 밑줄, 아래 줄.
 * tone="danger" 는 제목 없이 위험 색 테두리 상자(퇴사, 탈퇴).
 */
export function SettingsSection({ title, tone, children }: { title?: string; tone?: "danger"; children: ReactNode }) {
  const id = useId();
  if (tone === "danger") {
    return (
      <section data-danger-zone="" aria-label="계정 삭제" className="rounded-[20px] border-2 border-danger-500 px-[18px] py-1">
        <ul className="flex flex-col divide-y divide-empty">{children}</ul>
      </section>
    );
  }
  return (
    <section aria-labelledby={id} className="flex flex-col">
      <h2 id={id} className="border-b-2 border-ink pb-1.5 text-[17px] font-bold leading-[1.4] tracking-[-0.34px] text-ink">
        {title}
      </h2>
      <ul className="flex flex-col divide-y divide-empty">{children}</ul>
    </section>
  );
}

/** 설정 한 줄. 링크, 버튼, 값만 보이는 줄. 오른쪽은 값 글자 또는 화살표. */
export function SettingsLink({
  title,
  href,
  onClick,
  value,
  danger = false,
  disabled = false,
}: {
  title: string;
  href?: string;
  onClick?: () => void;
  value?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
}) {
  const rowClass = `flex min-h-14 w-full items-center gap-2 py-3 text-left ${focusRing}`;
  const body = (
    <>
      <span className={`min-w-0 flex-1 text-[16px] font-bold tracking-[-0.16px] [word-break:keep-all] ${danger ? "text-danger-700" : "text-ink"}`}>{title}</span>
      {value !== undefined ? (
        <span className="shrink-0 text-[15px] text-ink-muted">{value}</span>
      ) : (href || onClick) && !danger ? (
        <Icon name="right" size={18} className="text-ink-muted" />
      ) : null}
    </>
  );
  return (
    <li>
      {href ? (
        <Link href={href} className={`${rowClass} ${pressable}`}>
          {body}
        </Link>
      ) : onClick ? (
        <button type="button" onClick={onClick} disabled={disabled} className={`${rowClass} ${pressable} disabled:opacity-50`}>
          {body}
        </button>
      ) : (
        <div className={rowClass}>{body}</div>
      )}
    </li>
  );
}
