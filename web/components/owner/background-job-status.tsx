"use client";

import Link from "next/link";
import { Card } from "@/components/ui";
import { isIngestJobActive, type IngestJobListItem, type IngestJobStatus } from "@/lib/api";
import { JobStatusBadge } from "./status-badge";

interface BackgroundJobStatusProps {
  jobs: IngestJobListItem[];
  onRetry: (jobId: number) => void;
  retryingJobId?: number | null;
  isFetching?: boolean;
  isLoading?: boolean;
}

function jobStatusDescription(status: IngestJobStatus) {
  switch (status) {
    case "QUEUED":
      return "서버 접수 완료 · 분석 대기 중";
    case "EXTRACTING":
      return "AI가 자료에서 업무 내용을 추출하는 중…";
    case "CLASSIFYING":
      return "추출된 내용을 매장 카테고리로 정리하는 중…";
    case "SUCCEEDED":
      return "업무 카드 정리 완료! 검토가 가능해요.";
    case "PARTIAL":
      return "일부 자료만 정리되었어요. 실패한 자료는 재시도해주세요.";
    case "NO_RESULT":
      return "정상 처리되었으나 업무 내용을 찾지 못했어요.";
    case "FAILED":
      return "처리 중 오류가 발생했어요. 다시 시도할 수 있어요.";
    default:
      return status;
  }
}

export function BackgroundJobStatus({
  jobs,
  onRetry,
  retryingJobId = null,
  isFetching = false,
  isLoading = false,
}: BackgroundJobStatusProps) {
  const activeJobs = jobs.filter((j) => isIngestJobActive(j.status));

  if (isLoading) {
    return null; // SkeletonList는 상위에서 렌더링
  }

  if (jobs.length === 0) {
    return null;
  }

  return (
    <section className="space-y-3 pt-2" aria-labelledby="jobs-heading">
      <div className="flex items-center justify-between px-1">
        <h2 id="jobs-heading" className="text-xs font-bold text-brand-700 uppercase tracking-wider">
          최근 처리 작업
        </h2>
        {isFetching && !isLoading && (
          <span className="text-xs text-muted bg-surface-muted px-2 py-0.5 rounded-full">
            갱신 중…
          </span>
        )}
      </div>

      {/* 처리 중 작업이 있을 때 안심 안내 메시지 */}
      {activeJobs.length > 0 && (
        <div
          role="status"
          className="flex items-center gap-2.5 rounded-xl border border-brand-500/30 bg-brand-50/50 p-3 text-xs text-brand-800 shadow-2xs"
        >
          <span className="h-2 w-2 rounded-full bg-brand-500 motion-safe:animate-ping shrink-0" />
          <p className="font-medium leading-relaxed">
            <strong>{activeJobs.length}개 작업</strong>을 정리하고 있어요. 다른 화면으로 가도 백그라운드에서 계속 처리돼요.
          </p>
        </div>
      )}

      {/* 작업 카드 목록 */}
      <div className="space-y-2">
        {jobs.slice(0, 10).map((job) => {
          const isActive = isIngestJobActive(job.status);
          const isFailed = job.status === "FAILED" || job.status === "PARTIAL";
          const hasCards = job.card_count > 0;
          const isRetrying = retryingJobId === job.job_id;

          return (
            <Card
              key={job.job_id}
              className={`p-3.5 space-y-2 border transition-all ${
                isActive
                  ? "border-brand-300 bg-brand-50/20"
                  : isFailed
                  ? "border-danger-200 bg-danger-50/20"
                  : "border-border bg-surface"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold text-foreground truncate">
                    {job.title ?? `작업 #${job.job_id}`}
                  </p>
                  <p className="text-xs text-muted mt-0.5">
                    {jobStatusDescription(job.status)}
                  </p>
                </div>
                <JobStatusBadge status={job.status} />
              </div>

              {/* 하단 세부 액션 및 카드 링크 */}
              <div className="flex items-center justify-between pt-1 border-t border-border/50 text-xs">
                <span className="text-xs text-muted">
                  생성 카드: <strong className="text-brand-700">{job.card_count}개</strong>
                </span>

                <div className="flex items-center gap-2">
                  {isFailed && (
                    <button
                      type="button"
                      disabled={isRetrying}
                      onClick={() => onRetry(job.job_id)}
                      aria-busy={isRetrying || undefined}
                      className="min-h-11 px-3 rounded-lg font-bold text-danger-700 bg-danger-50 border border-danger-200 hover:bg-danger-100 active:scale-95 transition-all text-sm disabled:opacity-50"
                    >
                      실패 재시도
                    </button>
                  )}

                  {hasCards && (
                    <Link
                      href={`/owner/cards/review?job_id=${job.job_id}`}
                      className="inline-flex min-h-11 items-center gap-1 px-3 rounded-lg font-bold text-brand-700 bg-brand-50 hover:bg-brand-100 active:scale-95 transition-all text-sm"
                    >
                      <span>카드 검토하기</span>
                      <span>→</span>
                    </Link>
                  )}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </section>
  );
}
