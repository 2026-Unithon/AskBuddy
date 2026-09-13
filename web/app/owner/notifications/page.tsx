"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import {
  ApiError,
  deletePushSubscription,
  markNotificationRead,
  savePushSubscription,
  type NotificationItem,
} from "@/lib/api";
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
  const [subscription, setSubscription] = useState<PushSubscription | null>(null);
  const [subscriptionId, setSubscriptionId] = useState<number | null>(null);
  const [browserSupported, setBrowserSupported] = useState(false);
  const [isIOS, setIsIOS] = useState(false);
  const [isStandalone, setIsStandalone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const supported = "serviceWorker" in navigator && "PushManager" in window;
    const stateTimer = window.setTimeout(() => {
      setBrowserSupported(supported);
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
      await queryClient.invalidateQueries({ queryKey: queryKeys.notificationSupport(state.storeId) });
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

  async function openNotification(item: NotificationItem) {
    if (!state.token) return;
    if (!item.read_at) {
      try {
        const result = await markNotificationRead(item.notification_id, state.token);
        queryClient.setQueryData(
          queryKeys.notificationPages(state.storeId),
          (current: typeof notifications.data) => current
            ? {
                ...current,
                pages: current.pages.map((page, index) => ({
                  ...page,
                  unread_count: index === 0 ? Math.max(0, page.unread_count - 1) : page.unread_count,
                  items: page.items.map((value) => value.notification_id === item.notification_id
                    ? { ...value, read_at: result.read_at }
                    : value),
                })),
              }
            : current
        );
        await queryClient.invalidateQueries({ queryKey: queryKeys.notificationsRoot(state.storeId) });
      } catch (requestError) {
        setError(messageForError(requestError));
        return;
      }
    }
    router.push(item.destination);
  }

  const pushReady = browserSupported && support?.push_configured;

  return (
    <Shell>
      <TopBar title="알림" backHref="/owner/upload" />
      <div className="px-5 pb-7 space-y-5 overflow-y-auto">
        <Card className="p-4 space-y-3">
          <div className="flex items-start gap-3">
            <span className="text-2xl" aria-hidden>🔔</span>
            <div className="flex-1">
              <p className="text-sm font-bold text-brand-700">휴대폰 알림</p>
              <p className="text-xs text-muted mt-1 leading-relaxed">
                새 질문과 카드 추출 완료를 알려드려요. 허용하지 않아도 아래 앱 알림은 항상 남습니다.
              </p>
            </div>
          </div>
          {!browserSupported && (
            <p className="text-xs rounded-xl bg-surface-muted px-3 py-2">이 브라우저는 Web Push를 지원하지 않아요.</p>
          )}
          {isIOS && !isStandalone && (
            <p className="text-xs rounded-xl bg-accent-50 px-3 py-2 leading-relaxed">
              iPhone에서는 공유 버튼을 눌러 홈 화면에 추가한 뒤, 설치된 AskBuddy에서 알림을 켜주세요.
            </p>
          )}
          {browserSupported && support && !support.push_configured && (
            <p className="text-xs rounded-xl bg-surface-muted px-3 py-2">서버의 Push 키 설정이 아직 준비되지 않았어요. 앱 내부 알림은 정상 작동합니다.</p>
          )}
          {pushReady && (subscription ? (
            <Button variant="secondary" onClick={disablePush} disabled={busy} className="w-full">
              {busy ? "처리 중" : "휴대폰 알림 끄기"}
            </Button>
          ) : (
            <Button onClick={enablePush} disabled={busy || (isIOS && !isStandalone)} className="w-full">
              {busy ? "처리 중" : "휴대폰 알림 받기"}
            </Button>
          ))}
        </Card>

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-brand-700">앱 알림</h2>
            <button onClick={() => void notifications.refetch()} className="text-xs font-semibold text-brand-500">새로고침</button>
          </div>
          {(error || supportQuery.error || notifications.error) && <p role="alert" className="text-xs font-medium text-[#E57373]">{error ?? messageForError(supportQuery.error ?? notifications.error)}</p>}
          {notifications.isLoading && <div className="space-y-3" aria-label="알림 불러오는 중">{[0, 1, 2].map((item) => <div key={item} className="h-24 animate-pulse rounded-2xl bg-surface-muted" />)}</div>}
          {notifications.isFetching && !notifications.isLoading && !notifications.isFetchingNextPage && <p className="text-[11px] text-muted">최신 알림 확인 중…</p>}
          {!notifications.isLoading && items.length === 0 && !error && !notifications.error && (
            <Card className="p-6 text-center text-sm text-muted">아직 도착한 알림이 없어요.</Card>
          )}
          {items.map((item) => (
            <button key={item.notification_id} onClick={() => void openNotification(item)} className="block w-full text-left">
              <Card className={`p-4 ${item.read_at ? "opacity-65" : "border-brand-500/40"}`}>
                <div className="flex items-start gap-3">
                  <span className="text-xl" aria-hidden>{item.event_type === "PENDING_QUESTION" ? "❓" : "✨"}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-bold">{item.title}</p>
                      {!item.read_at && <span className="w-2 h-2 rounded-full bg-brand-500" aria-label="읽지 않음" />}
                    </div>
                    <p className="text-xs text-muted mt-1 break-words">{item.body}</p>
                    <p className="text-[11px] text-muted mt-2">{formatTime(item.created_at)}</p>
                  </div>
                  {item.action_completed && <Badge tone="neutral">처리 완료</Badge>}
                </div>
              </Card>
            </button>
          ))}
          {notifications.hasNextPage && (
            <Button variant="secondary" className="w-full" disabled={notifications.isFetchingNextPage} onClick={() => void notifications.fetchNextPage()}>
              {notifications.isFetchingNextPage ? "불러오는 중…" : "이전 알림 더 보기"}
            </Button>
          )}
        </section>
      </div>
    </Shell>
  );
}
