"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui";
import { useApp } from "@/lib/store";
import type { UploadSourceType } from "@/lib/types";
import {
  ApiError,
  computeContentHash,
  createIngestJob,
  putToStorage,
  registerSource,
  requestUploadUrl,
  retryIngestJob,
} from "@/lib/api";
import { ingestJobsQuery, queryKeys } from "@/lib/query";

import { UploadFilePicker } from "@/components/owner/upload-file-picker";
import { UploadQueueItem, type QueuedUploadFile } from "@/components/owner/upload-queue-item";
import { BackgroundJobStatus } from "@/components/owner/background-job-status";
import { InlineError } from "@/components/owner/inline-error";
import { SkeletonList } from "@/components/owner/skeleton-list";
import { OwnerPageHeader } from "@/components/owner/owner-page-header";

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
      return { import_type: ["png", "jpg", "jpeg"].includes(ext) ? "SCREENSHOT" : "TXT_EXPORT" };
    case "SCAN":
    default:
      return { doc_type: DOC_TYPE[ext] ?? "PDF", doc_category: "ETC" };
  }
}

export default function UploadPage() {
  const { state } = useApp();
  const queryClient = useQueryClient();

  const [queue, setQueue] = useState<QueuedUploadFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const batchIdempotencyKey = useRef<string | null>(null);

  const jobsQuery = useQuery(ingestJobsQuery(state.token, state.storeId));
  const jobs = jobsQuery.data?.items ?? [];

  const retryJob = useMutation({
    mutationFn: (jobId: number) => retryIngestJob(jobId, state.token!),
    onSuccess: async () => {
      setErrorMessage(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) });
    },
    onError: (retryError) => {
      setErrorMessage(
        retryError instanceof ApiError
          ? retryError.detail || "재시도하지 못했어요"
          : "서버에 연결할 수 없습니다."
      );
    },
  });

  function handleFilesAdded(newFiles: QueuedUploadFile[]) {
    batchIdempotencyKey.current = null;
    setErrorMessage(null);
    setSuccessMessage(null);
    setQueue((prev) => [...prev, ...newFiles]);
  }

  function handleInvalidFiles(errors: string[]) {
    setErrorMessage(errors.join("\n"));
  }

  function handleRemoveFile(id: string) {
    batchIdempotencyKey.current = null;
    setQueue((prev) => prev.filter((item) => item.id !== id));
  }

  async function handleStartBatchUpload() {
    if (queue.length === 0 || isUploading) return;
    if (!state.token) {
      setErrorMessage("로그인 정보가 없습니다. 다시 로그인해주세요.");
      return;
    }

    setIsUploading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    const token = state.token;
    const registeredSources: Array<{ sourceId: number; fileName: string }> = [];
    let failureCount = 0;

    for (let i = 0; i < queue.length; i++) {
      const item = queue[i];

      if (item.sourceId) {
        registeredSources.push({ sourceId: item.sourceId, fileName: item.file.name });
        continue;
      }

      // 대기열 아이템 업로드 중 표시
      setQueue((prev) =>
        prev.map((q, idx) => (idx === i ? { ...q, status: "uploading" } : q))
      );

      try {
        const { upload_url, file_url } = await requestUploadUrl(item.sourceType, item.file.name, token);
        await putToStorage(upload_url, item.file);
        const contentHash = await computeContentHash(item.file);
        const { source_id, duplicate } = await registerSource(
          {
            sourceType: item.sourceType,
            fileUrl: file_url,
            title: item.file.name,
            fileSize: item.file.size,
            contentHash,
            meta: metaFor(item.sourceType, item.file),
          },
          token
        );

        if (duplicate) {
          failureCount++;
          setQueue((prev) =>
            prev.map((q, idx) =>
              idx === i
                ? { ...q, status: "error", errorMessage: "이미 등록된 파일" }
                : q
            )
          );
        } else {
          registeredSources.push({ sourceId: source_id, fileName: item.file.name });
          setQueue((prev) =>
            prev.map((q, idx) =>
              idx === i
                ? { ...q, sourceId: source_id, status: "registered", errorMessage: undefined }
                : q
            )
          );
        }
      } catch (err) {
        failureCount++;
        const msg =
          err instanceof ApiError
            ? err.detail || `업로드 실패 (${err.status})`
            : "전송 오류";
        setQueue((prev) =>
          prev.map((q, idx) =>
            idx === i ? { ...q, status: "error", errorMessage: msg } : q
          )
        );
      }
    }

    // 성공한 소스들이 있으면 백그라운드 인제스트 작업 생성
    if (registeredSources.length > 0) {
      try {
        const title =
          registeredSources.length === 1
            ? registeredSources[0].fileName
            : `${registeredSources[0].fileName} 외 ${registeredSources.length - 1}건`;

        const idempotencyKey = batchIdempotencyKey.current ?? crypto.randomUUID();
        batchIdempotencyKey.current = idempotencyKey;

        await createIngestJob(
          registeredSources.map((source) => source.sourceId),
          token,
          {
          title,
          idempotencyKey,
          }
        );

        await queryClient.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) });
        batchIdempotencyKey.current = null;

        setSuccessMessage(
          `서버에 접수되었습니다. AI가 업무 카드로 정리하고 있으니 다른 화면으로 가도 계속 처리돼요.`
        );

        const acceptedIds = new Set(registeredSources.map((source) => source.sourceId));
        setQueue((prev) => prev.filter((item) => !item.sourceId || !acceptedIds.has(item.sourceId)));
      } catch (err) {
        setErrorMessage(
          err instanceof ApiError
            ? err.detail || "분석 작업 접수에 실패했어요. 파일 등록 상태는 보존했으니 다시 시도해주세요."
            : "분석 작업을 접수하지 못했습니다. 파일 등록 상태는 보존했으니 다시 시도해주세요."
        );
      }
    } else if (failureCount > 0) {
      setErrorMessage("파일을 전송하지 못했습니다. 네트워크와 파일 형식을 확인해주세요.");
    }

    setIsUploading(false);
  }

  const queryError = jobsQuery.error instanceof ApiError
    ? jobsQuery.error.detail || "작업 목록을 불러오지 못했어요."
    : jobsQuery.error
    ? "서버에 연결할 수 없습니다."
    : null;

  return (
    <div className="flex-1 flex flex-col w-full bg-background min-h-dvh">
      <OwnerPageHeader
        title="자료 업로드"
        subtitle="음성·영상·문서·카톡 자료로 매장 지식 구축"
        isFetching={jobsQuery.isFetching}
        isLoading={jobsQuery.isLoading}
      />

      {/* 메인 스크롤 콘텐츠 (하단 탭 높이 고려 pb-24) */}
      <main className="flex-1 space-y-4 px-4 py-4 pb-24 overflow-y-auto">
        {/* 파일 추가 단일 주 CTA */}
        <section aria-label="파일 선택">
          <UploadFilePicker
            onFilesAdded={handleFilesAdded}
            onInvalidFiles={handleInvalidFiles}
            disabled={isUploading}
          />
        </section>

        {/* 에러 메시지 알림 (사라지지 않고 텍스트 유지) */}
        {(errorMessage || queryError) && (
          <InlineError
            message={errorMessage ?? queryError!}
            onRetry={() => {
              setErrorMessage(null);
              void jobsQuery.refetch();
            }}
          />
        )}

        {/* 접수 성공 안내 알림 */}
        {successMessage && (
          <div
            role="status"
            className="rounded-2xl border border-brand-500/40 bg-brand-50/60 p-3.5 text-xs text-brand-800 shadow-2xs space-y-1"
          >
            <p className="font-bold flex items-center gap-1.5">
              <span>✓</span>
              <span>서버 접수 완료!</span>
            </p>
            <p className="leading-relaxed text-brand-900/90">{successMessage}</p>
          </div>
        )}

        {/* 업로드 대기열 (Queue) */}
        {queue.length > 0 && (
          <section className="space-y-2.5 pt-1" aria-labelledby="queue-heading">
            <div className="flex items-center justify-between px-1">
              <h2 id="queue-heading" className="text-xs font-bold text-foreground uppercase tracking-wider">
                선택한 파일 목록 ({queue.length}개)
              </h2>
              {!isUploading && (
                <button
                  type="button"
                  onClick={() => {
                    batchIdempotencyKey.current = null;
                    setQueue([]);
                  }}
                  className="text-[11px] text-muted hover:text-danger-600 font-semibold active:scale-95"
                >
                  전체 취소
                </button>
              )}
            </div>

            <div className="space-y-2">
              {queue.map((item) => (
                <UploadQueueItem
                  key={item.id}
                  item={item}
                  onRemove={handleRemoveFile}
                  disabled={isUploading}
                />
              ))}
            </div>

            {/* 업로드 및 분석 시작 CTA 버튼 */}
            <div className="pt-2">
              <Button
                size="lg"
                variant="primary"
                disabled={isUploading || queue.length === 0}
                onClick={handleStartBatchUpload}
                className="w-full min-h-[50px] text-xs font-bold shadow-xs active:scale-[0.98]"
              >
                {isUploading
                  ? "파일 전송 및 서버 접수 중…"
                  : queue.some((item) => item.status === "registered")
                  ? "분석 작업 다시 접수하기"
                  : `${queue.length}개 파일 업로드 및 분석 시작`}
              </Button>
            </div>
          </section>
        )}

        {/* 최근 처리 작업 로딩 스켈레톤 */}
        {jobsQuery.isLoading && (
          <div className="pt-4 space-y-2">
            <p className="text-xs font-bold text-muted px-1">처리 작업 불러오는 중…</p>
            <SkeletonList count={3} heightClass="h-20" />
          </div>
        )}

        {/* 최근 처리 작업 목록 및 상태 안내 */}
        <BackgroundJobStatus
          jobs={jobs}
          onRetry={(jobId) => retryJob.mutate(jobId)}
          isRetrying={retryJob.isPending}
          isFetching={jobsQuery.isFetching}
          isLoading={jobsQuery.isLoading}
        />
      </main>
    </div>
  );
}
