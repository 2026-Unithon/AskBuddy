"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { BuddyBubble, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { UPLOAD_METHODS, type UploadSourceType } from "@/lib/types";
import {
  ApiError,
  computeContentHash,
  getIngestStatus,
  putToStorage,
  registerSource,
  requestUploadUrl,
  startProcessing,
} from "@/lib/api";

const SHEET_COPY: Record<UploadSourceType, string> = {
  VOICE: "이전에 녹음해둔 파일이 있다면 올려주세요. 지금 바로 녹음할 수도 있어요.",
  VIDEO: "촬영하면서 설명해주세요. 사전에 메모나 문서를 첨부하면 더 정확하게 분석해요. (선택 사항)",
  KAKAO: '카카오톡에서 "대화 내보내기"로 저장한 파일이나 대화 캡처 이미지를 올려주세요.',
  SCAN: "메뉴판, 매뉴얼 사진, PDF 파일을 올려주세요. AI가 텍스트를 읽어 분석해요.",
};

const ACCEPT: Record<UploadSourceType, string> = {
  VOICE: "audio/*",
  VIDEO: "video/*",
  KAKAO: ".txt,image/*",
  SCAN: ".pdf,image/*",
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
  const { state, dispatch } = useApp();
  const [busy, setBusy] = useState<UploadSourceType | null>(null);
  const [activeSheet, setActiveSheet] = useState<UploadSourceType | null>(null);
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});
  // 업로드마다 고유 id 를 붙이는 카운터. Date.now()는 렌더 순수성 규칙에 걸려 쓰지 않는다.
  const uploadSeq = useRef(0);

  // uploadSources(전역)가 유일한 출처다 — 로컬 상태를 따로 두면 둘이 어긋난다.
  // state.uploadSources 만 의존성으로 둔다 — state 전체를 넣으면 관련 없는 변경에도 재계산된다.
  const latestByType = useMemo(() => {
    const map: Partial<Record<UploadSourceType, (typeof state.uploadSources)[number]>> = {};
    for (const s of state.uploadSources) map[s.type] = s;
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.uploadSources]);

  const gaugePct = UPLOAD_METHODS.reduce(
    (sum, m) => sum + (latestByType[m.type]?.status === "DONE" ? m.weight : 0),
    0
  );
  const hasAny = Object.values(latestByType).some((s) => s?.status === "DONE");
  const sufficient = gaugePct >= 50;

  async function handleFile(type: UploadSourceType, file: File) {
    uploadSeq.current += 1;
    const id = `${type}-${uploadSeq.current}`;
    dispatch({
      type: "ADD_UPLOAD_SOURCE",
      source: { id, type, title: file.name, status: "UPLOADED" },
    });
    setBusy(type);
    dispatch({ type: "UPDATE_UPLOAD_SOURCE", id, patch: { status: "PROCESSING" } });

    try {
      // 실제 백엔드 연동 경로 (docs/ingest-contract.md 3단계). 토큰이 없으면 401로 실패하고
      // catch 블록에서 로컬 시뮬레이션으로 대체한다 — 배포된 프론트만으로도 데모가 끊기지 않게.
      const token = state.token ?? undefined;
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
        // 같은 파일을 이미 올렸다. 새로 처리하지 않고 완료로 표시한다 (D9).
        dispatch({
          type: "UPDATE_UPLOAD_SOURCE",
          id,
          patch: { status: "DONE", title: `${file.name} (이미 올린 파일)` },
        });
        return;
      }
      dispatch({ type: "UPDATE_UPLOAD_SOURCE", id, patch: { sourceId: source_id } });
      await startProcessing(source_id, token);

      // 영상은 프레임 추출 + 멀티모달 판독이라 분 단위로 걸린다. 60회 × 2초 = 2분까지 기다린다.
      const maxPolls = type === "VIDEO" ? 60 : 30;
      let done = false;
      for (let i = 0; i < maxPolls && !done; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const s = await getIngestStatus(source_id, token);
        if (s.status === "DONE") {
          dispatch({ type: "UPDATE_UPLOAD_SOURCE", id, patch: { status: "DONE" } });
          done = true;
        } else if (s.status === "FAILED") {
          dispatch({
            type: "UPDATE_UPLOAD_SOURCE",
            id,
            patch: { status: "FAILED", errorMessage: s.error_message ?? "처리 실패" },
          });
          done = true;
        }
      }
    } catch (err) {
      if (err instanceof ApiError) {
        // 서버가 내린 판정이다. 조용히 완료로 만들면 등록되지 않은 걸 등록됐다고 속인다.
        dispatch({
          type: "UPDATE_UPLOAD_SOURCE",
          id,
          patch: {
            status: "FAILED",
            errorMessage:
              err.status === 422
                ? "이 파일 형식은 아직 지원하지 않아요"
                : err.detail || `등록 실패 (${err.status})`,
          },
        });
      } else {
        // 백엔드 미연결 — 로컬에서 완료로 표시해 데모 흐름을 이어간다
        await new Promise((r) => setTimeout(r, 1200));
        dispatch({ type: "UPDATE_UPLOAD_SOURCE", id, patch: { status: "DONE" } });
      }
    } finally {
      setBusy(null);
    }
  }

  const buddyMsg = sufficient
    ? "충분한 자료가 모였어요! 인수인계를 시작할 수 있어요 🎉"
    : hasAny
      ? "자료를 더 추가하면 더 정확하게 알려줄 수 있어요! 📎"
      : "어떤 방법으로 알려주실 건가요? 하나만 골라도 괜찮아요 😊";

  return (
    <Shell>
      <TopBar title="자료 업로드" />

      <div className="px-4 pt-1 pb-3 shrink-0">
        <div className="flex justify-between mb-1.5">
          <span className="text-xs font-bold text-brand-700">학습 진전도</span>
          <span className="text-xs font-bold text-brand-500">{gaugePct}%</span>
        </div>
        <div className="h-3 bg-surface-muted rounded-full overflow-hidden mb-3">
          <div
            className="h-full rounded-full transition-all duration-700 ease-out bg-gradient-to-r from-brand-500 to-brand-600"
            style={{ width: `${gaugePct}%` }}
          />
        </div>
        <div className={`rounded-2xl px-3 py-2.5 ${sufficient ? "bg-brand-50" : "bg-accent-50"}`}>
          <BuddyBubble text={buddyMsg} size={30} />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-4">
        <p className="text-xs text-muted mb-3">원하는 방법으로 자료를 올려주세요. 여러 개 조합도 가능해요.</p>
        <div className="space-y-2.5">
          {UPLOAD_METHODS.map((m) => {
            const status = latestByType[m.type]?.status;
            const isDone = status === "DONE";
            return (
              <button
                key={m.type}
                onClick={() => setActiveSheet(m.type)}
                className={`w-full h-[76px] flex items-center gap-3 px-4 rounded-xl border transition-all active:scale-[0.98] ${
                  isDone ? "border-brand-500 bg-brand-50/40" : "border-border bg-surface"
                }`}
              >
                <div
                  className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-xl ${
                    isDone ? "bg-brand-100" : "bg-surface-muted"
                  }`}
                >
                  {m.icon}
                </div>
                <div className="flex-1 min-w-0 text-left">
                  <p className="text-sm font-bold leading-tight">{m.label}</p>
                  <p className="text-xs text-muted mt-0.5 truncate">
                    {status === "FAILED"
                      ? (latestByType[m.type]?.errorMessage ?? "처리 실패")
                      : m.type === "VOICE"
                        ? "녹음 파일 업로드 또는 바로 녹음"
                        : m.type === "VIDEO"
                          ? "촬영하면서 업무를 설명해주세요"
                          : m.type === "KAKAO"
                            ? "대화 파일(.txt) 또는 캡처 이미지 업로드"
                            : "PDF, 메뉴판 사진, 문서 이미지 업로드"}
                  </p>
                </div>
                {isDone ? (
                  <span className="w-6 h-6 rounded-full bg-brand-500 flex items-center justify-center text-white text-xs shrink-0">
                    ✓
                  </span>
                ) : status === "FAILED" ? (
                  <span className="text-danger-500 text-xs font-bold shrink-0">재시도</span>
                ) : status === "PROCESSING" || busy === m.type ? (
                  <span className="text-muted text-xs shrink-0">처리 중…</span>
                ) : (
                  <span className="text-muted shrink-0">→</span>
                )}
              </button>
            );
          })}
        </div>

        {hasAny && (
          <div className="mt-5 bg-surface rounded-2xl px-4 py-3 shadow-sm">
            <p className="text-xs font-bold text-brand-700 mb-2">등록된 자료</p>
            <div className="flex flex-wrap gap-2">
              {UPLOAD_METHODS.filter((c) => latestByType[c.type]?.status === "DONE").map((c) => (
                <div key={c.type} className="flex items-center gap-1 bg-brand-50 rounded-full px-2.5 py-1">
                  <span className="text-xs">{c.icon}</span>
                  <span className="text-xs font-semibold text-brand-700">{c.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="px-4 pb-8 pt-4 bg-gradient-to-t from-background via-background to-transparent">
        <button
          disabled={!hasAny}
          onClick={() => router.push("/owner/preview")}
          className="w-full py-4 rounded-2xl font-bold text-lg transition-all active:scale-95 disabled:cursor-not-allowed"
          style={{
            background: !hasAny ? "var(--border)" : "var(--brand-500)",
            color: !hasAny ? "var(--foreground)" : "white",
            boxShadow: !hasAny ? "none" : "0 6px 20px rgba(91,191,106,0.38)",
          }}
        >
          {!hasAny ? "자료를 하나 이상 등록해주세요" : sufficient ? "미리보기 →" : "일단 미리보기 →"}
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
          {...(m.type === "VIDEO" ? { capture: "environment" as const } : {})}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) handleFile(m.type, file);
          }}
        />
      ))}

      {activeSheet && (
        <UploadSheet
          type={activeSheet}
          status={latestByType[activeSheet]?.status}
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
                    <span className="text-sm font-bold text-white">촬영 시작하기</span>
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
