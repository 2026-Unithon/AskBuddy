"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BackButton,
  Button,
  Chip,
  ConfirmDialog,
  CountBadge,
  ErrorInline,
  ListGroup,
  ListRow,
  PageHeader,
  Screen,
  Sheet,
  Skeleton,
  Surface,
  TextButton,
  focusRing,
} from "@/components/kit";
import { apiErrorMessage, logoutSession, renameMe, renameStore } from "@/lib/api";
import { bootstrapQuery, membersQuery, notificationsQuery, queryKeys } from "@/lib/query";
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
  // 이름 고치기 시트(o12a, 계획 7 Task 9). 화면 상태
  const [renaming, setRenaming] = useState<"me" | "store" | null>(null);

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
                  <PencilButton label="내 이름 고치기" onClick={() => setRenaming("me")} />
                </div>
                {store?.store_name && (
                  <div className="flex items-center gap-1">
                    <p className="truncate text-[14px] text-ink-muted">{store.store_name}</p>
                    {owner && <PencilButton label="매장 이름 고치기" onClick={() => setRenaming("store")} />}
                  </div>
                )}
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
      {renaming && (
        <RenameSheet
          title={renaming === "me" ? "내 이름 고치기" : "매장 이름 고치기"}
          initial={(renaming === "me" ? user?.name : store?.store_name) ?? ""}
          save={(name) => (renaming === "me" ? renameMe(name, state.token!) : renameStore(name, state.token!))}
          onClose={() => setRenaming(null)}
        />
      )}
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


function PencilButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" aria-label={label} onClick={onClick} className={`flex size-9 shrink-0 items-center justify-center rounded-full text-ink-muted ${focusRing}`}>
      <span aria-hidden className="text-[15px]">✎</span>
    </button>
  );
}

/** 이름 하나를 고치는 시트. 저장하면 계정 정보(bootstrap)를 다시 받는다. */
function RenameSheet({ title, initial, save, onClose }: { title: string; initial: string; save: (name: string) => Promise<unknown>; onClose: () => void }) {
  const { state } = useApp();
  const client = useQueryClient();
  // 입력 초안(서버 값 아님)
  const [name, setName] = useState(initial);
  const mutation = useMutation({
    mutationFn: () => save(name.trim()),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) });
      onClose();
    },
  });
  return (
    <Sheet open onClose={() => !mutation.isPending && onClose()} title={title}>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim() && !mutation.isPending) mutation.mutate();
        }}
      >
        <label className="flex flex-col gap-1.5">
          <span className="text-[14px] font-bold text-ink">이름</span>
          <input
            value={name}
            maxLength={50}
            onChange={(event) => setName(event.target.value)}
            className={`min-h-12 rounded-[14px] bg-surface px-4 text-[16px] text-ink shadow-card outline-none ${focusRing}`}
          />
        </label>
        {mutation.error && <ErrorInline message={apiErrorMessage(mutation.error, "이름을 바꾸지 못했어요.")} />}
        <Button type="submit" loading={mutation.isPending} disabled={!name.trim()}>
          저장
        </Button>
      </form>
    </Sheet>
  );
}
