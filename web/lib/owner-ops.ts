import { fetchJson } from "./api";

// ---- /today-tasks — 사장이 보내는 오늘만 할 일 ----
export type TodayTaskTarget = {
  member_id: number;
  name: string;
  seen_at: string | null;
  done_at: string | null;
};
export type OwnerTodayTask = {
  task_id: number;
  body: string;
  original_text: string;
  created_at: string;
  targets: TodayTaskTarget[];
};
export type MyTodayTask = {
  task_id: number;
  body: string;
  created_at: string;
  seen: boolean;
  done: boolean;
};
export type TodayTaskCreate = { text: string; body?: string; member_ids: number[] };

// ---- /report/summary — 사장 리포트(건수만) ----
export type ReportSummary = {
  first_date: string;
  last_date: string;
  days: 7 | 30;
  questions: {
    questions: number;
    ai_answered: number;
    escalated: number;
    owner_answered: number;
    answer_minutes_median: number | null;
    waiting_now: number;
  };
  top_escalations: { question_id: number; question_text: string; status: string; asked: number }[];
  per_staff: { member_id: number; name: string; questions: number; escalated: number }[] | null;
  checklist: { submissions: number; complete: number };
  today_tasks: { tasks: number; assigned: number; done: number };
};

function request<T>(token: string, path: string, method = "GET", body?: unknown, signal?: AbortSignal) {
  return fetchJson<T>(path, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    signal,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

export const todayTasksApi = {
  list: (token: string, signal?: AbortSignal) =>
    request<{ business_date: string; items: OwnerTodayTask[] }>(token, "/today-tasks", "GET", undefined, signal),
  mine: (token: string, signal?: AbortSignal) =>
    request<{ business_date: string; items: MyTodayTask[] }>(token, "/today-tasks/mine", "GET", undefined, signal),
  create: (token: string, body: TodayTaskCreate) =>
    request<{ business_date: string; task: OwnerTodayTask }>(token, "/today-tasks", "POST", body),
  polish: (token: string, text: string) => request<{ body: string }>(token, "/today-tasks/polish", "POST", { text }),
  cancel: (token: string, taskId: number) => request<void>(token, `/today-tasks/${taskId}`, "DELETE"),
  done: (token: string, taskId: number, done: boolean) =>
    request<{ task_id: number; done: boolean }>(token, `/today-tasks/${taskId}/done`, "PUT", { done }),
  seen: (token: string, taskIds: number[]) =>
    request<{ updated: number }>(token, "/today-tasks/seen", "POST", { task_ids: taskIds }),
};

export const reportApi = {
  summary: (token: string, days: 7 | 30, signal?: AbortSignal) =>
    request<ReportSummary>(token, `/report/summary?days=${days}`, "GET", undefined, signal),
};

export const ownerOpsKeys = {
  todayTasks: (store: number | null) => ["today-tasks", store, "owner"] as const,
  myTodayTasks: (store: number | null, user: number | null) => ["today-tasks", store, "mine", user] as const,
  report: (store: number | null, days: 7 | 30) => ["report", store, days] as const,
};

/** 대상 한 명의 진행 상태. 화면 글은 여기서 정한다. */
export function targetState(target: TodayTaskTarget): "done" | "seen" | "unseen" {
  if (target.done_at) return "done";
  if (target.seen_at) return "seen";
  return "unseen";
}

/** 분을 사람이 읽는 길이로. 60분 이상은 시간 단위로 반올림한다. */
export function formatMinutes(minutes: number | null): string {
  if (minutes === null) return "아직 없음";
  if (minutes < 60) return `${minutes}분`;
  const hours = Math.round(minutes / 6) / 10;
  return `${Number.isInteger(hours) ? hours.toFixed(0) : hours}시간`;
}
