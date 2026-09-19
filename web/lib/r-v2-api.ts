import { ApiError } from "./api";

export type RAnswer = {
  action: "ANSWER" | "CLARIFY" | "ESCALATE" | "REFUSE" | "SAFE_ROUTE";
  message: string;
  context_id: string | null;
  allowed_options: string[];
  pending_id: string | null;
  citations: { card_id: string; card_version_id: string; block_id: string; source_availability: string }[];
};
export type RMessage = {
  message_id: string; sender: "USER" | "BUDDY"; content: string;
  receipt_id: string | null;
  original_question: string | null;
  response: RAnswer | null; context_revision: number | null;
  owner_answer_id: string | null; revision: number | null; knowledge_status: string | null;
};
export type RChatInput = {
  request_id: string; session_id: string; question: string;
  context_id?: string; context_revision?: number; option?: string;
  policy_receipt_id?: string;
};
export type ROwnerInput = { request_id: string; answer: string; expected_revision: number };
export type RRetryInput = { request_id: string; reason: string };
export type RNotification = { notification_id: string; title: string; body: string; destination: string; read: boolean };
export type RPending = {
  pending_id: string; status: string;
  occurrences: { receipt_id: string; original_question: string;
    resolved_query: { confirmed_slots?: Record<string, string> };
    context_snapshot: { context?: { original_question?: string } } | null }[];
  answers: { owner_answer_id: string; answer: string; revision: number; knowledge_status: string;
    event_id: string | null; attempts: number; retry_available: boolean }[];
};

async function request<T>(path: string, token: string, signal?: AbortSignal, body?: unknown): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/learn/v2${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal ? AbortSignal.any([signal, controller.signal]) : controller.signal,
    });
    const payload: unknown = await response.json();
    if (!response.ok) {
      const error = payload && typeof payload === "object" && "error" in payload ? payload.error : null;
      const message = error && typeof error === "object" && "message" in error && typeof error.message === "string"
        ? error.message : "요청을 완료하지 못했습니다.";
      const code = error && typeof error === "object" && "code" in error && typeof error.code === "string" ? error.code : undefined;
      throw new ApiError(response.status, message, path, { code });
    }
    return payload as T;
  } finally { clearTimeout(timer); }
}

export const rSessions = (token: string, signal?: AbortSignal) =>
  request<{ sessions: { session_id: string }[] }>("/sessions", token, signal);
export const rCreateSession = (token: string, request_id: string) =>
  request<{ session_id: string }>("/sessions", token, undefined, { request_id });
export const rAsk = (token: string, body: RChatInput) => request<RAnswer>("/chat", token, undefined, body);
export const rHistory = (token: string, session: string, after: string | null, signal?: AbortSignal) =>
  request<{ messages: RMessage[]; next_after: string | null }>(`/sessions/${encodeURIComponent(session)}/history${after ? `?after=${after}` : ""}`, token, signal);
export const rPendingList = (token: string, after: string | null, signal?: AbortSignal) =>
  request<{ questions: { pending_id: string; question: string; status: string }[]; next_after: string | null }>(`/pending${after ? `?after=${after}` : ""}`, token, signal);
export const rPendingDetail = (token: string, id: string, signal?: AbortSignal) =>
  request<RPending>(`/pending/${encodeURIComponent(id)}`, token, signal);
export const rOwnerAnswer = (token: string, id: string, body: ROwnerInput) =>
  request<{ owner_answer_id: string; knowledge_status: string }>(`/pending/${encodeURIComponent(id)}/answers`, token, undefined, body);
export const rOwnerRetry = (token: string, id: string, body: RRetryInput) =>
  request<{ event_id: string; status: string }>(`/owner-events/${encodeURIComponent(id)}/retry`, token, undefined, body);
export const rCitation = (token: string, receipt: string, order: number, signal?: AbortSignal) =>
  request<{ title: string; text: string; card_version_id: string; source_availability: string }>(`/receipts/${encodeURIComponent(receipt)}/citations/${order}`, token, signal);
export const rNotifications = (token: string, after: string | null, signal?: AbortSignal) =>
  request<{ notifications: RNotification[]; next_after: string | null }>(`/notifications${after ? `?after=${after}` : ""}`, token, signal);
export const rReadNotification = (token: string, id: string) =>
  request<{ notification_id: string; read: boolean }>(`/notifications/${encodeURIComponent(id)}/read`, token, undefined, {});
