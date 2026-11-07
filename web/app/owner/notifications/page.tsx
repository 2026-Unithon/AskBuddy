"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import {
  BackButton,
  Banner,
  Button,
  Chip,
  Coachmark,
  CountBadge,
  Empty,
  ErrorInline,
  PageHeader,
  Screen,
  Skeleton,
  SwipeRow,
  TextButton,
} from "@/components/kit";
import { useApp } from "@/lib/store";
import {
  ApiError,
  deletePushSubscription,
  listNotifications,
  markNotificationRead,
  savePushSubscription,
  type NotificationItem,
} from "@/lib/api";

// 알림 켜기 권유에 '나중에'를 누르면 이 기기에서 다시 띄우지 않는다(G6, 사용자 편의라 브라우저 저장소)
const PUSH_LATER_KEY = "askbuddy:push-banner";
function readLater() {
  try {
    return localStorage.getItem(PUSH_LATER_KEY) === "later";
  } catch {
    return false;
  }
}
const COACH = [{ target: "[data-notification-unread]", text: "밀면 읽음으로 바뀌어요" }];
type Pages = InfiniteData<Awaited<ReturnType<typeof listNotifications>>>;
import { notificationPagesQuery, notificationSupportQuery, queryKeys } from "@/lib/query";

function applicationServerKey(value: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function messageForError(error: unknown) {
  if (error instanceof ApiError) return error.detail || "알림 요청에 실패했어요.";
  return "서버에 연결할 수 없습니다.";
}

export default function NotificationsPage() {
  const router = useRouter();
  const { state } = useApp();
  const queryClient = useQueryClient();
  const supportQuery = useQuery(notificationSupportQuery(state.token, state.storeId));
  const notifications = useInfiniteQuery(notificationPagesQuery(state.token, state.storeId));
  const support = supportQuery.data;
  const items = notifications.data?.pages.flatMap((page) => page.items) ?? [];
  const unread = notifications.data?.pages[0]?.unread_count ?? 0;
  const [subscription, setSubscription] = useState<PushSubscription | null>(null);
  const [subscriptionId, setSubscriptionId] = useState<number | null>(null);
  const [browserSupported, setBrowserSupported] = useState(false);
  const [isIOS, setIsIOS] = useState(false);
  const [isStandalone, setIsStandalone] = useState(false);
  const [later, setLater] = useState(true);
  const [busy, setBusy] = useState(false);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const supported = "serviceWorker" in navigator && "PushManager" in window;
    const stateTimer = window.setTimeout(() => {
      setBrowserSupported(supported);
      setLater(readLater());
      setIsIOS(/iPad|iPhone|iPod/.test(navigator.userAgent));
      setIsStandalone(
        window.matchMedia("(display-mode: standalone)").matches ||
          Boolean((navigator as Navigator & { standalone?: boolean }).standalone)
      );
    }, 0);
    if (!supported) return () => window.clearTimeout(stateTimer);
    let cancelled = false;
    navigator.serviceWorker
      .register("/sw.js", { scope: "/", updateViaCache: "none" })
      .then((registration) => registration.pushManager.getSubscription())
      .then(async (current) => {
        if (cancelled || !current || !state.token) return;
        setSubscription(current);
        const saved = await savePushSubscription(current.toJSON(), state.token);
        if (!cancelled) setSubscriptionId(saved.subscription_id);
      })
      .catch(() => {
        if (!cancelled) setError("브라우저 알림 상태를 확인하지 못했어요.");
      });
    return () => {
      cancelled = true;
      window.clearTimeout(stateTimer);
    };
  }, [state.token]);

  async function enablePush() {
    if (!state.token || !support?.vapid_public_key || busy) return;
    setBusy(true);
    setError(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setError("알림 권한이 허용되지 않았어요. 브라우저 설정에서 다시 켤 수 있어요.");
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      const current =
        (await registration.pushManager.getSubscription()) ??
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: applicationServerKey(support.vapid_public_key),
        }));
      const saved = await savePushSubscription(current.toJSON(), state.token);
      setSubscription(current);
      setSubscriptionId(saved.subscription_id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.notificationSupport(state.storeId) });
    } catch (requestError) {
      setError(messageForError(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function disablePush() {
    if (!state.token || !subscription || subscriptionId === null || busy) return;
    setBusy(true);
    setError(null);
    try {
      await subscription.unsubscribe();
      await deletePushSubscription(subscriptionId, state.token);
      setSubscription(null);
      setSubscriptionId(null);
    } catch (requestError) {
      setError(messageForError(requestError));
    } finally {
      setBusy(false);
    }
  }

  function pushLater() {
    setLater(true);
    try {
      localStorage.setItem(PUSH_LATER_KEY, "later");
    } catch {
      // 저장 못 하면 다음에 한 번 더 보인다
    }
  }

  // 캐시의 알림 하나를 읽음/안 읽음으로 바꾼다(첫 페이지의 읽지 않은 수도 같이)
  const setRead = (id: number, readAt: string | null) =>
    queryClient.setQueryData<Pages>(queryKeys.notificationPages(state.storeId), (current) =>
      current
        ? {
            ...current,
            pages: current.pages.map((page, index) => ({
              ...page,
              unread_count: index === 0 ? Math.max(0, page.unread_count + (readAt ? -1 : 1)) : page.unread_count,
              items: page.items.map((value) => (value.notification_id === id ? { ...value, read_at: readAt } : value)),
            })),
          }
        : current
    );

  // 밀어서 읽음(o18b): 바로 읽음으로 보이고, 실패하면 되돌린다
  const markRead = useMutation({
    mutationFn: (item: NotificationItem) => markNotificationRead(item.notification_id, state.token!),
    onMutate: (item) => {
      void queryClient.cancelQueries({ queryKey: queryKeys.notificationPages(state.storeId) });
      setRead(item.notification_id, new Date().toISOString());
    },
    onError: (_error, item) => setRead(item.notification_id, null),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: queryKeys.notificationsRoot(state.storeId) }),
  });

  async function openNotification(item: NotificationItem) {
    if (!state.token || openingId !== null) return;
    setOpeningId(item.notification_id);
    if (!item.read_at) {
      try {
        const result = await markNotificationRead(item.notification_id, state.token);
        setRead(item.notification_id, result.read_at);
        void queryClient.invalidateQueries({ queryKey: queryKeys.notificationsRoot(state.storeId) });
      } catch (requestError) {
        setError(messageForError(requestError));
        setOpeningId(null);
        return;
      }
    }
    router.push(item.destination);
  }

  const pushReady = browserSupported && support?.push_configured;
  const firstUnread = items.find((item) => !item.read_at)?.notification_id;

  return (
    <Screen onRefresh={() => notifications.refetch()}>
      <BackButton parent="/owner" />
      <PageHeader
        title={
          <>
            알림
            {unread > 0 && <CountBadge n={unread} tone="danger" />}
          </>
        }
        action={
          <TextButton disabled={notifications.isFetching} onClick={() => void notifications.refetch()}>
            새로고침
          </TextButton>
        }
      />
      {pushReady && !subscription && !later && (
        <Banner tone="info" action={{ label: "알림 받기", onClick: () => void enablePush() }} onDismiss={pushLater} dismissLabel="나중에">
          질문이 오면 휴대폰으로 바로 알려드릴까요?
        </Banner>
      )}
      {isIOS && !isStandalone && <Banner tone="info">iPhone에서는 공유 버튼을 눌러 홈 화면에 추가한 뒤, 설치된 AskBuddy에서 알림을 켜주세요.</Banner>}
      {(error || supportQuery.error || notifications.error) && (
        <ErrorInline
          message={error ?? messageForError(supportQuery.error ?? notifications.error)}
          onRetry={notifications.error ? () => void notifications.refetch() : undefined}
        />
      )}
      {markRead.error && <ErrorInline message="읽음으로 바꾸지 못했어요." />}
      {notifications.isLoading && (
        <div className="flex flex-col gap-2" aria-label="알림 불러오는 중">
          {[0, 1, 2].map((item) => (
            <Skeleton key={item} className="h-24" />
          ))}
        </div>
      )}
      {!notifications.isLoading && !notifications.error && items.length === 0 && <Empty title="아직 도착한 알림이 없어요" />}
      <ul className="flex flex-col gap-2">
        {items.map((item) => {
          const row = (
            <button
              type="button"
              data-notification=""
              onClick={() => void openNotification(item)}
              disabled={openingId === item.notification_id}
              aria-busy={openingId === item.notification_id || undefined}
              className={`flex min-h-11 w-full items-start gap-3 rounded-[20px] bg-surface p-4 text-left shadow-card disabled:opacity-60 ${item.read_at ? "opacity-60" : ""}`}
            >
              <span className="text-xl" aria-hidden>
                {item.event_type === "PENDING_QUESTION" ? "❓" : item.event_type === "JOIN_REQUESTED" ? "👋" : "✨"}
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="flex items-center gap-2">
                  {!item.read_at && <span className="size-2 shrink-0 rounded-full bg-primary" aria-label="읽지 않음" />}
                  <span className="text-[15px] font-bold text-ink">{item.title}</span>
                </span>
                <span className="mt-1 break-words text-[14px] leading-relaxed text-ink-muted">{item.body}</span>
                <span className="mt-2 text-[12px] text-ink-muted">{formatTime(item.created_at)}</span>
              </span>
              {item.action_completed && <Chip size="sm">처리 완료</Chip>}
            </button>
          );
          return (
            <li key={item.notification_id} {...(item.notification_id === firstUnread ? { "data-notification-unread": "" } : {})}>
              {item.read_at ? (
                row
              ) : (
                <SwipeRow left={{ label: "읽음", ariaLabel: `${item.title} 읽음으로`, tone: "primary", onAction: () => markRead.mutate(item) }}>
                  {row}
                </SwipeRow>
              )}
            </li>
          );
        })}
      </ul>
      {notifications.hasNextPage && (
        <Button variant="secondary" loading={notifications.isFetchingNextPage} onClick={() => void notifications.fetchNextPage()}>
          이전 알림 더 보기
        </Button>
      )}
      {pushReady && !subscription && later && (
        <TextButton className="self-center" disabled={busy || (isIOS && !isStandalone)} onClick={() => void enablePush()}>
          휴대폰 알림 켜기
        </TextButton>
      )}
      {pushReady && subscription && (
        <TextButton className="self-center" disabled={busy} onClick={() => void disablePush()}>
          휴대폰 알림 끄기
        </TextButton>
      )}
      <Coachmark id="owner-notifications" steps={COACH} />
    </Screen>
  );
}
