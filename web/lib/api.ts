// FastAPI 호출 래퍼. Supabase는 절대 직접 호출하지 않는다 (CLAUDE.md 불변식 1).
// 백엔드가 아직 배포되지 않았거나 응답이 없으면, 호출한 쪽에서 mock 데이터로 대체할 수 있도록
// 실패를 조용히 삼키지 않고 예외를 던진다 — 화면단에서 catch 해서 판단한다.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TIMEOUT_MS = 6000;

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
      throw new Error(`${path} 실패: ${res.status}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
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

function authHeader(token?: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
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
