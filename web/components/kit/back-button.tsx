"use client";

import Link from "next/link";
import { focusRing, pressable } from "@/components/kit/buttons";
import { Icon } from "@/components/kit/icon";
import { useBack } from "@/lib/nav-history";

/**
 * Figma BackBtn. 앱 안에서 이동해 왔으면 왔던 곳으로, 링크로 바로 열렸으면 parent 로 간다.
 * href 는 parent 라서 새로고침·새 탭(보조 키 클릭)에서도 같은 곳이 열린다.
 */
export function BackButton({ parent, label = "뒤로" }: { parent: string; label?: string }) {
  const back = useBack(parent);
  return (
    <Link
      href={parent}
      data-back=""
      onNavigate={(event) => {
        event.preventDefault();
        back();
      }}
      className={`inline-flex min-h-11 items-center gap-0.5 self-start rounded-full bg-surface py-2 pl-2 pr-3.5 text-[14px] font-medium tracking-[-0.14px] text-ink shadow-card ${pressable} ${focusRing}`}
    >
      <Icon name="left" size={16} />
      {label}
    </Link>
  );
}
