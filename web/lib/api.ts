// FastAPI 호출 래퍼. Supabase는 절대 직접 호출하지 않는다 (CLAUDE.md 불변식 1).
// 백엔드가 아직 배포되지 않았거나 응답이 없으면, 호출한 쪽에서 mock 데이터로 대체할 수 있도록
// 실패를 조용히 삼키지 않고 예외를 던진다 — 화면단에서 catch 해서 판단한다.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 6000;

function authHeader(token?: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// 상태 코드를 실어 던진다 — 화면단이 401(로그인 필요)과 네트워크 단절을 구분해야 한다.
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    path: string
  ) {
    super(`${path} 실패: ${status}${detail ? ` — ${detail}` : ""}`);
    this.name = "ApiError";
  }
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      signal: controller.signal,
    });
    if (!res.ok) {
      // FastAPI 는 오류를 { detail: ... } 로 준다. 사람이 읽을 문구를 살려서 올린다.
      let detail = "";
      try {
        const body = (await res.json()) as { detail?: unknown };
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? "");
      } catch {
        // 본문이 JSON 이 아니면 상태 코드만으로 판단한다
      }
      throw new ApiError(res.status, detail, path);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

// ---- /auth/* — 로그인·가입·초대코드 합류 ----
// store_id 는 토큰 안에만 있다. 요청 본문으로 매장을 지정하지 않는다 (CLAUDE.md 불변식 4).

export type AuthUser = {
  user_id: number;
  name: string;
  email: string;
  role: "OWNER" | "STAFF";
  // 매장을 만들기 전 점주에게는 이 필드가 아예 없다. null 이 아니라 누락이다.
  store_id?: number | null;
};

export type AuthResponse = { token: string; user: AuthUser };

export async function login(email: string, password: string, role: "OWNER" | "STAFF") {
  return fetchJson<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password, role }),
  });
}

export async function signup(params: {
  name: string;
  email: string;
  password: string;
  role: "OWNER" | "STAFF";
  phone?: string;
}) {
  return fetchJson<AuthResponse>("/auth/signup", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

// 신입은 이 하나로 가입과 매장 합류가 동시에 끝난다.
export async function joinByInvite(params: {
  name: string;
  email: string;
  password: string;
  inviteCode: string;
}) {
  return fetchJson<AuthResponse>("/auth/join", {
    method: "POST",
    body: JSON.stringify({
      name: params.name,
      email: params.email,
      password: params.password,
      invite_code: params.inviteCode,
    }),
  });
}

export type CreatedStore = {
  store_id: number;
  store_slug: string;
  store_name: string;
};

// 매장을 만들면 store_id 가 담긴 새 토큰이 내려온다. 반드시 이 토큰으로 갈아끼운다 —
// 가입 직후 토큰에는 store_id 가 없어 /ingest/* 가 403 이다.
export async function createStore(
  params: { storeName: string; businessType: string },
  token: string
) {
  return fetchJson<{ token: string; store: CreatedStore }>("/auth/stores", {
    method: "POST",
    headers: authHeader(token),
    body: JSON.stringify({ store_name: params.storeName, business_type: params.businessType }),
  });
}

export async function createInvite(token: string) {
  return fetchJson<{ code: string; expires_at?: string }>("/auth/invites", {
    method: "POST",
    headers: authHeader(token),
    body: JSON.stringify({}),
  });
}

// ---- /ingest/categories — 업무 카테고리 (점주 설정) ----
// 추출기는 여기 켜진 카테고리 안에서만 카드를 만든다. 목록이 비면 카드가 0건이 된다.

export type TaskCategoryDto = {
  category_id: number;
  category_name: string;
  is_enabled: boolean;
  sort_order: number;
};

export async function listCategories(token: string) {
  return fetchJson<TaskCategoryDto[]>("/ingest/categories", { headers: authHeader(token) });
}

export async function updateCategories(
  categories: { category_name: string; is_enabled: boolean }[],
  token: string
) {
  return fetchJson<TaskCategoryDto[]>("/ingest/categories", {
    method: "PATCH",
    headers: authHeader(token),
    body: JSON.stringify({ categories }),
  });
}

// ---- /ingest/review — 검수 목록 (미승인 포함) ----
// /reg/cards 는 승인된 카드만 준다. 방금 등록한 카드는 미승인이라 거기 안 나온다.

export type ReviewCard = {
  card_id: number;
  title: string;
  content: string;
  category_id: number | null;
  category_name: string | null;
  source_id: number | null;
  source_type: string | null;
  source_title: string | null;
  confidence: number;
  is_verified: boolean;
  needs_attention: boolean;
  created_at: string;
};

export async function listReviewCards(
  token: string,
  opts: { verified?: boolean; sourceId?: number; limit?: number } = {}
) {
  const q = new URLSearchParams();
  if (opts.verified !== undefined) q.set("verified", String(opts.verified));
  if (opts.sourceId !== undefined) q.set("source_id", String(opts.sourceId));
  if (opts.limit !== undefined) q.set("limit", String(opts.limit));
  const res = await fetchJson<{ total: number; threshold: number; cards: ReviewCard[] }>(
    `/ingest/review${q.toString() ? `?${q}` : ""}`,
    { headers: authHeader(token) }
  );
  return res;
}

// ---- /reg/cards — 매장 지식카드 목록 ----

export type KnowledgeCard = {
  id: number;
  title: string;
  content: string;
  category: string | null;
  confidence: number;
  is_verified: boolean;
};

export async function listCards(storeSlug: string, token?: string) {
  const res = await fetchJson<{ store_id: string; cards: KnowledgeCard[] }>(
    `/reg/cards?store_id=${encodeURIComponent(storeSlug)}`,
    { headers: authHeader(token) }
  );
  return res.cards;
}

export type RetrieveCandidate = {
  id: string;
  content: string;
  category: string;
  score: number;
};

export type RetrieveResponse =
  | { kind: "hit"; candidates: RetrieveCandidate[] }
  | { kind: "miss"; reason: string; message: string };

// POST /reg/retrieve — 지식 진입점 하나 (개발가이드 6-3). 채팅·검색 어디서든 이걸 통과한다.
export async function retrieve(storeSlug: string, question: string, topK = 5) {
  return fetchJson<RetrieveResponse>("/reg/retrieve", {
    method: "POST",
    body: JSON.stringify({ store_id: storeSlug, question, top_k: topK }),
  });
}

// ---- /ingest/* — docs/ingest-contract.md 3단계 업로드 ----
// 실 배포 전까지는 로그인이 없어 Bearer 토큰이 비어 있을 수 있다.
// 그 경우 백엔드가 401을 돌려주고, 업로드 화면은 이를 잡아 로컬 진행률로 대체한다.

export type IngestSourceType = "VOICE" | "VIDEO" | "KAKAO" | "SCAN";

export async function requestUploadUrl(
  sourceType: IngestSourceType,
  filename: string,
  token?: string
) {
  return fetchJson<{ upload_url: string; file_url: string }>("/ingest/upload-url", {
    method: "POST",
    headers: authHeader(token),
    body: JSON.stringify({ source_type: sourceType, filename }),
  });
}

export async function putToStorage(uploadUrl: string, file: File) {
  const res = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "content-type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!res.ok) throw new Error(`업로드 실패: ${res.status}`);
}

export async function computeContentHash(file: File): Promise<string | undefined> {
  // crypto.subtle 은 https 또는 localhost 에서만 동작한다 (D9). 실패해도 등록은 계속 진행한다.
  try {
    const buf = await file.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", buf);
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return undefined;
  }
}

export async function registerSource(
  params: {
    sourceType: IngestSourceType;
    fileUrl: string;
    title?: string;
    fileSize?: number;
    contentHash?: string;
    meta: Record<string, unknown>;
  },
  token?: string
) {
  return fetchJson<{ source_id: number; status: string; duplicate: boolean }>("/ingest/sources", {
    method: "POST",
    headers: authHeader(token),
    body: JSON.stringify({
      source_type: params.sourceType,
      file_url: params.fileUrl,
      title: params.title,
      file_size: params.fileSize,
      content_hash: params.contentHash,
      meta: params.meta,
    }),
  });
}

export async function startProcessing(sourceId: number, token?: string, force = false) {
  return fetchJson<{ status: string }>("/ingest/process", {
    method: "POST",
    headers: authHeader(token),
    body: JSON.stringify({ source_id: sourceId, force }),
  });
}

export type IngestStatus = {
  source_id: number;
  status: "UPLOADED" | "PROCESSING" | "DONE" | "FAILED";
  error_message: string | null;
  processed_at: string | null;
  card_count: number;
};

export async function getIngestStatus(sourceId: number, token?: string) {
  return fetchJson<IngestStatus>(`/ingest/status?source_id=${sourceId}`, {
    headers: authHeader(token),
  });
}
