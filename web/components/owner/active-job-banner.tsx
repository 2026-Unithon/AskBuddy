"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { focusRing, pressable } from "@/components/kit/buttons";
import { isIngestJobActive } from "@/lib/api";
import { ingestJobsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";
import { CancelJobButton } from "./cancel-job-button";
import { JOB_STEPS, jobStepIndex } from "./job-steps-logic";

/**
 * 오늘 매장 위 "카드 제작 중" 줄들. 자료를 올리고 작업 화면을 떠나도 진행을 여기서 본다.
 * 서버 작업 목록이 정본이고, 진행 중인 작업이 있는 동안만 목록 조회가 2초마다 다시 돈다(ingestJobsQuery).
 */
export function ActiveJobBanner() {
  const { state } = useApp();
  const jobs = useQuery(ingestJobsQuery(state.token, state.storeId));
  // 올린 순서대로 다(2026-11-08 사용자: 여러 개 올리면 최근 것만 떴다). 줄마다 옆에서 취소
  const active = (jobs.data?.items ?? [])
    .filter((job) => isIngestJobActive(job.status))
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.job_id - b.job_id);
  if (active.length === 0) return null;
  return (
    <ul aria-label="정리 중인 자료" className="flex flex-col gap-2">
      {active.map((job) => {
        const step = Math.min(jobStepIndex(job.status), 2);
        return (
          <li key={job.job_id} data-active-job="" className="flex items-center gap-2 rounded-[16px] bg-empty py-2 pl-4 pr-2 text-primary">
            <Link href={`/owner/jobs/${job.job_id}`} className={`flex min-w-0 flex-1 items-center gap-3 rounded-[12px] py-1 ${pressable} ${focusRing}`}>
              {job.status === "QUEUED" ? (
                <span aria-hidden className="size-5 shrink-0 rounded-full border-[2.5px] border-current opacity-40" />
              ) : (
                <span aria-hidden className="size-5 shrink-0 animate-spin rounded-full border-[2.5px] border-current border-r-transparent" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[15px] font-bold">{job.title?.trim() || `올린 자료 ${job.source_count}개`}</span>
                <span className="block text-[13px] text-ink-muted">{job.status === "QUEUED" ? "차례를 기다려요" : JOB_STEPS[step]}</span>
              </span>
            </Link>
            <CancelJobButton jobId={job.job_id} sourceCount={job.source_count} />
          </li>
        );
      })}
    </ul>
  );
}
