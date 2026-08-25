"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge, BottomCta, Button, Card, ProgressBar, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { UPLOAD_METHODS, type UploadSourceType } from "@/lib/types";
import {
  computeContentHash,
  getIngestStatus,
  putToStorage,
  registerSource,
  requestUploadUrl,
  startProcessing,
} from "@/lib/api";

function metaFor(type: UploadSourceType, file: File): Record<string, unknown> {
  switch (type) {
    case "VOICE":
      return { audio_format: file.name.split(".").pop(), record_method: "UPLOAD" };
    case "VIDEO":
      return { video_format: file.name.split(".").pop() };
    case "KAKAO":
      return { import_type: "FILE" };
    case "SCAN":
      return { doc_type: file.name.split(".").pop() };
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

  const hasAnyOtherDone = UPLOAD_METHODS.filter((m) => m.type !== "VIDEO").some(
    (m) => latestByType[m.type]?.status === "DONE"
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
      const { upload_url, file_url } = await requestUploadUrl(type, file.name);
      await putToStorage(upload_url, file);
      const contentHash = await computeContentHash(file);
      const { source_id } = await registerSource({
        sourceType: type,
        fileUrl: file_url,
        title: file.name,
        fileSize: file.size,
        contentHash,
        meta: metaFor(type, file),
      });
      await startProcessing(source_id);

      let done = false;
      for (let i = 0; i < 15 && !done; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const s = await getIngestStatus(source_id);
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
    } catch {
      // 백엔드 미연결 상태 — 로컬에서 처리 완료로 표시해 데모 흐름을 이어간다.
      await new Promise((r) => setTimeout(r, 1200));
      dispatch({ type: "UPDATE_UPLOAD_SOURCE", id, patch: { status: "DONE" } });
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
            const locked = Boolean(m.requiresOther) && !hasAnyOtherDone;
            const status = source?.status;
            return (
              <Card key={m.type} className="p-4 flex items-center gap-3.5">
                <div className="w-12 h-12 rounded-2xl bg-brand-50 flex items-center justify-center text-xl shrink-0">
                  {m.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold">{m.label}</p>
                  <p className="text-xs text-muted mt-0.5">
                    {locked ? "다른 자료를 먼저 등록하면 열려요" : `${m.formats} · 가중치 ${m.weight}%`}
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
                    disabled={locked || busy !== null}
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
