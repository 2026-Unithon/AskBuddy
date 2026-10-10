// FastAPI 호출 래퍼. Supabase는 절대 직접 호출하지 않는다 (CLAUDE.md 불변식 1).
// 실패를 조용히 삼키지 않고 종류와 복구 가능 여부를 보존해 올린다.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 6000;
const CHAT_TIMEOUT_MS = 20000;

function authHeader(token?: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// sessionExpiry=false: 운영자 호출의 401 이 같은 탭의 제품 로그인을 끊지 않게 한다
type FetchJsonInit = RequestInit & { timeoutMs?: number; sessionExpiry?: boolean };

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

async function fetchJsonOnce<T>(path: string, init?: FetchJsonInit): Promise<T> {
  const { timeoutMs = TIMEOUT_MS, sessionExpiry: _sessionExpiry, ...fetchInit } = init ?? {};
  void _sessionExpiry;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const clientRequestId = requestId();
  const signal = fetchInit.signal
    ? AbortSignal.any([fetchInit.signal, controller.signal])
    : controller.signal;
  try {
    const res = await fetch(`${BASE}${path}`, {
      credentials: "include",
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

// /preflight 는 운영자 전용이다. 운영자 토큰은 제품 세션과 따로 다룬다.
export async function getPreflight(deep: boolean, token: string, signal?: AbortSignal) {
  return fetchJson<PreflightReport>(`/preflight${deep ? "?deep=1" : ""}`, {
    cache: "no-store",
    timeoutMs: deep ? 60_000 : TIMEOUT_MS,
    signal,
    headers: authHeader(token),
    sessionExpiry: false,
  });
}

export type OperatorLogin = {
  token: string;
  operator: { user_id: number; name: string; email: string };
};

export async function opsLogin(email: string, password: string) {
  return fetchJson<OperatorLogin>("/ops/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    sessionExpiry: false,
  });
}

// ---- /auth/* — 로그인·가입·초대코드 합류 ----
// store_id 는 토큰 안에만 있다. 요청 본문으로 매장을 지정하지 않는다 (CLAUDE.md 불변식 4).

export type AuthUser = {
  user_id: number;
  name: string;
  email?: string;
  role: "OWNER" | "STAFF" | null;
  // 매장을 만들기 전 점주에게는 이 필드가 아예 없다. null 이 아니라 누락이다.
  store_id?: number | null;
};

export type AuthResponse = { token: string; user: AuthUser };

export type BootstrapResponse = {
  user: {
    user_id: number;
    role: "OWNER" | "STAFF" | null;
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

export async function login(email: string, password: string, role?: "OWNER" | "STAFF") {
  return fetchJson<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password, role }),
  });
}

export async function signup(params: {
  name: string;
  email: string;
  password: string;
  role?: "OWNER" | "STAFF";
  phone?: string;
}) {
  return fetchJson<AuthResponse>("/auth/signup", {
    method: "POST",
    body: JSON.stringify(params),
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

export type SourceAvailability = "AVAILABLE" | "DELETED" | "UNAVAILABLE";

export type CardSourceDto = {
  source_id: number;
  title: string | null;
  source_type: string | null;
  read_url: string | null;
  // 자료가 삭제되면 원본을 열 수 없다. 근거는 '인용 끊김'으로 표시한다
  source_availability?: SourceAvailability;
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
  // W3b: 초안 판에 블록 사실이 있으면 사실 카드. 편집 플래그는 서버 설정 그대로
  fact_card: boolean;
  fact_edit_enabled: boolean;
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

// ---- /cards/{id}/facts — W3b 사실 카드 편집 (api/app/cards/fact_edit_schemas.py 와 같은 모양) ----

export type FactPolarity = "AFFIRM" | "NEGATE";
export type EditBlockKind = "QUANTITIES" | "STEPS" | "NOTES";

export type FactVariant = { temperature: "HOT" | "ICE" | null; size: string | null };

export type FactFields = {
  sentence: string;
  polarity: FactPolarity;
  value: string | null;
  unit: string | null;
  conditions: string[];
  exceptions: string[];
  step_order: number | null;
  variant: FactVariant;
  predicate: string | null;
};

export type EditItem =
  | { op: "KEEP"; fact_revision_id: number }
  | { op: "MODIFY"; fact_revision_id: number; fact: FactFields }
  | { op: "ADD"; client_ref: string; fact: FactFields };

export type EditBlock = { kind: EditBlockKind; items: EditItem[] };

export type FactEditRequest = {
  expected_version_id: number;
  idempotency_key: string;
  blocks: EditBlock[];
  deleted_fact_revision_ids: number[];
};

export type FactParseRequest = {
  text: string;
  mode: "ADD" | "MODIFY";
  base_fact_revision_id: number | null;
};

export type ParsedFactProposal = {
  client_ref: string;
  fact: FactFields;
  block_kind: EditBlockKind;
  warnings: string[];
};

export type FactParseResponse = {
  mode: "ADD" | "MODIFY";
  proposals: ParsedFactProposal[];
  warnings: string[];
};

export type FactOrigin = {
  kind: "SOURCE" | "OWNER_ANSWER" | "OWNER_TEXT";
  source_id: number | null;
  source_title: string | null;
  source_type: string | null;
  source_availability: "AVAILABLE" | "DELETED" | "UNAVAILABLE" | null;
  locator_type: string | null;
  locator: Record<string, unknown>;
  owner_answer_id: number | null;
  created_at: string | null;
};

export type FactRequirement = { fact_id: number; label: string };

export type FactRow = {
  fact_revision_id: number;
  fact_id: number;
  position: number;
  sentence: string;
  assertion: string;
  subject: string | null;
  predicate: string | null;
  variant: FactVariant;
  value: string | null;
  unit: string | null;
  polarity: FactPolarity;
  step_order: number | null;
  conditions: string[];
  exceptions: string[];
  requires: FactRequirement[];
  change_kind: string | null;
  previous_sentence: string | null;
  origins: FactOrigin[];
  edit_block: "CHANGED_ELSEWHERE" | "MOVED_ENTITY" | null;
};

export type FactBlockView = {
  block_id: string;
  kind: EditBlockKind | "RAW";
  order: number;
  variant: FactVariant;
  facts: FactRow[];
};

export type CardFactsView = {
  card_id: number;
  version_id: number;
  title: string;
  entity_id: number | null;
  entity_name: string | null;
  review_status: CardReviewStatus;
  published_version_id: number | null;
  editable: boolean;
  entity_problem: "MIXED_ENTITY" | "MERGED_ENTITY" | null;
  blocks: FactBlockView[];
};

export type FactRevisionResult = {
  op: "MODIFY" | "ADD";
  client_ref: string | null;
  base_fact_revision_id: number | null;
  fact_revision_id: number;
};

export type FactEditResult = CardMutationResult & {
  changed: boolean;
  edit_id: number;
  revisions: FactRevisionResult[];
};

export async function getCardFacts(cardId: number, token: string, signal?: AbortSignal) {
  return fetchJson<CardFactsView>(`/cards/${cardId}/facts`, { headers: authHeader(token), signal });
}

// 분석은 모델을 부르므로 길게 기다린다. 상태를 남기지 않는다
export async function parseCardFacts(cardId: number, body: FactParseRequest, token: string) {
  return fetchJson<FactParseResponse>(`/cards/${cardId}/facts/parse`, {
    method: "POST",
    headers: authHeader(token),
    body: JSON.stringify(body),
    timeoutMs: 20_000,
  });
}

// 같은 idempotency_key 로 다시 보내면 서버가 처음 결과를 그대로 돌려준다
export async function saveCardFacts(cardId: number, body: FactEditRequest, token: string) {
  return fetchJson<FactEditResult>(`/cards/${cardId}/facts`, {
    method: "PUT",
    headers: authHeader(token),
    body: JSON.stringify(body),
    timeoutMs: 15_000,
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
  counts: { sources: number; succeeded: number; failed: number; partial: number; cards: number };
  sources: Array<{
    source_id: number;
    filename: string;
    status: string;
    card_count: number;
    error: { code: string; message: string } | null;
    source_availability?: SourceAvailability;
  }>;
  review_destination: string;
};

export function isIngestJobActive(status: IngestJobStatus) {
  return status === "QUEUED" || status === "EXTRACTING" || status === "CLASSIFYING";
}

// 지원 형식·제한의 단일 출처 (MVP §10-1). 병렬 작업이 TEXT 를 추가하면 여기에 그대로 나타난다
export type IngestCapability = { extensions: string[]; max_bytes?: number; max_duration_sec?: number; max_pages?: number; max_chars?: number };
export type IngestCapabilities = Partial<Record<IngestSourceType | "TEXT", IngestCapability>>;

export async function getIngestCapabilities(token: string, signal?: AbortSignal) {
  return fetchJson<IngestCapabilities>("/ingest/capabilities", { headers: authHeader(token), signal });
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

// 자료 삭제: 원본 접근만 해제한다. 사실·카드·답변 근거는 남고 '인용 끊김'으로 표시된다
export async function deleteIngestSource(sourceId: number, token: string) {
  return fetchJson<{
    source_id: number;
    source_availability: "DELETED";
    deleted_at: string;
    already_deleted: boolean;
  }>(`/ingest/sources/${sourceId}`, { method: "DELETE", headers: authHeader(token) });
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
  event_type: "INGEST_COMPLETED" | "PENDING_QUESTION" | "OWNER_ANSWER" | "JOIN_REQUESTED" | "JOIN_APPROVED";
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

export type SessionResponse = AuthResponse;
let renewing: Promise<SessionResponse> | null = null;
const renewListeners = new Set<(s: SessionResponse) => void>();

export function onSessionRenewed(listener: (s: SessionResponse) => void): () => void {
  renewListeners.add(listener);
  return () => { renewListeners.delete(listener); };
}

async function postRefresh(): Promise<SessionResponse> {
  return fetchJsonOnce<SessionResponse>("/auth/refresh", { method: "POST", sessionExpiry: false });
}

// 여러 요청이 동시에 401 을 받아도 갱신은 한 번만 한다.
// 다른 탭이 방금 회전했다면 첫 시도가 401 이다 — 쿠키는 탭끼리 공유하므로 잠시 뒤 한 번 더 시도한다.
export function refreshSession(): Promise<SessionResponse> {
  if (!renewing) {
    renewing = (async () => {
      try {
        return await postRefresh();
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          await new Promise((r) => setTimeout(r, 300));
          return await postRefresh();
        }
        throw error;
      }
    })()
      .then((session) => {
        renewListeners.forEach((l) => l(session));
        return session;
      })
      .finally(() => { renewing = null; });
  }
  return renewing;
}

export async function fetchJson<T>(path: string, init?: FetchJsonInit): Promise<T> {
  try {
    return await fetchJsonOnce<T>(path, init);
  } catch (error) {
    const headers = new Headers(init?.headers);
    const canRenew = (init?.sessionExpiry ?? true) && headers.has("Authorization");
    if (!(error instanceof ApiError) || error.status !== 401 || !canRenew) throw error;
    let session: SessionResponse;
    try {
      session = await refreshSession();
    } catch (refreshError) {
      if (refreshError instanceof ApiError && refreshError.status === 401) emitSessionExpired(path);
      throw refreshError;
    }
    headers.set("Authorization", `Bearer ${session.token}`);
    return fetchJsonOnce<T>(path, { ...init, headers: Object.fromEntries(headers.entries()) });
  }
}

export async function logoutSession(): Promise<void> {
  await fetchJsonOnce<void>("/auth/logout", { method: "POST", sessionExpiry: false });
}

// api.ts
export type JoinStatus = {
  status: "PENDING" | "REJECTED" | "APPROVED" | "REMOVED" | "NONE";
  store_name: string | null;
};

export async function getJoinStatus(token: string, signal?: AbortSignal) {
  return fetchJson<JoinStatus>("/auth/join-status", { headers: authHeader(token), signal, cache: "no-store" });
}

export async function getPushKey(token: string, signal?: AbortSignal) {
  return fetchJson<{ push_configured: boolean; vapid_public_key: string | null }>(
    "/notifications/push-key", { headers: authHeader(token), signal });
}

export async function saveMyPushSubscription(subscription: PushSubscriptionJSON, token: string) {
  return fetchJson<{ subscription_id: number; enabled: boolean }>("/notifications/my-subscriptions", {
    method: "POST", headers: authHeader(token), body: JSON.stringify(subscription),
  });
}

export function kakaoStartUrl(p: { intent: "LOGIN" | "STAFF_JOIN"; invite?: string; next?: string | null }) {
  const q = new URLSearchParams({ intent: p.intent });
  if (p.invite) q.set("invite", p.invite);
  if (p.next) q.set("next", p.next);
  return `${BASE}/auth/kakao/start?${q.toString()}`;
}

export async function getProviders(signal?: AbortSignal) {
  return fetchJson<{ kakao: boolean }>("/auth/providers", { signal });
}

export async function getInvitePreview(token: string, signal?: AbortSignal) {
  return fetchJson<{ store_name: string }>(`/auth/invites/${encodeURIComponent(token)}`, { signal });
}

export async function requestJoin(inviteToken: string, token: string) {
  return fetchJson<{ status: "PENDING" | "ALREADY_MEMBER"; store_name: string }>("/auth/join-requests", {
    method: "POST", headers: authHeader(token), body: JSON.stringify({ invite_token: inviteToken }),
  });
}

// MVP §28 문구 사전과 같은 문구
export const AUTH_ERROR_COPY: Record<string, string> = {
  KAKAO_CANCELLED: "카카오 로그인을 취소했어요.",
  KAKAO_FAILED: "카카오 로그인에 실패했어요. 잠시 후 다시 시도해 주세요.",
  OAUTH_STATE_INVALID: "로그인 시간이 지났어요. 처음부터 다시 시도해 주세요.",
  ROLE_CONFLICT: "이 계정은 다른 역할로 가입되어 있어요.",
  INVITE_INVALID: "더 이상 쓸 수 없는 초대 링크예요. 사장님께 새 링크를 받아 주세요.",
  ALREADY_IN_OTHER_STORE: "이미 다른 매장에 합류한 계정이에요.",
  KAKAO_NOT_CONFIGURED: "지금은 카카오 로그인을 쓸 수 없어요. 이메일로 계속해 주세요.",
};

export type MembersResponse = {
  pending: { request_id: number; name: string; requested_at: string }[];
  active: { user_id: number; name: string; role: "OWNER" | "STAFF"; joined_at: string }[];
};

export async function getInviteLink(token: string, signal?: AbortSignal) {
  return fetchJson<{ url: string }>("/members/invite-link", { headers: authHeader(token), signal });
}
export async function rotateInviteLink(token: string) {
  return fetchJson<{ url: string }>("/members/invite-link/rotate", { method: "POST", headers: authHeader(token) });
}
export async function listMembers(token: string, signal?: AbortSignal) {
  return fetchJson<MembersResponse>("/members", { headers: authHeader(token), signal });
}
export async function approveJoin(requestId: number, token: string) {
  return fetchJson<void>(`/members/requests/${requestId}/approve`, { method: "POST", headers: authHeader(token) });
}
export async function rejectJoin(requestId: number, token: string) {
  return fetchJson<void>(`/members/requests/${requestId}/reject`, { method: "POST", headers: authHeader(token) });
}
export async function removeMember(userId: number, token: string) {
  return fetchJson<void>(`/members/${userId}/remove`, { method: "POST", headers: authHeader(token) });
}

export function chooseRole(role: "OWNER" | "STAFF", token: string) {
  return fetchJson<SessionResponse>("/auth/role", { method: "POST", headers: authHeader(token), body: JSON.stringify({ role }) });
}
