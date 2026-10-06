import {
  ApiError,
  apiErrorMessage,
  computeContentHash,
  createIngestJob,
  putToStorage,
  registerSource,
  requestUploadUrl,
  type IngestCapabilities,
  type IngestSourceType,
} from "@/lib/api";

// 리브랜딩 입력창(O3·O6)의 "넣기" 한 번 = 자료 여러 개 등록 + 작업 하나 접수.
// 서버가 202 job_id 를 돌려주면 끝이다. 추출 완료는 작업 화면이 서버 상태로 본다 (MVP §10-1).

export type PickedFile = { id: string; file: File; sourceType: IngestSourceType };
export type SourceFailure = { name: string; message: string };
export type IngestSubmitResult = { jobId: number | null; failures: SourceFailure[] };

const extensionOf = (name: string) => (name.includes(".") ? name.split(".").pop()!.toLowerCase() : "");

// 확장자 → 자료 유형. 이미지는 문서 사진(SCAN)으로 본다 — 카톡 캡처도 SCAN 이 읽는다.
const PREFERRED_TYPE: IngestSourceType[] = ["SCAN", "VOICE", "VIDEO", "KAKAO"];

export function sourceTypeFor(file: File, caps: IngestCapabilities | undefined): IngestSourceType | null {
  const ext = extensionOf(file.name);
  if (!caps) return null;
  return PREFERRED_TYPE.find((type) => caps[type]?.extensions.includes(ext)) ?? null;
}

export function acceptAttribute(caps: IngestCapabilities | undefined): string {
  if (!caps) return "";
  const exts = new Set(PREFERRED_TYPE.flatMap((type) => caps[type]?.extensions ?? []));
  return [...exts].map((ext) => `.${ext}`).join(",");
}

/** 붙여 넣은 글을 받을 수 있는가. 병렬 작업이 TEXT 유형을 추가하면 켜진다 (계획 §8 F1). */
export function supportsText(caps: IngestCapabilities | undefined): boolean {
  return Boolean(caps?.TEXT);
}

export function tooLargeMessage(file: File, type: IngestSourceType, caps: IngestCapabilities | undefined): string | null {
  const max = caps?.[type]?.max_bytes;
  if (!max || file.size <= max) return null;
  return `'${file.name}'은(는) ${Math.floor(max / 1024 / 1024)}MB보다 커서 올릴 수 없어요.`;
}

async function registerOne(file: File, sourceType: IngestSourceType | "TEXT", token: string) {
  // TEXT 는 병렬 작업의 계약이 오면 이 경로(서명 URL로 .txt 업로드)가 맞는지 다시 확인한다
  const type = sourceType as IngestSourceType;
  const { upload_url, file_url } = await requestUploadUrl(type, file.name, token);
  await putToStorage(upload_url, file);
  const contentHash = await computeContentHash(file);
  return registerSource(
    { sourceType: type, fileUrl: file_url, title: file.name, fileSize: file.size, contentHash, meta: metaFor(sourceType, file) },
    token
  );
}

function metaFor(type: IngestSourceType | "TEXT", file: File): Record<string, unknown> {
  const ext = extensionOf(file.name);
  switch (type) {
    case "VOICE":
      return { audio_format: ext, record_method: "UPLOAD" };
    case "VIDEO":
      return { video_format: ext };
    case "KAKAO":
      return { import_type: ext === "txt" ? "TXT_EXPORT" : "SCREENSHOT" };
    case "SCAN":
      return { doc_type: ext === "jpeg" ? "JPG" : ext.toUpperCase() };
    case "TEXT":
      return {};
  }
}

export async function submitIngest({
  files,
  text,
  token,
  idempotencyKey,
}: {
  files: PickedFile[];
  text: string;
  token: string;
  idempotencyKey: string;
}): Promise<IngestSubmitResult> {
  const sourceIds: number[] = [];
  const failures: SourceFailure[] = [];
  const items: { name: string; file: File; type: IngestSourceType | "TEXT" }[] = files.map((f) => ({
    name: f.file.name,
    file: f.file,
    type: f.sourceType,
  }));
  if (text.trim()) {
    items.push({ name: "붙여 넣은 글", file: new File([text], "붙여넣은글.txt", { type: "text/plain" }), type: "TEXT" });
  }

  for (const item of items) {
    try {
      const { source_id, duplicate } = await registerOne(item.file, item.type, token);
      if (duplicate) failures.push({ name: item.name, message: "이미 올린 자료예요. 기존 결과를 확인해 주세요." });
      else sourceIds.push(source_id);
    } catch (error) {
      failures.push({
        name: item.name,
        message: error instanceof ApiError ? apiErrorMessage(error, "전송이 완료되지 않았어요.") : "전송이 완료되지 않았어요. 다시 올려주세요.",
      });
    }
  }

  if (sourceIds.length === 0) return { jobId: null, failures };
  const job = await createIngestJob(sourceIds, token, { idempotencyKey });
  return { jobId: job.job_id, failures };
}
