import type { BootstrapResponse } from "./api";
export function authDestination(boot: BootstrapResponse, next: string | null): string {
  if (!next || !boot.store || !boot.user.role) return boot.default_destination;
  const prefix = boot.user.role === "OWNER" ? "/owner/" : "/staff/";
  try {
    const decoded = decodeURIComponent(next);
    if (!decoded.startsWith(prefix) || decoded.includes("\\") || decoded.includes("//") || /[\u0000-\u001f]/.test(decoded)) return boot.default_destination;
    if (decoded.split("?")[0].split("/").some((part) => part === "." || part === "..")) return boot.default_destination;
    return next;
  } catch { return boot.default_destination; }
}
