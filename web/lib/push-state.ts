// 이 기기 푸시 알림 상태 판정(계획 8). 브라우저 값만 받는 순수 함수라 단위 테스트로 본다
export type PushEnv = {
  hasPushApi: boolean;
  ios: boolean;
  standalone: boolean;
  permission: "default" | "granted" | "denied";
  subscribed: boolean;
  configured: boolean;
};
export type PushState = "IOS_NEEDS_HOME" | "UNSUPPORTED" | "NOT_CONFIGURED" | "DENIED" | "ON" | "OFF";

/** 판정 순서가 곧 우선순위다. 아이폰 Safari 탭은 푸시 API 가 있어도 홈 화면 앱이어야 받는다 */
export function pushState(env: PushEnv): PushState {
  if (env.ios && !env.standalone) return "IOS_NEEDS_HOME";
  if (!env.hasPushApi) return "UNSUPPORTED";
  if (!env.configured) return "NOT_CONFIGURED";
  if (env.permission === "denied") return "DENIED";
  if (env.permission === "granted" && env.subscribed) return "ON";
  return "OFF";
}
