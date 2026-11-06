"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useFeedback } from "@/components/kit";
import { isIngestJobActive } from "@/lib/api";
import { ingestJobsQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

/**
 * 작업이 진행 → 끝으로 바뀌면 관련 조회를 새로 하고 "정리 끝!"을 알린다(o03c).
 * 그 작업 화면을 보고 있으면 토스트만, 다른 화면이면 '보기' 스낵바. 카드 없이 끝난 작업은 알리지 않는다(실패 화면이 보여 준다).
 */
export function OwnerJobMonitor() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const { toast, snackbar } = useFeedback();
  const jobs = useQuery(ingestJobsQuery(state.token, state.storeId));
  const previous = useRef<Map<number, string>>(new Map());
  const where = useRef(pathname);

  useEffect(() => {
    where.current = pathname;
  }, [pathname]);

  useEffect(() => {
    const items = jobs.data?.items;
    if (!items) return;

    const finished = items.filter((job) => {
      const oldStatus = previous.current.get(job.job_id);
      return oldStatus !== undefined && isIngestJobActive(oldStatus as typeof job.status) && !isIngestJobActive(job.status);
    });
    previous.current = new Map(items.map((job) => [job.job_id, job.status]));
    if (!finished.length) return;

    void queryClient.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.notificationsRoot(state.storeId) });

    const done = finished.find((job) => job.card_count > 0);
    if (!done) return;
    const target = `/owner/jobs/${done.job_id}`;
    if (where.current === target) toast("정리 끝!");
    else snackbar({ message: "정리 끝!", actionLabel: "보기", onAction: () => router.push(target) });
  }, [jobs.data?.items, queryClient, router, snackbar, state.userId, state.storeId, toast]);

  return null;
}
