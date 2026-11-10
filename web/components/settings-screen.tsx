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
import {
  apiErrorMessage,
  logoutSession,
  putToStorage,
  renameMe,
  renameStore,
  requestAvatarUpload,
  setAvatar,
} from "@/lib/api";
import {
  bootstrapQuery,
  membersQuery,
  notificationsQuery,
  queryKeys,
} from "@/lib/query";
import { useApp } from "@/lib/store";

type Row = { title: string; href: string; badge?: number };

/** 설정(o12a, s07a). 위는 프로필, 아래는 관리 항목. 기능이 없는 항목(언어 등)은 넣지 않는다. */
export function SettingsScreen({ role }: { role: "OWNER" | "STAFF" }) {
  const { state } = useApp();
  const owner = role === "OWNER";
  const bootstrap = useQuery(
    bootstrapQuery(state.token, state.userId, state.storeId),
  );
  // 뱃지: 합류 요청 수(사장님만), 읽지 않은 알림 수. 못 불러와도 줄은 그대로 보인다
  const members = useQuery({
    ...membersQuery(state.token, state.storeId),
    enabled: owner && Boolean(state.token && state.storeId),
  });
  const notifications = useQuery(
    notificationsQuery(state.token, state.storeId),
  );
  const unread = notifications.data?.unread_count ?? 0;
  const user = bootstrap.data?.user;
  const store = bootstrap.data?.store;
  const [confirming, setConfirming] = useState(false);
  // 프로필 고치기 시트(o12a). 화면 상태
  const [editing, setEditing] = useState(false);

  const rows: Row[] = owner
    ? [
        { title: "근무조", href: "/owner/shifts" },
        {
          title: "직원 관리",
          href: "/owner/members",
          badge: members.data?.pending.length,
        },
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
        <ErrorInline
          message={apiErrorMessage(
            bootstrap.error,
            "계정 정보를 불러오지 못했어요.",
          )}
          onRetry={() => void bootstrap.refetch()}
          retrying={bootstrap.isRefetching}
        />
      )}
      {bootstrap.data && (
        <>
          <div data-profile="">
            <Surface
              as="section"
              className="relative flex items-center gap-4 p-5"
            >
              <Avatar name={user?.name} url={user?.avatar_url ?? null} />
              <div className="flex min-w-0 flex-1 flex-col gap-1 pr-8">
                <div className="flex items-center gap-2">
                  <p className="truncate text-[20px] font-bold leading-[1.4] text-ink">
                    {user?.name}
                  </p>
                  <Chip size="sm">{owner ? "사장님" : "알바생"}</Chip>
                </div>
                {store?.store_name && (
                  <p className="truncate text-[14px] text-ink-muted">
                    {store.store_name}
                  </p>
                )}
              </div>
              {/* 연필 하나로 사진·이름·매장 이름(2026-11-08 사용자) */}
              <button
                type="button"
                aria-label="프로필 고치기"
                onClick={() => setEditing(true)}
                className={`absolute right-2 top-2 flex size-11 items-center justify-center rounded-full text-ink-muted ${focusRing}`}
              >
                <span aria-hidden className="text-[17px]">
                  ✎
                </span>
              </button>
            </Surface>
          </div>
          <ListGroup>
            {rows.map((row) => (
              <ListRow
                key={row.title}
                title={row.title}
                href={row.href}
                badge={
                  row.badge ? (
                    <CountBadge n={row.badge} tone="danger" />
                  ) : undefined
                }
              />
            ))}
          </ListGroup>
        </>
      )}
      <div className="mt-auto pt-6">
        {logout.error && (
          <ErrorInline
            message={apiErrorMessage(logout.error, "로그아웃하지 못했어요.")}
            onRetry={() => logout.mutate()}
            retrying={logout.isPending}
          />
        )}
        <TextButton
          disabled={logout.isPending}
          onClick={() => setConfirming(true)}
        >
          로그아웃
        </TextButton>
      </div>
      {editing && user && (
        <ProfileSheet
          owner={owner}
          initialName={user.name}
          initialStore={store?.store_name ?? ""}
          avatarUrl={user.avatar_url ?? null}
          onClose={() => setEditing(false)}
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

/** 프로필 사진. 없으면 이름 첫 글자 */
function Avatar({
  name,
  url,
  size = 56,
  label = "프로필 사진",
}: {
  name?: string;
  url: string | null;
  size?: number;
  label?: string;
}) {
  const style = { width: size, height: size };
  return url ? (
    // 비공개 버킷의 잠깐 읽는 URL 이라 next/image 최적화(서버 캐시)를 거치지 않고 배경으로 그린다
    <span
      role="img"
      aria-label={label}
      style={{ ...style, backgroundImage: `url("${url}")` }}
      className="shrink-0 rounded-full bg-empty bg-cover bg-center"
    />
  ) : (
    <span
      aria-hidden
      style={style}
      className="flex shrink-0 items-center justify-center rounded-full bg-empty text-[22px] font-bold text-primary"
    >
      {name?.slice(0, 1) ?? "?"}
    </span>
  );
}

/**
 * 사진·이름·매장 이름을 한 시트에서(2026-11-08). 바꾼 것만 보낸다.
 * 사진은 서명 URL 로 직접 올린 뒤 경로를 내 사진으로 정한다(불변식 7). 실패하면 입력은 그대로 두고 이유를 보인다.
 */
function ProfileSheet({
  owner,
  initialName,
  initialStore,
  avatarUrl,
  onClose,
}: {
  owner: boolean;
  initialName: string;
  initialStore: string;
  avatarUrl: string | null;
  onClose: () => void;
}) {
  const { state } = useApp();
  const client = useQueryClient();
  // 입력 초안(서버 값 아님)
  const [name, setName] = useState(initialName);
  const [storeName, setStoreName] = useState(initialStore);
  const [photo, setPhoto] = useState<{ file: File; preview: string } | null>(
    null,
  );
  const [photoError, setPhotoError] = useState<string | null>(null);
  // 이름이 먼저(실패가 적고 되돌릴 일도 없다), 사진은 뒤. 사진만 실패하면 이름은 남기고 무엇이 안 됐는지 알린다
  const [photoFailed, setPhotoFailed] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: async () => {
      setPhotoFailed(null);
      if (name.trim() !== initialName) await renameMe(name.trim(), state.token!);
      if (owner && storeName.trim() && storeName.trim() !== initialStore) await renameStore(storeName.trim(), state.token!);
      if (!photo) return true;
      try {
        const { upload_url, path } = await requestAvatarUpload(photo.file, state.token!);
        await putToStorage(upload_url, photo.file);
        await setAvatar(path, state.token!);
        return true;
      } catch (error) {
        setPhotoFailed(`이름은 저장했어요. 사진은 올리지 못했어요. ${apiErrorMessage(error, "잠시 뒤 다시 골라 주세요.")}`);
        return false;
      }
    },
    // 일부만 저장됐어도 화면은 서버 값으로 맞춘다
    onSettled: () => client.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) }),
    onSuccess: (done) => {
      if (done) onClose();
    },
  });
  const pick = (file: File | undefined) => {
    setPhotoError(null);
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type))
      return setPhotoError("사진은 JPG, PNG, WEBP 만 올릴 수 있어요.");
    if (file.size > 5 * 1024 * 1024)
      return setPhotoError("사진이 너무 커요. 5MB 아래로 골라 주세요.");
    setPhoto({ file, preview: URL.createObjectURL(file) });
  };
  const field = `min-h-12 rounded-[14px] bg-surface px-4 text-[16px] text-ink shadow-card outline-none ${focusRing}`;
  return (
    <Sheet
      open
      onClose={() => !mutation.isPending && onClose()}
      title="프로필 고치기"
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim() && !mutation.isPending) mutation.mutate();
        }}
      >
        <label className="flex cursor-pointer items-center gap-4 self-start">
          <Avatar
            name={name}
            url={photo?.preview ?? avatarUrl}
            size={64}
            label={photo ? "새 사진" : "프로필 사진"}
          />
          <span className="text-[15px] font-bold text-primary">
            사진 바꾸기
          </span>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            onChange={(event) => pick(event.target.files?.[0])}
          />
        </label>
        {photoError && <ErrorInline message={photoError} />}
        <label className="flex flex-col gap-1.5">
          <span className="text-[14px] font-bold text-ink">이름</span>
          <input
            value={name}
            maxLength={50}
            onChange={(event) => setName(event.target.value)}
            className={field}
          />
        </label>
        {owner && (
          <label className="flex flex-col gap-1.5">
            <span className="text-[14px] font-bold text-ink">매장 이름</span>
            <input
              value={storeName}
              maxLength={50}
              onChange={(event) => setStoreName(event.target.value)}
              className={field}
            />
          </label>
        )}
        {photoFailed && <ErrorInline message={photoFailed} />}
        {mutation.error && (
          <ErrorInline
            message={apiErrorMessage(
              mutation.error,
              "저장하지 못했어요. 다시 눌러 주세요.",
            )}
          />
        )}
        <Button
          type="submit"
          loading={mutation.isPending}
          disabled={!name.trim()}
        >
          저장
        </Button>
      </form>
    </Sheet>
  );
}
