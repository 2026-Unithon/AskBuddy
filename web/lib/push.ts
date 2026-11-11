// Web Push 구독. 점주 알림 설정과 알바 승인 알림이 같이 쓴다
import {
  deleteMyPushSubscription,
  deletePushSubscription,
  getPushKey,
  saveMyPushSubscription,
  savePushSubscription,
} from "./api";
import type { PushEnv } from "./push-state";

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

// ── 설정의 이 기기 푸시(계획 8) ─────────────────────────────────────────────
// 사장님은 /notifications/subscriptions, 알바생은 /notifications/my-subscriptions 에 저장한다(지금 두 화면이 쓰는 계약)
type Role = "OWNER" | "STAFF";
const saveFor = (role: Role) => (role === "OWNER" ? savePushSubscription : saveMyPushSubscription);
const deleteFor = (role: Role) => (role === "OWNER" ? deletePushSubscription : deleteMyPushSubscription);

/** 브라우저 쪽 푸시 상태. 서비스 워커를 새로 등록하지 않고 이미 있는 구독만 본다 */
export async function readPushEnv(): Promise<Omit<PushEnv, "configured">> {
  const hasPushApi = "serviceWorker" in navigator && "PushManager" in window;
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const standalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    Boolean((navigator as Navigator & { standalone?: boolean }).standalone);
  const permission = typeof Notification === "undefined" ? "default" : Notification.permission;
  let subscribed = false;
  if (hasPushApi) {
    const registration = await navigator.serviceWorker.getRegistration("/");
    subscribed = Boolean(await registration?.pushManager.getSubscription());
  }
  return { hasPushApi, ios, standalone, permission, subscribed };
}

/** 켜기. 권한 요청은 사용자 클릭 안에서 불러야 한다(iOS 요구) */
export async function turnPushOn(role: Role, token: string): Promise<"ON" | "DENIED" | "UNSUPPORTED" | "NOT_CONFIGURED"> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return "UNSUPPORTED";
  const key = await getPushKey(token);
  if (!key.push_configured || !key.vapid_public_key) return "NOT_CONFIGURED";
  if ((await Notification.requestPermission()) !== "granted") return "DENIED";
  const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" });
  await navigator.serviceWorker.ready;
  const current =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: applicationServerKey(key.vapid_public_key),
    }));
  await saveFor(role)(current.toJSON(), token);
  return "ON";
}

/** 끄기. 서버가 endpoint 로 upsert 하므로 다시 저장해 번호를 받은 뒤 그 번호를 지우고, 브라우저 구독도 푼다 */
export async function turnPushOff(role: Role, token: string): Promise<void> {
  const registration = await navigator.serviceWorker.getRegistration("/");
  const current = await registration?.pushManager.getSubscription();
  if (!current) return;
  const saved = await saveFor(role)(current.toJSON(), token);
  await deleteFor(role)(saved.subscription_id, token);
  await current.unsubscribe();
}
