"use client";

import { useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BuddyBubble, Shell, TopBar } from "@/components/ui";
import { OwnerPrimaryNav } from "@/components/owner-primary-nav";
import { useApp } from "@/lib/store";
import { UPLOAD_METHODS, type UploadSourceType } from "@/lib/types";
import {
  ApiError,
  computeContentHash,
  createIngestJob,
  isIngestJobActive,
  putToStorage,
  registerSource,
  requestUploadUrl,
  retryIngestJob,
} from "@/lib/api";
import { ingestJobsQuery, queryKeys } from "@/lib/query";

const SHEET_COPY: Record<UploadSourceType, string> = {
  VOICE: "이전에 녹음해둔 파일이 있다면 올려주세요. 지금 바로 녹음할 수도 있어요.",
  VIDEO: "촬영하면서 설명해주세요. 사전에 메모나 문서를 첨부하면 더 정확하게 분석해요. (선택 사항)",
  KAKAO: '카카오톡에서 "대화 내보내기"로 저장한 파일이나 대화 캡처 이미지를 올려주세요.',
  SCAN: "메뉴판, 매뉴얼 사진, PDF 파일을 올려주세요. AI가 텍스트를 읽어 분석해요.",
};

// 백엔드가 받는 확장자와 정확히 같아야 한다. 넓게 열면 파일 선택창에서는 고를 수 있는데
// /ingest/upload-url 이 422 로 거절한다 (aac·webp·avi·heic 등).
const ALLOWED_EXT: Record<UploadSourceType, string[]> = {
  VOICE: ["mp3", "m4a", "wav"],
  VIDEO: ["mp4", "mov"],
  KAKAO: ["txt", "zip", "png", "jpg", "jpeg"],
  SCAN: ["pdf", "png", "jpg", "jpeg"],
};

const ACCEPT: Record<UploadSourceType, string> = {
  VOICE: ".mp3,.m4a,.wav",
  VIDEO: ".mp4,.mov",
  KAKAO: ".txt,.zip,.png,.jpg,.jpeg",
  SCAN: ".pdf,.png,.jpg,.jpeg",
};

// 백엔드 enum 과 정확히 맞춰야 한다. 어긋나면 /ingest/sources 가 422 를 준다.
//   audio_format  mp3 | m4a | wav        (소문자)
//   video_format  mp4 | mov              (소문자)
//   import_type   TXT_EXPORT | SCREENSHOT
//   doc_type      PDF | JPG | PNG        (대문자)
function extOf(file: File): string {
  return file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "";
}

const DOC_TYPE: Record<string, "PDF" | "JPG" | "PNG"> = {
  pdf: "PDF",
  jpg: "JPG",
  jpeg: "JPG",
  png: "PNG",
};

function metaFor(type: UploadSourceType, file: File): Record<string, unknown> {
  const ext = extOf(file);
  switch (type) {
    case "VOICE":
      return { audio_format: ext, record_method: "UPLOAD" };
    case "VIDEO":
      return { video_format: ext };
    case "KAKAO":
      // 대화 캡처 이미지도 카톡 소스다 (source_kakao.import_type)
      return { import_type: ["png", "jpg", "jpeg"].includes(ext) ? "SCREENSHOT" : "TXT_EXPORT" };
    case "SCAN":
      return { doc_type: DOC_TYPE[ext] ?? "PDF", doc_category: "ETC" };
  }
}

export default function UploadPage() {
  const router = useRouter();
  // 등록 흐름 중이면 업종 선택으로, 대시보드에서 들어왔으면 대시보드로.
  // router.back() 은 직접 열거나 새로고침하면 갈 곳이 없어 아무 반응이 없다.
  const fromDashboard = useSearchParams().get("from") === "dashboard";
  const backHref = fromDashboard ? "/owner/dashboard" : "/owner/category";
  const { state } = useApp();
  const queryClient = useQueryClient();
  const jobsQuery = useQuery(ingestJobsQuery(state.token, state.storeId));
  const [busy, setBusy] = useState<UploadSourceType | null>(null);
  const [activeSheet, setActiveSheet] = useState<UploadSourceType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const retryJob = useMutation({
    mutationFn: (jobId: number) => retryIngestJob(jobId, state.token!),
    onSuccess: async () => {
      setError(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) });
    },
    onError: (retryError) => {
      setError(retryError instanceof ApiError ? retryError.detail || "재시도하지 못했어요" : "서버에 연결할 수 없습니다.");
    },
  });
  const jobs = jobsQuery.data?.items ?? [];
  const activeJobs = jobs.filter((job) => isIngestJobActive(job.status));
  const completedJobs = jobs.filter((job) => job.status === "SUCCEEDED" || job.status === "PARTIAL");
  const cardCount = completedJobs.reduce((sum, job) => sum + job.card_count, 0);
  const hasAny = cardCount > 0;
  const visibleError = error ?? (jobsQuery.error instanceof ApiError
    ? jobsQuery.error.detail || "처리 작업을 불러오지 못했어요"
    : jobsQuery.error
      ? "서버에 연결할 수 없습니다."
      : null);

  async function handleFile(type: UploadSourceType, file: File) {
    // 허용 목록 밖이면 서버에 보내지 않고 여기서 막는다.
    // 보내면 /ingest/upload-url 이 422 를 주는데, 그 사이 화면은 "처리 중" 으로 보인다.
    const ext = extOf(file);
    if (!ALLOWED_EXT[type].includes(ext)) {
      setError(`${ext ? `.${ext}` : "이 파일"} 형식은 안 돼요 — ${ALLOWED_EXT[type]
        .map((e) => `.${e}`)
        .join(", ")} 만 올릴 수 있어요`);
      return;
    }

    if (!state.token) {
      setError("로그인 정보가 없습니다. 다시 로그인해주세요.");
      return;
    }
    setBusy(type);
    setError(null);

    try {
      const token = state.token;
      const { upload_url, file_url } = await requestUploadUrl(type, file.name, token);
      await putToStorage(upload_url, file);
      const contentHash = await computeContentHash(file);
      const { source_id, duplicate } = await registerSource(
        {
          sourceType: type,
          fileUrl: file_url,
          title: file.name,
          fileSize: file.size,
          contentHash,
          meta: metaFor(type, file),
        },
        token
      );
      if (duplicate) {
        setError("이미 등록된 파일이에요. 기존 처리 결과를 확인해주세요.");
        await queryClient.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) });
        return;
      }
      await createIngestJob([source_id], token, {
        title: file.name,
        idempotencyKey: crypto.randomUUID(),
      });
      await queryClient.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) });
      setActiveSheet(null);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 422
            ? "이 파일 형식은 아직 지원하지 않아요"
            : err.detail || `등록 실패 (${err.status})`
          : "서버에 연결할 수 없습니다. 처리 완료로 표시하지 않았어요."
      );
    } finally {
      setBusy(null);
    }
  }

  const buddyMsg = activeJobs.length > 0
    ? `${activeJobs.length}개 작업을 처리하고 있어요. 다른 화면으로 이동해도 괜찮아요.`
    : hasAny
      ? `현재 검토할 카드가 ${cardCount}개 있어요.`
      : "어떤 방법으로 알려주실 건가요? 하나만 골라도 괜찮아요 😊";

  return (
    <Shell>
      <TopBar title="자료 업로드" backHref={backHref} />

      <div className="px-4 pb-3"><OwnerPrimaryNav /></div>

      <div className="px-4 pt-1 pb-3 shrink-0">
        <div className="mb-3 grid grid-cols-3 gap-2">
          <div className="rounded-xl bg-surface-muted px-3 py-2 text-center"><p className="text-base font-bold text-brand-700">{jobs.length}</p><p className="text-[10px] text-muted">전체 작업</p></div>
          <div className="rounded-xl bg-surface-muted px-3 py-2 text-center"><p className="text-base font-bold text-brand-500">{activeJobs.length}</p><p className="text-[10px] text-muted">처리 중</p></div>
          <div className="rounded-xl bg-surface-muted px-3 py-2 text-center"><p className="text-base font-bold text-brand-700">{cardCount}</p><p className="text-[10px] text-muted">생성 카드</p></div>
        </div>
        <div className={`rounded-2xl px-3 py-2.5 ${hasAny ? "bg-brand-50" : "bg-accent-50"}`}>
          <BuddyBubble text={buddyMsg} size={30} />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-4">
        <p className="text-xs text-muted mb-3">원하는 방법으로 자료를 올려주세요. 여러 개 조합도 가능해요.</p>
        {visibleError && <p className="mb-3 rounded-xl bg-danger-50 px-3 py-2 text-xs font-medium text-danger-500">{visibleError}</p>}
        <div className="space-y-2.5">
          {UPLOAD_METHODS.map((m) => {
            const processing = busy === m.type;
            return (
              <button
                key={m.type}
                onClick={() => setActiveSheet(m.type)}
                className={`w-full h-[76px] flex items-center gap-3 px-4 rounded-xl border transition-all active:scale-[0.98] ${
                  processing ? "border-brand-500 bg-brand-50/40" : "border-border bg-surface"
                }`}
              >
                <div
                  className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-xl ${
                    processing ? "bg-brand-100" : "bg-surface-muted"
                  }`}
                >
                  {m.icon}
                </div>
                <div className="flex-1 min-w-0 text-left">
                  <p className="text-sm font-bold leading-tight">{m.label}</p>
                  <p className="text-xs text-muted mt-0.5 truncate">
                    {m.type === "VOICE"
                        ? "녹음 파일 업로드 또는 바로 녹음"
                        : m.type === "VIDEO"
                          ? "촬영하면서 업무를 설명해주세요"
                          : m.type === "KAKAO"
                            ? "대화 파일(.txt) 또는 캡처 이미지 업로드"
                            : "PDF, 메뉴판 사진, 문서 이미지 업로드"}
                  </p>
                </div>
                {processing ? (
                  <span className="text-muted text-xs shrink-0">업로드 중…</span>
                ) : (
                  <span className="text-muted shrink-0">→</span>
                )}
              </button>
            );
          })}
        </div>

        {jobsQuery.isLoading && <div className="mt-5 h-24 animate-pulse rounded-2xl bg-surface-muted" aria-label="처리 작업 불러오는 중" />}
        {jobs.length > 0 && (
          <div className="mt-5 bg-surface rounded-2xl px-4 py-3 shadow-sm">
            <p className="text-xs font-bold text-brand-700 mb-2">처리 작업</p>
            {jobsQuery.isFetching && !jobsQuery.isLoading && <p className="mb-2 text-[11px] text-muted">최신 상태 확인 중…</p>}
            <div className="space-y-2">
              {jobs.slice(0, 8).map((job) => (
                <div key={job.job_id} className="flex items-center justify-between gap-3 rounded-xl bg-background px-3 py-2">
                  <Link href={`/owner/jobs/${job.job_id}`} className="flex min-h-11 min-w-0 flex-1 items-center truncate text-xs font-semibold text-brand-700">{job.title ?? `작업 #${job.job_id}`}</Link>
                  {job.status === "FAILED" || job.status === "NO_RESULT" ? (
                    <button
                      type="button"
                      disabled={retryJob.isPending}
                      onClick={() => retryJob.mutate(job.job_id)}
                      className="shrink-0 text-xs font-bold text-danger-500 disabled:opacity-50"
                    >
                      {retryJob.isPending && retryJob.variables === job.job_id ? "재시도 중" : "재시도"}
                    </button>
                  ) : (
                    <span className={`shrink-0 text-xs font-bold ${isIngestJobActive(job.status) ? "text-brand-500" : "text-brand-700"}`}>
                      {isIngestJobActive(job.status) ? "처리 중" : job.status === "SUCCEEDED" ? `${job.card_count}개 완료` : `${job.card_count}개 일부 완료`}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="px-4 pb-8 pt-4 bg-gradient-to-t from-background via-background to-transparent">
        <button
          disabled={!hasAny}
          onClick={() => router.push("/owner/cards?status=pending")}
          className="w-full py-4 rounded-2xl font-bold text-lg transition-all active:scale-95 disabled:cursor-not-allowed"
          style={{
            background: !hasAny ? "var(--border)" : "var(--brand-500)",
            color: !hasAny ? "var(--foreground)" : "white",
            boxShadow: !hasAny ? "none" : "0 6px 20px rgba(91,191,106,0.38)",
          }}
        >
          {!hasAny ? "완료된 카드가 아직 없어요" : "카드 검토하기 →"}
        </button>
      </div>

      {/* 숨겨진 파일 입력 — 방식별로 하나씩, 바텀시트 버튼이 이걸 클릭시킨다 */}
      {UPLOAD_METHODS.map((m) => (
        <input
          key={m.type}
          ref={(el) => {
            inputRefs.current[m.type] = el;
          }}
          type="file"
          accept={ACCEPT[m.type]}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) void handleFile(m.type, file);
          }}
        />
      ))}

      {activeSheet && (
        <UploadSheet
          type={activeSheet}
          status={undefined}
          loading={busy === activeSheet}
          onTriggerFile={() => inputRefs.current[activeSheet]?.click()}
          onClose={() => setActiveSheet(null)}
        />
      )}
    </Shell>
  );
}

function Spinner({ className = "" }: { className?: string }) {
  return (
    <div
      className={`border-4 border-brand-500 border-t-transparent rounded-full animate-spin ${className}`}
    />
  );
}

function UploadSheet({
  type,
  status,
  loading,
  onTriggerFile,
  onClose,
}: {
  type: UploadSourceType;
  status: "UPLOADED" | "PROCESSING" | "DONE" | "FAILED" | undefined;
  loading: boolean;
  onTriggerFile: () => void;
  onClose: () => void;
}) {
  const method = UPLOAD_METHODS.find((m) => m.type === type)!;
  const done = status === "DONE";
  const [recording, setRecording] = useState(false);
  const [attachDoc, setAttachDoc] = useState(false);

  return (
    <div className="absolute inset-0 z-40">
      <button aria-label="닫기" onClick={onClose} className="absolute inset-0 bg-black/22" />
      <div
        className="absolute bottom-0 left-0 right-0 bg-surface rounded-t-3xl shadow-2xl max-h-[70%] overflow-y-auto animate-[slideUp_0.25s_ease-out]"
        style={{ animationFillMode: "backwards" }}
      >
        <div className="p-5">
          <div className="w-12 h-1 bg-border rounded-full mx-auto mb-5" />
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <span className="text-xl">{method.icon}</span>
              <div>
                <h3 className="font-bold text-brand-700">{method.label}</h3>
                {done && <p className="text-xs font-semibold text-brand-500">✓ 등록됨</p>}
                {status === "FAILED" && <p className="text-xs font-semibold text-danger-500">등록 실패 — 다시 시도해주세요</p>}
              </div>
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 flex items-center justify-center rounded-full bg-background text-muted font-bold text-sm"
            >
              ✕
            </button>
          </div>

          <p className="text-sm text-foreground/70 leading-relaxed mb-3">{SHEET_COPY[type]}</p>

          {type === "VOICE" && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={onTriggerFile}
                  disabled={loading}
                  className="flex flex-col items-center gap-2 py-5 rounded-2xl border-2 bg-surface active:scale-95 transition-all"
                  style={{ borderColor: done ? "var(--brand-500)" : "var(--border)" }}
                >
                  {loading ? <Spinner className="w-6 h-6" /> : <span className="text-2xl">{done ? "✅" : "📂"}</span>}
                  <span className="text-xs font-bold">파일 업로드</span>
                  <span className="text-[10px] text-muted">mp3, m4a, wav</span>
                </button>
                <button
                  onClick={() => setRecording((r) => !r)}
                  disabled={done}
                  className={`flex flex-col items-center gap-2 py-5 rounded-2xl border-2 transition-all active:scale-95 ${
                    recording ? "border-danger-500 bg-danger-50" : "border-border bg-surface"
                  }`}
                >
                  <span className="text-2xl">{recording ? "⏹️" : "⏺️"}</span>
                  <span className="text-xs font-bold">{recording ? "녹음 중지" : "지금 녹음하기"}</span>
                  {recording && <span className="text-[10px] font-semibold text-danger-500 animate-pulse">● REC</span>}
                </button>
              </div>
              {recording && (
                <div className="flex items-center gap-2 bg-danger-50 border border-danger-500/20 rounded-xl px-4 py-3">
                  <span className="text-danger-500 animate-pulse font-bold">●</span>
                  <span className="text-xs font-semibold">녹음 중… 완료하려면 &quot;녹음 중지&quot;를 눌러주세요</span>
                </div>
              )}
            </div>
          )}

          {type === "VIDEO" && (
            <div className="space-y-3">
              <button
                onClick={() => setAttachDoc((v) => !v)}
                className="w-full flex items-center justify-between bg-surface border-2 rounded-2xl px-4 py-3 transition-all"
                style={{ borderColor: attachDoc ? "var(--brand-500)" : "var(--border)" }}
              >
                <div className="flex items-center gap-2">
                  <span>📎</span>
                  <div className="text-left">
                    <p className="text-sm font-bold">사전 문서 첨부</p>
                    <p className="text-[11px] text-muted">레시피, 메모 등 (선택)</p>
                  </div>
                </div>
                <span
                  className="w-10 h-5 rounded-full relative shrink-0 transition-colors"
                  style={{ background: attachDoc ? "var(--brand-500)" : "var(--border)" }}
                >
                  <span
                    className="absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform"
                    style={{ left: attachDoc ? "22px" : "2px" }}
                  />
                </span>
              </button>
              <button
                onClick={onTriggerFile}
                disabled={loading}
                className="w-full flex items-center justify-center gap-3 rounded-2xl py-5 border-2 transition-all active:scale-95"
                style={{
                  background: done ? "var(--brand-50)" : "var(--brand-700)",
                  borderColor: done ? "var(--brand-500)" : "var(--brand-700)",
                }}
              >
                {loading ? (
                  <Spinner className="w-6 h-6 !border-white" />
                ) : done ? (
                  <>
                    <span className="text-xl">✅</span>
                    <span className="text-sm font-bold text-brand-500">업로드 완료</span>
                  </>
                ) : (
                  <>
                    <span className="text-2xl">🎥</span>
                    <span className="text-sm font-bold text-white">영상 올리기 (mp4, mov)</span>
                  </>
                )}
              </button>
            </div>
          )}

          {type === "KAKAO" && (
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "대화 파일(.txt)", sub: "내보내기 파일", icon: "📁" },
                { label: "대화 캡처", sub: "스크린샷 이미지", icon: "🖼️" },
              ].map((btn) => (
                <button
                  key={btn.label}
                  onClick={onTriggerFile}
                  disabled={loading}
                  className="flex flex-col items-center gap-2 py-5 rounded-2xl border-2 bg-surface active:scale-95 transition-all"
                  style={{ borderColor: done ? "var(--brand-500)" : "var(--border)" }}
                >
                  {loading ? <Spinner className="w-6 h-6" /> : <span className="text-2xl">{done ? "✅" : btn.icon}</span>}
                  <span className="text-xs font-bold">{btn.label}</span>
                  <span className="text-[10px] text-muted">{btn.sub}</span>
                </button>
              ))}
            </div>
          )}

          {type === "SCAN" && (
            <button
              onClick={onTriggerFile}
              disabled={loading}
              className="w-full flex flex-col items-center gap-3 py-8 rounded-2xl border-2 bg-surface active:scale-95 transition-all"
              style={{ borderColor: done ? "var(--brand-500)" : "var(--border)", borderStyle: done ? "solid" : "dashed" }}
            >
              {loading ? (
                <Spinner className="w-8 h-8" />
              ) : done ? (
                <>
                  <span className="text-3xl">✅</span>
                  <span className="text-sm font-bold text-brand-500">업로드 완료</span>
                </>
              ) : (
                <>
                  <span className="text-3xl">📄</span>
                  <span className="text-sm font-bold">파일 선택 또는 드래그</span>
                  <span className="text-xs text-muted">PDF, JPG, PNG 지원</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
