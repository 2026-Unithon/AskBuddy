"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { focusRing, pressable } from "@/components/kit/buttons";
import { Icon } from "@/components/kit/icon";
import { isIngestJobActive } from "@/lib/api";
import { ingestJobsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";
import { JOB_STEPS, jobStepIndex } from "./job-steps-logic";

/**
 * 오늘 매장 위 "카드 제작 중" 줄. 자료를 올리고 작업 화면을 떠나도 진행을 여기서 본다.
 * 서버 작업 목록이 정본이고, 진행 중인 작업이 있는 동안만 목록 조회가 2초마다 다시 돈다(ingestJobsQuery).
 */
export function ActiveJobBanner() {
  const { state } = useApp();
  const jobs = useQuery(ingestJobsQuery(state.token, state.storeId));
  const active = (jobs.data?.items ?? []).filter((job) => isIngestJobActive(job.status));
  if (active.length === 0) return null;
  const job = active[0];
  const step = Math.min(jobStepIndex(job.status), 2);
  return (
    <Link
      href={`/owner/jobs/${job.job_id}`}
      data-active-job=""
      className={`flex items-center gap-3 rounded-[16px] bg-empty px-4 py-3 text-primary ${pressable} ${focusRing}`}
    >
      <span aria-hidden className="size-5 shrink-0 animate-spin rounded-full border-[2.5px] border-current border-r-transparent" />
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-bold">{JOB_STEPS[step]}</span>
        <span className="block text-[13px] text-ink-muted">
          {active.length > 1 ? `자료 ${active.length}건 정리 중이에요` : "다 되면 알려드릴게요"}
        </span>
      </span>
      <Icon name="right" size={18} className="text-ink-muted" />
    </Link>
  );
}
