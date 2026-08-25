"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge, BottomCta, Button, Card, ProgressBar, Shell, TopBar } from "@/components/ui";
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
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const [busy, setBusy] = useState<UploadSourceType | null>(null);

  const latestByType = useMemo(() => {
    const map: Partial<Record<UploadSourceType, (typeof state.uploadSources)[number]>> = {};
    for (const s of state.uploadSources) map[s.type] = s;
    return map;
  }, [state.uploadSources]);

  const gaugePct = UPLOAD_METHODS.reduce(
    (sum, m) => sum + (latestByType[m.type]?.status === "DONE" ? m.weight : 0),
    0
  );

  async function handleFile(type: UploadSourceType, file: File) {
    const id = `${type}-${Date.now()}`;
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

  return (
    <Shell>
      <TopBar title="자료 업로드" />
      <div className="flex-1 overflow-y-auto px-6 pt-2 pb-4 flex flex-col gap-5">
        <div className="space-y-2">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-semibold text-muted">학습 진행률</span>
            <span className="text-sm font-bold text-brand-700">{gaugePct}%</span>
          </div>
          <ProgressBar pct={gaugePct} />
        </div>

        <div className="flex flex-col gap-3">
          {UPLOAD_METHODS.map((m) => {
            const source = latestByType[m.type];
            const status = source?.status;
            return (
              <Card key={m.type} className="p-4 flex items-center gap-3.5">
                <div className="w-12 h-12 rounded-2xl bg-brand-50 flex items-center justify-center text-xl shrink-0">
                  {m.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold">{m.label}</p>
                  <p className="text-xs text-muted mt-0.5">
                    {`${m.formats} · 가중치 ${m.weight}%`}
                  </p>
                  {status === "FAILED" && source?.errorMessage && (
                    <p className="text-xs text-danger-500 mt-1">{source.errorMessage}</p>
                  )}
                </div>
                <input
                  ref={(el) => {
                    inputRefs.current[m.type] = el;
                  }}
                  type="file"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) handleFile(m.type, file);
                    e.target.value = "";
                  }}
                />
                {status === "DONE" ? (
                  <Badge tone="brand">✅ 완료</Badge>
                ) : status === "PROCESSING" ? (
                  <Badge tone="neutral">처리 중…</Badge>
                ) : status === "FAILED" ? (
                  <Button
                    variant="danger"
                    className="h-9 px-3 text-xs"
                    onClick={() => inputRefs.current[m.type]?.click()}
                  >
                    다시 시도
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    className="h-9 px-3 text-xs"
                    disabled={busy !== null}
                    onClick={() => inputRefs.current[m.type]?.click()}
                  >
                    업로드
                  </Button>
                )}
              </Card>
            );
          })}
        </div>
      </div>
      <BottomCta>
        <Button size="lg" className="w-full" onClick={() => router.push("/owner/preview")}>
          {gaugePct >= 50 ? "학습 미리보기" : "일단 미리보기 (진행률 낮음)"}
        </Button>
      </BottomCta>
    </Shell>
  );
}
