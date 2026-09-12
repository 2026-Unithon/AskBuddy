"use client";

import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isIngestJobActive } from "@/lib/api";
import { ingestJobsQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

export function OwnerJobMonitor() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const jobs = useQuery(ingestJobsQuery(state.token, state.storeId));
  const previous = useRef<Map<number, string>>(new Map());

  useEffect(() => {
    const items = jobs.data?.items;
    if (!items) return;

    const completed = items.some((job) => {
      const oldStatus = previous.current.get(job.job_id);
      return oldStatus !== undefined && isIngestJobActive(oldStatus as typeof job.status) && !isIngestJobActive(job.status);
    });
    previous.current = new Map(items.map((job) => [job.job_id, job.status]));

    if (completed) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.notificationsRoot(state.storeId) });
    }
  }, [jobs.data?.items, queryClient, state.storeId]);

  return null;
}
