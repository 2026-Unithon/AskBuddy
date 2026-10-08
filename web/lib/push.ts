// Web Push 구독. 점주 알림 설정과 알바 승인 알림이 같이 쓴다
import { getPushKey, saveMyPushSubscription } from "./api";

export const PUSH_MESSAGE = "askbuddy:push";

export function applicationServerKey(value: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

// 권한 요청은 반드시 사용자 버튼 클릭 안에서 부른다(iOS 요구)
export async function enablePersonalPush(token: string): Promise<"enabled" | "denied" | "unsupported" | "not_configured"> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return "unsupported";
  const key = await getPushKey(token);
  if (!key.push_configured || !key.vapid_public_key) return "not_configured";
  if ((await Notification.requestPermission()) !== "granted") return "denied";
  const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" });
  await navigator.serviceWorker.ready;
  const current = (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: applicationServerKey(key.vapid_public_key),
    }));
  await saveMyPushSubscription(current.toJSON(), token);
  return "enabled";
}
