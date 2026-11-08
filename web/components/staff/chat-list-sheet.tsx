"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ErrorInline, Sheet, Skeleton, focusRing } from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { rSessionSearchQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

const SEARCH_DELAY_MS = 250;

function when(iso: string | null | undefined) {
  if (!iso) return "";
  const at = new Date(iso);
  return at.toLocaleDateString("ko-KR", { month: "numeric", day: "numeric" });
}

/**
 * 지난 대화 목록(계획 7 Task 8). 버디 화면 머리의 '지난 대화'로 연다.
 * '새 대화'는 눈에 띄지 않게 목록 맨 위 작은 글자로만 둔다(2026-11-08 사용자).
 */
export function ChatListSheet({ open, onClose, current }: { open: boolean; onClose: () => void; current: string | null }) {
  const { state } = useApp();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search]);
  const list = useQuery(rSessionSearchQuery(state.token, state.storeId, state.userId, query, open));
  const sessions = list.data?.sessions ?? [];
  return (
    <Sheet open={open} onClose={onClose} title="지난 대화">
      <div className="flex items-center gap-3">
        <input
          type="search"
          aria-label="지난 대화 찾기"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="물어본 말로 찾기"
          className={`min-h-11 min-w-0 flex-1 rounded-full bg-surface px-4 text-[15px] text-ink shadow-card outline-none ${focusRing}`}
        />
        <Link href="/staff/ask?new=1" onClick={onClose} className={`shrink-0 text-[13px] font-bold text-primary ${focusRing}`}>
          새 대화
        </Link>
      </div>
      {list.isLoading && <Skeleton className="h-32" />}
      {list.error && <ErrorInline message={apiErrorMessage(list.error, "지난 대화를 불러오지 못했어요.")} onRetry={() => void list.refetch()} />}
      {list.data && sessions.length === 0 && <p className="py-6 text-center text-[14px] text-ink-muted">{query ? "찾는 대화가 없어요" : "아직 대화가 없어요"}</p>}
      <ul className="flex max-h-[55dvh] flex-col overflow-y-auto">
        {sessions.map((session) => (
          <li key={session.session_id}>
            <Link
              href={`/staff/ask?session_id=${encodeURIComponent(session.session_id)}`}
              onClick={onClose}
              aria-current={session.session_id === current ? "page" : undefined}
              className={`flex min-h-12 items-center gap-3 rounded-[12px] px-2 py-2.5 ${session.session_id === current ? "bg-empty" : ""} ${focusRing}`}
            >
              <span className="min-w-0 flex-1 truncate text-[15px] text-ink">{session.title || "제목 없는 대화"}</span>
              <span className="shrink-0 text-[12px] text-ink-muted">{when(session.last_at)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}
