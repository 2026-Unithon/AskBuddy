"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  BackButton,
  Chip,
  ConfirmDialog,
  CountBadge,
  ErrorInline,
  ListGroup,
  ListRow,
  PageHeader,
  Screen,
  Skeleton,
  Surface,
  TextButton,
} from "@/components/kit";
import { apiErrorMessage, logoutSession } from "@/lib/api";
import { bootstrapQuery, membersQuery, notificationsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

type Row = { title: string; href: string; badge?: number };

/** 설정(o12a, s07a). 위는 프로필, 아래는 관리 항목. 기능이 없는 항목(언어 등)은 넣지 않는다. */
export function SettingsScreen({ role }: { role: "OWNER" | "STAFF" }) {
  const { state } = useApp();
  const owner = role === "OWNER";
  const bootstrap = useQuery(bootstrapQuery(state.token, state.userId, state.storeId));
  // 뱃지: 합류 요청 수(사장님만), 읽지 않은 알림 수. 못 불러와도 줄은 그대로 보인다
  const members = useQuery({ ...membersQuery(state.token, state.storeId), enabled: owner && Boolean(state.token && state.storeId) });
  const notifications = useQuery(notificationsQuery(state.token, state.storeId));
  const unread = notifications.data?.unread_count ?? 0;
  const user = bootstrap.data?.user;
  const store = bootstrap.data?.store;
  const [confirming, setConfirming] = useState(false);

  const rows: Row[] = owner
    ? [
        { title: "근무조", href: "/owner/shifts" },
        { title: "직원 관리", href: "/owner/members", badge: members.data?.pending.length },
        { title: "알바생 기록", href: "/owner/me" },
        { title: "카테고리", href: "/owner/categories" },
        { title: "알림", href: "/owner/notifications", badge: unread },
      ]
    : [
        { title: "내 기록", href: "/staff/me" },
        { title: "답변 알림", href: "/staff/notifications/v2", badge: unread },
      ];

  // 서버의 세션을 먼저 폐기한다. 실패하면 설정 화면에서 재시도한다.
  const logout = useMutation({
    mutationFn: logoutSession,
    onSuccess: () => window.location.replace("/"),
  });

  return (
    <Screen>
      <BackButton parent={owner ? "/owner" : "/staff"} />
      <PageHeader title="설정" />
      {bootstrap.isLoading && <Skeleton className="h-60" />}
      {bootstrap.error && (
        <ErrorInline message={apiErrorMessage(bootstrap.error, "계정 정보를 불러오지 못했어요.")} onRetry={() => void bootstrap.refetch()} retrying={bootstrap.isRefetching} />
      )}
      {bootstrap.data && (
        <>
          <Surface as="section" className="flex items-center gap-4 p-5">
            <div data-profile="" className="contents">
              <span aria-hidden className="flex size-14 shrink-0 items-center justify-center rounded-full bg-empty text-[22px] font-bold text-primary">
                {user?.name?.slice(0, 1) ?? "?"}
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-[20px] font-bold leading-[1.4] text-ink">{user?.name}</p>
                  <Chip size="sm">{owner ? "사장님" : "알바생"}</Chip>
                </div>
                {store?.store_name && <p className="truncate text-[14px] text-ink-muted">{store.store_name}</p>}
              </div>
            </div>
          </Surface>
          <ListGroup>
            {rows.map((row) => (
              <ListRow
                key={row.title}
                title={row.title}
                href={row.href}
                badge={row.badge ? <CountBadge n={row.badge} tone="danger" /> : undefined}
              />
            ))}
          </ListGroup>
        </>
      )}
      <div className="mt-auto pt-6">
        {logout.error && <ErrorInline message={apiErrorMessage(logout.error, "로그아웃하지 못했어요.")} onRetry={() => logout.mutate()} retrying={logout.isPending} />}
        <TextButton disabled={logout.isPending} onClick={() => setConfirming(true)}>로그아웃</TextButton>
      </div>
      <ConfirmDialog
        open={confirming}
        title="로그아웃할까요?"
        confirmLabel="로그아웃"
        tone="danger"
        loading={logout.isPending}
        onConfirm={() => {
          setConfirming(false);
          logout.mutate();
        }}
        onCancel={() => setConfirming(false)}
      />
    </Screen>
  );
}
