"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { focusRing, pressable } from "@/components/kit/buttons";
import { Icon } from "@/components/kit/icon";
import { notificationsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

const circle = `relative flex size-11 items-center justify-center rounded-full bg-surface text-primary shadow-card ${pressable} ${focusRing}`;

/** 화면 오른쪽 위: 알림 종(읽지 않은 수) + 마이페이지 사람 아이콘(NAV-5·8·10, 계획 8). 두 역할 모두 같은 /notifications 를 본다. */
export function HeaderActions({ role }: { role: "OWNER" | "STAFF" }) {
  const { state } = useApp();
  const notifications = useQuery(notificationsQuery(state.token, state.storeId));
  const unread = notifications.data?.unread_count ?? 0;
  const base = role === "OWNER" ? "/owner" : "/staff";
  return (
    <div className="flex items-center gap-2">
      <Link
        href={role === "OWNER" ? "/owner/notifications" : "/staff/notifications/v2"}
        aria-label={unread > 0 ? `알림 ${unread}개 읽지 않음` : "알림"}
        className={circle}
      >
        <Icon name="bell" size={20} />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-danger-500 px-1 text-[11px] font-bold leading-none text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </Link>
      <Link href={`${base}/settings`} aria-label="마이페이지" className={circle}>
        <Icon name="user" size={20} />
      </Link>
    </div>
  );
}
