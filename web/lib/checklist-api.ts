import { fetchJson } from "./api";

export type Counts = { total: number; done: number };
export type CheckItem = {
  card_version_id: number;
  line_no: number;
  checked: boolean;
};
export type CheckRequest = CheckItem & { business_date: string };
export type Shift = {
  shift_id: number;
  name: string;
  starts_at: string | null;
  ends_at: string | null;
  sort_order: number;
  card_ids: number[];
};
export type ShiftProgress = Omit<Shift, "sort_order" | "card_ids"> &
  Counts & { submitted: boolean };
export type Submission = {
  submitted_at: string;
  total_lines: number;
  done_lines: number;
  late?: boolean;
};
export type ChecklistGroup = {
  shift_id: number | null;
  name: string;
  cards: {
    card_id: number;
    card_version_id: number;
    title: string;
    lines: { line_no: number; text: string; checked: boolean }[];
  }[];
};
export type ChecklistToday = {
  business_date: string;
  previous_business_date: string;
  previous_submitted: boolean;
  scope: { all: boolean; shift_ids: number[] };
  current_shift_id: number | null;
  upcoming: boolean;
  shifts: ShiftProgress[];
  groups: ChecklistGroup[];
  view: Counts;
  scope_counts: Counts;
  my_submission: Submission | null;
};
export type ChecklistStatus = {
  business_date: string;
  current_shift_id: number | null;
  shifts: ShiftProgress[];
  scope_counts: Counts;
  last_submission:
    (Submission & { business_date: string; shift_names: string[] }) | null;
};
export type ChecklistMember = {
  member_id: number;
  user_id: number;
  name: string;
  role: "OWNER" | "STAFF";
  shift_ids: number[];
};
export type ChecklistSettings = {
  business_day_starts_at: string;
  staff_records_visible: boolean;
  timezone: string;
};
export type CardLinks = { checklist: boolean; shift_ids: number[] };
export type Records = {
  user_id: number;
  month: string;
  visible: boolean;
  recording: boolean;
  days: {
    date: string;
    percent: number | null;
    total: number | null;
    done: number | null;
    checked_lines: number;
    submitted: boolean;
  }[];
};
export type RecordDay = {
  date: string;
  visible: boolean;
  lines: { title: string; text: string; checked_at: string }[];
  submission: Submission | null;
};
export type ShiftInput = {
  name: string;
  starts_at: string | null;
  ends_at: string | null;
  clear_time?: boolean;
};

function request<T>(
  token: string,
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
) {
  return fetchJson<T>(`/checklist${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    signal,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}
export const checklistApi = {
  today: (
    token: string,
    shift?: number | null,
    date?: string | null,
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams();
    if (shift) params.set("shift_id", String(shift));
    if (date) params.set("date", date);
    return request<ChecklistToday>(
      token,
      `/today?${params}`,
      "GET",
      undefined,
      signal,
    );
  },
  check: (token: string, body: CheckRequest) =>
    request<{ submitted: boolean }>(token, "/checks", "PUT", body),
  submit: (token: string, business_date: string, checks: CheckItem[] = []) =>
    request<{ submission: Submission }>(token, "/submissions", "POST", {
      business_date,
      checks,
    }),
  status: (token: string, signal?: AbortSignal) =>
    request<ChecklistStatus>(token, "/status", "GET", undefined, signal),
  shifts: (token: string, signal?: AbortSignal) =>
    request<{ items: Shift[] }>(token, "/shifts", "GET", undefined, signal),
  createShift: (token: string, body: ShiftInput) =>
    request<Shift>(token, "/shifts", "POST", body),
  updateShift: (token: string, id: number, body: ShiftInput) =>
    request<Shift>(token, `/shifts/${id}`, "PATCH", body),
  deleteShift: (token: string, id: number) =>
    request<void>(token, `/shifts/${id}`, "DELETE"),
  order: (token: string, shift_ids: number[]) =>
    request(token, "/shifts/order", "PUT", { shift_ids }),
  preset: (token: string) => request(token, "/shifts/preset", "POST"),
  shiftCards: (token: string, id: number, ids: number[]) =>
    request(token, `/shifts/${id}/cards`, "PUT", { ids }),
  card: (token: string, id: number, signal?: AbortSignal) =>
    request<CardLinks>(token, `/cards/${id}`, "GET", undefined, signal),
  setCard: (token: string, id: number, body: CardLinks) =>
    request<CardLinks>(token, `/cards/${id}`, "PUT", body),
  members: (token: string, signal?: AbortSignal) =>
    request<{ items: ChecklistMember[] }>(
      token,
      "/members",
      "GET",
      undefined,
      signal,
    ),
  memberShifts: (token: string, id: number, ids: number[]) =>
    request(token, `/members/${id}/shifts`, "PUT", { ids }),
  settings: (token: string, signal?: AbortSignal) =>
    request<ChecklistSettings>(token, "/settings", "GET", undefined, signal),
  setSettings: (token: string, body: Partial<ChecklistSettings>) =>
    request<ChecklistSettings>(token, "/settings", "PATCH", body),
  me: (token: string, signal?: AbortSignal) =>
    request<{ personal_records_enabled: boolean }>(
      token,
      "/me",
      "GET",
      undefined,
      signal,
    ),
  setMe: (token: string, personal_records_enabled: boolean) =>
    request(token, "/me", "PATCH", { personal_records_enabled }),
  records: (
    token: string,
    month: string,
    user: number | null,
    signal?: AbortSignal,
  ) =>
    request<Records>(
      token,
      `/records?month=${month}${user ? `&user_id=${user}` : ""}`,
      "GET",
      undefined,
      signal,
    ),
  recordDay: (
    token: string,
    date: string,
    user: number | null,
    signal?: AbortSignal,
  ) =>
    request<RecordDay>(
      token,
      `/records/${date}${user ? `?user_id=${user}` : ""}`,
      "GET",
      undefined,
      signal,
    ),
};
