// FastAPI 호출 래퍼. Supabase는 절대 직접 호출하지 않는다 (CLAUDE.md 불변식 1).
// 실패를 조용히 삼키지 않고 종류와 복구 가능 여부를 보존해 올린다.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 6000;
const CHAT_TIMEOUT_MS = 20000;

function authHeader(token?: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

type FetchJsonInit = RequestInit & { timeoutMs?: number };

export const SESSION_EXPIRED_EVENT = "askbuddy:session-expired";
export type ApiErrorKind = "http" | "timeout" | "offline" | "network" | "aborted";

type ApiErrorMeta = {
  kind?: ApiErrorKind;
  code?: string;
  retryable?: boolean;
  requestId?: string | null;
  retryAfterMs?: number | null;
  details?: Record<string, unknown>;
};

// 상태 코드를 실어 던진다 — 화면단이 401(로그인 필요)과 네트워크 단절을 구분해야 한다.
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly path: string,
    readonly meta: ApiErrorMeta = {}
  ) {
    super(`${path} 실패: ${status}${detail ? ` — ${detail}` : ""}`);
    this.name = "ApiError";
  }

  get kind(): ApiErrorKind { return this.meta.kind ?? "http"; }
  get code(): string { return this.meta.code ?? (this.status ? `HTTP_${this.status}` : this.kind.toUpperCase()); }
  get retryable(): boolean { return this.meta.retryable ?? [429, 503, 504].includes(this.status); }
  get requestId(): string | null { return this.meta.requestId ?? null; }
  get retryAfterMs(): number | null { return this.meta.retryAfterMs ?? null; }
  get details(): Record<string, unknown> { return this.meta.details ?? {}; }
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1_000);
  const at = Date.parse(value);
  return Number.isFinite(at) ? Math.max(0, at - Date.now()) : null;
}

function requestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `web_${Date.now().toString(36)}`;
}

function emitSessionExpired(path: string) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: { path } }));
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  if (error.kind === "timeout") return "응답이 늦어 요청을 멈췄어요. 다시 시도해주세요.";
  if (error.kind === "offline") return "인터넷 연결이 끊겼어요. 연결 후 다시 시도해주세요.";
  if (error.kind === "network") return "서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.";
  if (error.kind === "aborted") return "요청이 취소되었습니다.";
  if (error.status === 429) return "요청이 많습니다. 잠시 후 다시 시도해주세요.";
  if (error.status === 503 || error.status === 504) return "서비스가 잠시 지연되고 있습니다. 입력은 유지됩니다.";
  return error.detail || fallback;
}

async function fetchJson<T>(path: string, init?: FetchJsonInit): Promise<T> {
  const { timeoutMs = TIMEOUT_MS, ...fetchInit } = init ?? {};
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const clientRequestId = requestId();
  const signal = fetchInit.signal
    ? AbortSignal.any([fetchInit.signal, controller.signal])
    : controller.signal;
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...fetchInit,
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": clientRequestId,
        ...(fetchInit.headers ?? {}),
      },
      signal,
    });
    if (!res.ok) {
      // FastAPI 는 오류를 { detail: ... } 로 준다. 사람이 읽을 문구를 살려서 올린다.
      let detail = "";
      let code: string | undefined;
      let retryable: boolean | undefined;
      let responseRequestId: string | null = res.headers.get("x-request-id");
      let details: Record<string, unknown> | undefined;
      try {
        const body = (await res.json()) as {
          detail?: unknown;
          error?: {
            code?: unknown;
            message?: unknown;
            retryable?: unknown;
            request_id?: unknown;
            details?: unknown;
          };
        };
        if (typeof body.error?.message === "string") {
          detail = body.error.message;
          if (typeof body.error.code === "string") code = body.error.code;
          if (typeof body.error.retryable === "boolean") retryable = body.error.retryable;
          if (typeof body.error.request_id === "string") responseRequestId = body.error.request_id;
          if (body.error.details && typeof body.error.details === "object") {
            details = body.error.details as Record<string, unknown>;
          }
        }
        else detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? "");
      } catch {
        // 본문이 JSON 이 아니면 상태 코드만으로 판단한다
      }
      if (res.status === 401 && new Headers(fetchInit.headers).has("Authorization")) {
        emitSessionExpired(path);
      }
      throw new ApiError(res.status, detail, path, {
        code,
        retryable,
        requestId: responseRequestId ?? clientRequestId,
        retryAfterMs: parseRetryAfter(res.headers.get("retry-after")),
        details,
      });
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (fetchInit.signal?.aborted) {
      throw new ApiError(0, "요청이 취소되었습니다.", path, {
        kind: "aborted",
        retryable: false,
        requestId: clientRequestId,
      });
    }
    if (controller.signal.aborted) {
      throw new ApiError(0, "요청 시간이 초과되었습니다.", path, {
        kind: "timeout",
        retryable: true,
        requestId: clientRequestId,
      });
    }
    const offline = typeof navigator !== "undefined" && !navigator.onLine;
    throw new ApiError(0, offline ? "인터넷 연결이 끊겼습니다." : "서버에 연결할 수 없습니다.", path, {
      kind: offline ? "offline" : "network",
      retryable: true,
      requestId: clientRequestId,
    });
  } finally {
    clearTimeout(timer);
  }
}

export type PreflightReport = {
  ok: boolean;
  deep: boolean;
  env: string;
  blocking: string[];
  settings: Record<string, string | number>;
  checks: Array<{
    name: string;
    state: "live" | "warn" | "dead";
    detail: string;
    fix: string;
    ms: number | null;
  }>;
};

export async function getPreflight(deep: boolean, signal?: AbortSignal) {
  return fetchJson<PreflightReport>(`/preflight${deep ? "?deep=1" : ""}`, {
    cache: "no-store",
    timeoutMs: deep ? 60_000 : TIMEOUT_MS,
    signal,
  });
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

export type BootstrapResponse = {
  user: {
    user_id: number;
    role: "OWNER" | "STAFF";
    name: string;
  };
  store: {
    store_id: number;
    store_name: string;
    guide_completed: boolean;
    category_version: number;
  } | null;
  badges: {
    waiting_questions: number;
    pending_cards: number;
  };
  default_destination: string;
};

export async function getBootstrap(token: string, signal?: AbortSignal) {
  return fetchJson<BootstrapResponse>("/app/bootstrap", {
    cache: "no-store",
    headers: authHeader(token),
    signal,
  });
}

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

export async function listCategories(token: string, signal?: AbortSignal) {
  return fetchJson<TaskCategoryDto[]>("/ingest/categories", { headers: authHeader(token), signal });
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
  opts: { status?: "pending" | "approved" | "all"; sourceId?: number; limit?: number } = {},
  signal?: AbortSignal
) {
  const q = new URLSearchParams();
  // 백엔드가 받는 건 status 다. verified 로 보내면 무시되고 pending 으로 떨어진다
  if (opts.status !== undefined) q.set("status", opts.status);
  if (opts.sourceId !== undefined) q.set("source_id", String(opts.sourceId));
  if (opts.limit !== undefined) q.set("limit", String(opts.limit));
  const res = await fetchJson<{ total: number; threshold: number; cards: ReviewCard[] }>(
    `/ingest/review${q.toString() ? `?${q}` : ""}`,
    { headers: authHeader(token), signal }
  );
  return res;
}

// 승인 = 검색 노출. 백엔드가 승인과 임베딩을 한 트랜잭션에 묶으므로,
// 200 이 오면 벡터까지 들어간 것이다. 실패한 카드만 error 를 달고 돌아온다.
export type ApproveResult = {
  card_id: number;
  is_verified: boolean;
  chunks?: number;
  error?: string | null;
};

export async function approveCards(cardIds: number[], token: string) {
  // 카드마다 임베딩 호출이 붙는다. 기본 6초로는 못 끝난다.
  return fetchJson<ApproveResult[]>("/ingest/cards/approve", {
    method: "POST",
    headers: authHeader(token),
    body: JSON.stringify({ card_ids: cardIds }),
    timeoutMs: 90000,
  });
}

// 카드 한 장씩. 점주가 카드별로 넣고 뺀다.
export async function approveCard(cardId: number, token: string) {
  // 승인 한 건마다 임베딩 호출이 붙는다. 기본 타임아웃으로는 못 끝난다
  return fetchJson<ApproveResult>(`/ingest/cards/${cardId}/approve`, {
    method: "POST",
    headers: authHeader(token),
    timeoutMs: 30000,
  });
}

export async function unapproveCard(cardId: number, token: string) {
  // 임베딩은 남기고 검색에서만 뺀다. 다시 넣으면 그대로 살아난다
  return fetchJson<ApproveResult>(`/ingest/cards/${cardId}/unapprove`, {
    method: "POST",
    headers: authHeader(token),
  });
}

export async function updateCard(
  cardId: number,
  body: { title: string; content: string },
  token: string
) {
  // 승인된 카드를 고치면 백엔드가 임베딩까지 다시 만든다
  return fetchJson<ApproveResult>(`/ingest/cards/${cardId}`, {
    method: "PATCH",
    headers: authHeader(token),
    body: JSON.stringify(body),
    timeoutMs: 30000,
  });
}

// ---- /learn/roadmap — 승인된 공개 카드 기반 직원 학습 ----

export type LearningStatus = "NOT_STARTED" | "DONE" | "RECONFIRM_REQUIRED";

export type RoadmapItemDto = {
  item_id: number;
  card_id: number;
  published_version_id: number;
  title: string;
  status: LearningStatus;
};

export type RoadmapStageDto = {
  category_id: number;
  name: string;
  order: number;
  items: RoadmapItemDto[];
};

export type RoadmapDto = {
  store: { store_id: number; name: string };
  counts: { total: number; done: number; reconfirm_required: number };
  continue_item_id: number | null;
  stages: RoadmapStageDto[];
};

export async function getRoadmap(token: string, signal?: AbortSignal) {
  return fetchJson<RoadmapDto>("/learn/roadmap", { headers: authHeader(token), signal });
}

export async function patchRoadmapItem(
  itemId: number,
  status: "LOCKED" | "IN_PROGRESS" | "DONE",
  token: string
) {
  return fetchJson<{ item_id: number; status: string; progress_rate: number }>(
    `/learn/roadmap/items/${itemId}`,
    { method: "PATCH", headers: authHeader(token), body: JSON.stringify({ status }) }
  );
}

export type CardSourceDto = {
  source_id: number;
  title: string | null;
  source_type: string | null;
  read_url: string | null;
};

export type CardEvidenceDto = {
  evidence_id: number;
  locator_type: string;
  locator: Record<string, unknown>;
  excerpt: string | null;
  source: CardSourceDto;
};

export type LearnItemDetail = {
  item_id: number;
  card_id: number;
  published_version_id: number;
  title: string;
  content: string;
  status: LearningStatus;
  category: { category_id: number; name: string };
  evidence: CardEvidenceDto[];
  return_to: { path: string; item_id: number };
};

export async function getLearnItem(itemId: number, token: string, signal?: AbortSignal) {
  return fetchJson<LearnItemDetail>(`/learn/items/${itemId}`, {
    headers: authHeader(token),
    signal,
  });
}

export async function setLearnItemCompletion(
  itemId: number,
  publishedVersionId: number,
  completed: boolean,
  token: string
) {
  return fetchJson<{
    item_id: number;
    card_id: number;
    published_version_id: number;
    status: LearningStatus;
    counts: RoadmapDto["counts"];
  }>(`/learn/items/${itemId}/completion`, {
    method: "PUT",
    headers: authHeader(token),
    body: JSON.stringify({ published_version_id: publishedVersionId, completed }),
  });
}

// ---- /cards — 신규 카드 검토 계약 ----

export type CardReviewStatus = "PENDING" | "NEEDS_REVIEW" | "APPROVED" | "EXCLUDED";
export type CardListItem = {
  card_id: number;
  review_status: CardReviewStatus;
  title: string;
  content: string;
  category: { category_id: number; name: string } | null;
  assignment_type: "AUTOMATIC" | "MANUAL";
  source: CardSourceDto | null;
  job_id: number | null;
  has_evidence: boolean;
  needs_review_reason: string | null;
  updated_at: string;
};

export type CardListResponse = {
  items: CardListItem[];
  next_cursor: number | null;
  total: number;
};

export type CardVersionDto = {
  version_id: number;
  version_no: number;
  title: string;
  content: string;
  change_source: string;
  created_at: string;
};

export type CardDetailDto = {
  card_id: number;
  review_status: CardReviewStatus;
  assignment_type: "AUTOMATIC" | "MANUAL";
  category: CardListItem["category"];
  source: CardSourceDto | null;
  job_id: number | null;
  needs_review_reason: string | null;
  draft: CardVersionDto | null;
  published: CardVersionDto | null;
  evidence: CardEvidenceDto[];
  events: Array<{
    event_id: number;
    action: string;
    from_status: string | null;
    to_status: string | null;
    from_category_id: number | null;
    to_category_id: number | null;
    metadata: Record<string, unknown>;
    created_at: string;
  }>;
  updated_at: string;
};

export type CardFilters = {
  status?: "pending" | "needs_review" | "approved" | "excluded" | "all";
  jobId?: number;
  categoryId?: number;
  query?: string;
  cursor?: number;
  limit?: number;
};

export async function listProductCards(token: string, filters: CardFilters = {}, signal?: AbortSignal) {
  const query = new URLSearchParams();
  if (filters.status) query.set("review_status", filters.status);
  if (filters.jobId) query.set("job_id", String(filters.jobId));
  if (filters.categoryId) query.set("category_id", String(filters.categoryId));
  if (filters.query) query.set("query", filters.query);
  if (filters.cursor) query.set("cursor", String(filters.cursor));
  query.set("limit", String(filters.limit ?? 100));
  return fetchJson<CardListResponse>(`/cards?${query}`, { headers: authHeader(token), signal });
}

export async function getProductCard(cardId: number, token: string, signal?: AbortSignal) {
  return fetchJson<CardDetailDto>(`/cards/${cardId}`, { headers: authHeader(token), signal });
}

export type CardMutationResult = {
  card_id: number;
  review_status: CardReviewStatus;
  draft_version_id: number | null;
  published_version_id: number | null;
  updated_at: string;
  undo_until: string | null;
};

export async function updateProductCardDraft(cardId: number, title: string, content: string, expectedVersionId: number, token: string) {
  return fetchJson<CardMutationResult>(`/cards/${cardId}/draft`, {
    method: "PATCH",
    headers: authHeader(token),
    body: JSON.stringify({ title, content, expected_version_id: expectedVersionId }),
  });
}

export async function mutateProductCard(cardId: number, action: "approve" | "exclude" | "restore", token: string) {
  return fetchJson<CardMutationResult>(`/cards/${cardId}/${action}`, {
    method: "POST",
    headers: authHeader(token),
    timeoutMs: action === "approve" ? 30_000 : TIMEOUT_MS,
  });
}

export async function moveProductCard(cardId: number, categoryId: number, expectedUpdatedAt: string, token: string) {
  return fetchJson<CardMutationResult>(`/cards/${cardId}/category`, {
    method: "PATCH",
    headers: authHeader(token),
    body: JSON.stringify({ category_id: categoryId, expected_updated_at: expectedUpdatedAt }),
  });
}

export type ProductCategory = { category_id: number; name: string; is_system: boolean; sort_order: number };
export type ProductCategoryList = {
  version: number;
  items: ProductCategory[];
  reclassification: { status: string; job_id: number } | null;
};

export async function listProductCategories(token: string, signal?: AbortSignal) {
  return fetchJson<ProductCategoryList>("/categories", { headers: authHeader(token), signal });
}

export async function createProductCategory(name: string, sortOrder: number, token: string) {
  return fetchJson<{ category: ProductCategory; version: number; reclass_job_id: number | null }>("/categories", {
    method: "POST",
    headers: authHeader(token),
    body: JSON.stringify({ name, sort_order: sortOrder }),
  });
}

export async function deleteProductCategory(categoryId: number, token: string) {
  return fetchJson<{ category_id: number; version: number; reclass_job_id: number | null }>(`/categories/${categoryId}`, {
    method: "DELETE",
    headers: authHeader(token),
  });
}

export type ReclassificationJob = {
  job_id: number;
  target_category_version: number;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "STALE";
  total_count: number;
  applied_count: number;
  skipped_count: number;
  failed_count: number;
  error: { code: string; message: string } | null;
  started_at: string | null;
  completed_at: string | null;
};

export async function getReclassificationJob(jobId: number, token: string, signal?: AbortSignal) {
  return fetchJson<ReclassificationJob>(`/reclassification-jobs/${jobId}`, { headers: authHeader(token), signal });
}

export async function retryReclassificationJob(jobId: number, token: string) {
  return fetchJson<ReclassificationJob>(`/reclassification-jobs/${jobId}/retry`, { method: "POST", headers: authHeader(token) });
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

// POST /reg/retrieve — 현재 지식 진입점. 채팅·검색 어디서든 이 계약을 통과한다.
export async function retrieve(storeSlug: string, question: string, topK = 5) {
  return fetchJson<RetrieveResponse>("/reg/retrieve", {
    method: "POST",
    body: JSON.stringify({ store_id: storeSlug, question, top_k: topK }),
  });
}

// ---- /ingest/* — docs/ASKBUDDY_MVP_CURRENT.md 업로드 계약 ----
// 실 배포 전까지는 로그인이 없어 Bearer 토큰이 비어 있을 수 있다.
// 그 경우 백엔드가 401을 돌려주고, 업로드 화면은 이를 잡아 로컬 진행률로 대체한다.

export type IngestSourceType = "VOICE" | "VIDEO" | "KAKAO" | "SCAN";

export type IngestJobStatus =
  | "QUEUED"
  | "EXTRACTING"
  | "CLASSIFYING"
  | "SUCCEEDED"
  | "PARTIAL"
  | "NO_RESULT"
  | "FAILED";

export type IngestJobListItem = {
  job_id: number;
  title: string | null;
  status: IngestJobStatus;
  category_version: number;
  source_count: number;
  card_count: number;
  created_at: string;
  completed_at: string | null;
};

export type IngestJobList = {
  items: IngestJobListItem[];
  next_cursor: number | null;
  total: number;
};

export type IngestJobDetail = {
  job_id: number;
  title: string | null;
  status: IngestJobStatus;
  category_version: number;
  counts: { sources: number; succeeded: number; failed: number; cards: number };
  sources: Array<{
    source_id: number;
    filename: string;
    status: string;
    card_count: number;
    error: { code: string; message: string } | null;
  }>;
  review_destination: string;
};

export function isIngestJobActive(status: IngestJobStatus) {
  return status === "QUEUED" || status === "EXTRACTING" || status === "CLASSIFYING";
}

export async function createIngestJob(
  sourceIds: number[],
  token: string,
  options: { title?: string; idempotencyKey?: string } = {}
) {
  return fetchJson<{
    job_id: number;
    status: IngestJobStatus;
    category_version: number;
    source_count: number;
  }>("/ingest/jobs", {
    method: "POST",
    headers: {
      ...authHeader(token),
      ...(options.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {}),
    },
    body: JSON.stringify({ source_ids: sourceIds, title: options.title }),
  });
}

export async function listIngestJobs(token: string, signal?: AbortSignal) {
  return fetchJson<IngestJobList>("/ingest/jobs?limit=50", {
    headers: authHeader(token),
    signal,
  });
}

export async function getIngestJob(jobId: number, token: string, signal?: AbortSignal) {
  return fetchJson<IngestJobDetail>(`/ingest/jobs/${jobId}`, {
    headers: authHeader(token),
    signal,
  });
}

export async function retryIngestJob(jobId: number, token: string) {
  return fetchJson<{ job_id: number; status: IngestJobStatus }>(
    `/ingest/jobs/${jobId}/retry`,
    { method: "POST", headers: authHeader(token) }
  );
}

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

// ---- /learn/chat — 신입 질문 한 방 (검색·저장·miss면 pending) ----
// store_id 는 JWT 에만 있다. 본문으로 매장을 보내지 않는다.

export type LearnChatCitation = {
  card_id: number;
  title: string;
  relevance: number;
};

export type LearnChatMessage = {
  message_id: number;
  sender_type: "USER" | "BUDDY";
  content: string;
  answer_type: "ANSWERED" | "NO_ANSWER" | null;
  created_at: string;
  citations: LearnChatCitation[];
};

export type LearnChatAskResponse = {
  session_id: number;
  user_message_id: number;
  buddy: {
    message_id: number;
    answer_type: "ANSWERED" | "NO_ANSWER";
    content: string;
    citations: LearnChatCitation[];
  };
  pending_question_id: number | null;
};

export async function askChat(question: string, token: string) {
  return fetchJson<LearnChatAskResponse>("/learn/chat", {
    method: "POST",
    headers: authHeader(token),
    body: JSON.stringify({ question }),
    timeoutMs: CHAT_TIMEOUT_MS,
  });
}

export async function listChat(token: string, signal?: AbortSignal) {
  return fetchJson<{ session_id: number | null; messages: LearnChatMessage[] }>("/learn/chat", {
    headers: authHeader(token),
    timeoutMs: CHAT_TIMEOUT_MS,
    signal,
  });
}

// ---- /learn/pending — 점주 대시보드 폴링 · 답변 (D6, 2초) ----

export type LearnPendingItem = {
  question_id: number;
  question_text: string;
  miss_reason: string;
  status: "WAITING" | "ANSWERED";
  member_id: number;
  asked_by: string;
  created_at: string;
};

export async function listPending(token: string, status: "WAITING" | "ANSWERED" = "WAITING", signal?: AbortSignal) {
  return fetchJson<{ store_id: number; status: string; items: LearnPendingItem[] }>(
    `/learn/pending?status=${status}`,
    { headers: authHeader(token), signal }
  );
}

export type LearnStaffItem = {
  member_id: number;
  name: string;
  day_count: number;
  progress_rate: number;
  is_deployable: boolean;
};

export async function listStaff(token: string, signal?: AbortSignal) {
  return fetchJson<{ store_id: number; deploy_threshold: number; items: LearnStaffItem[] }>(
    "/learn/staff",
    { headers: authHeader(token), signal }
  );
}

// ---- /learn/questions — 점주 전체 질문 최신순 (hit·점주답·대기) ----

export type LearnQuestionItem = {
  message_id: number;
  question_text: string;
  asked_by: string;
  member_id: number;
  status: "WAITING" | "HIT" | "OWNER_ANSWERED";
  answer_text: string | null;
  waiting_question_id: number | null;
  answered_at: string | null;
  created_at: string;
};

export async function listQuestions(token: string, signal?: AbortSignal) {
  return fetchJson<{ store_id: number; items: LearnQuestionItem[] }>("/learn/questions", {
    headers: authHeader(token),
    signal,
  });
}

export async function answerPending(questionId: number, answerText: string, token: string) {
  return fetchJson<{
    question_id: number;
    status: "ANSWERED";
    card_id: number;
    answer_text: string;
  }>(`/learn/pending/${questionId}/answer`, {
    method: "POST",
    headers: authHeader(token),
    body: JSON.stringify({ answer_text: answerText }),
    timeoutMs: CHAT_TIMEOUT_MS,
  });
}

export type KnowledgeProposal = {
  proposal_id: number;
  relation_type: "IDENTICAL" | "NEW" | "SUPPLEMENT" | "CONFLICT";
  status: "ANALYZED" | "LINKED" | "PENDING_REVIEW" | "PUBLISHED" | "FAILED" | "DISMISSED";
  question_text: string;
  answer_text: string;
  target_card_id: number | null;
  target_version_id: number | null;
  current_title: string | null;
  current_content: string | null;
  proposed_title: string | null;
  proposed_content: string | null;
  reason: string | null;
  category_id: number;
  created_at: string;
};

export async function listKnowledgeProposals(token: string, signal?: AbortSignal) {
  return fetchJson<{ store_id: number; status: string; items: KnowledgeProposal[] }>(
    "/learn/knowledge-proposals?status=PENDING_REVIEW",
    { headers: authHeader(token), signal }
  );
}

export async function resolveKnowledgeProposal(proposalId: number, action: "approve" | "dismiss", token: string) {
  return fetchJson<{ proposal_id: number; status: string; card_id?: number; version_id?: number }>(
    `/learn/knowledge-proposals/${proposalId}/${action}`,
    { method: "POST", headers: authHeader(token), timeoutMs: action === "approve" ? 30_000 : TIMEOUT_MS }
  );
}

export type FaqItem = {
  question: string;
  question_count: number;
  distinct_questioners: number;
  last_asked_at: string;
  card_id: number;
  published_version_id: number;
  card_title: string;
  card_content: string;
  category_id: number;
  category_name: string;
};

export async function listFaqs(token: string, signal?: AbortSignal) {
  return fetchJson<{ store_id: number; items: FaqItem[] }>("/learn/faqs?min_questions=2&limit=50", {
    headers: authHeader(token),
    signal,
  });
}

// ---- /notifications — 앱 내부 알림 정본 + 선택적 Web Push ----

export type NotificationSupport = {
  push_configured: boolean;
  vapid_public_key: string | null;
  guide_version: string;
  guide_seen: boolean;
};

export type NotificationItem = {
  notification_id: number;
  event_type: "INGEST_COMPLETED" | "PENDING_QUESTION";
  aggregate_type: "INGEST_JOB" | "PENDING_QUESTION";
  aggregate_id: number;
  title: string;
  body: string;
  destination: string;
  delivery_status: "PENDING" | "REQUESTED" | "FAILED";
  read_at: string | null;
  action_completed: boolean;
  created_at: string;
};

export async function getNotificationSupport(token: string, signal?: AbortSignal) {
  return fetchJson<NotificationSupport>("/notifications/support", {
    headers: authHeader(token),
    signal,
  });
}

export async function savePushSubscription(
  subscription: PushSubscriptionJSON,
  token: string
) {
  return fetchJson<{ subscription_id: number; enabled: boolean }>(
    "/notifications/subscriptions",
    {
      method: "POST",
      headers: authHeader(token),
      body: JSON.stringify(subscription),
    }
  );
}

export async function deletePushSubscription(subscriptionId: number, token: string) {
  return fetchJson<void>(`/notifications/subscriptions/${subscriptionId}`, {
    method: "DELETE",
    headers: authHeader(token),
  });
}

export async function listNotifications(
  token: string,
  opts: { unreadOnly?: boolean; cursor?: number; limit?: number } = {},
  signal?: AbortSignal
) {
  const query = new URLSearchParams();
  if (opts.unreadOnly) query.set("unread_only", "true");
  if (opts.cursor) query.set("cursor", String(opts.cursor));
  if (opts.limit) query.set("limit", String(opts.limit));
  return fetchJson<{
    items: NotificationItem[];
    unread_count: number;
    next_cursor: number | null;
  }>(`/notifications${query.toString() ? `?${query}` : ""}`, {
    headers: authHeader(token),
    signal,
  });
}

export async function markNotificationRead(notificationId: number, token: string) {
  return fetchJson<{ notification_id: number; read_at: string }>(
    `/notifications/${notificationId}/read`,
    { method: "POST", headers: authHeader(token) }
  );
}
