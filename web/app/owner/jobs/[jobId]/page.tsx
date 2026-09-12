"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Shell, TopBar } from "@/components/ui";
import { ApiError, isIngestJobActive, retryIngestJob } from "@/lib/api";
import { ingestJobQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

function message(error: unknown) {
  return error instanceof ApiError ? error.detail || "작업 상태를 불러오지 못했어요." : "서버에 연결할 수 없습니다.";
}

export default function JobDetailPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = /^\d+$/.test(params.jobId) ? Number(params.jobId) : 0;
  const { state } = useApp();
  const queryClient = useQueryClient();
  const job = useQuery(ingestJobQuery(state.token, state.storeId, jobId));
  const retry = useMutation({
    mutationFn: () => retryIngestJob(jobId, state.token!),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.ingestJob(state.storeId, jobId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) }),
      ]);
    },
  });
  const data = job.data;
  const error = job.error ?? retry.error;
  return (
    <Shell>
      <TopBar title="처리 작업 상세" backHref="/owner/upload?from=dashboard" />
      <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-8">
        {job.isLoading && <div className="h-56 animate-pulse rounded-3xl bg-surface-muted" aria-label="작업 불러오는 중" />}
        {error && <Card className="space-y-3 p-5 text-center"><p role="alert" className="text-sm text-danger-500">{message(error)}</p><Button variant="secondary" onClick={() => void job.refetch()}>다시 시도</Button></Card>}
        {data && <>
          <Card className="space-y-4 p-5">
            <div className="flex items-center gap-2"><Badge tone={isIngestJobActive(data.status) ? "warn" : data.status === "SUCCEEDED" ? "brand" : data.status === "PARTIAL" ? "warn" : "danger"}>{isIngestJobActive(data.status) ? "처리 중" : data.status}</Badge>{job.isFetching && <span className="text-[11px] text-muted">갱신 중…</span>}</div>
            <h1 className="text-lg font-bold text-brand-700">{data.title ?? `작업 #${data.job_id}`}</h1>
            <div className="grid grid-cols-4 gap-2 text-center">{[["자료", data.counts.sources], ["성공", data.counts.succeeded], ["실패", data.counts.failed], ["카드", data.counts.cards]].map(([label, value]) => <div key={label} className="rounded-xl bg-surface-muted p-2"><p className="text-base font-bold">{value}</p><p className="text-[10px] text-muted">{label}</p></div>)}</div>
            {isIngestJobActive(data.status) && <p className="text-xs text-muted">다른 화면으로 이동해도 서버에서 계속 처리합니다.</p>}
            {(data.status === "FAILED" || data.status === "NO_RESULT") && <Button disabled={retry.isPending} onClick={() => retry.mutate()}>{retry.isPending ? "재시도 중…" : "작업 재시도"}</Button>}
            {data.counts.cards > 0 && <Link href={data.review_destination} className="flex min-h-11 items-center justify-center rounded-xl bg-brand-500 px-4 text-sm font-bold text-white">이 작업의 카드 검토</Link>}
          </Card>
          <section className="space-y-3"><h2 className="text-sm font-bold text-brand-700">자료별 상태</h2>{data.sources.map((source) => <Card key={source.source_id} className="space-y-2 p-4"><div className="flex items-center justify-between gap-3"><p className="truncate text-sm font-semibold">{source.filename}</p><span className="shrink-0 text-xs font-bold text-muted">{source.status}</span></div><p className="text-[11px] text-muted">생성 카드 {source.card_count}개</p>{source.error && <p role="alert" className="rounded-xl bg-danger-50 px-3 py-2 text-xs text-danger-500">{source.error.message}</p>}</Card>)}</section>
        </>}
        {!jobId && <Card className="p-6 text-center text-sm text-danger-500">잘못된 작업 링크입니다.</Card>}
      </div>
    </Shell>
  );
}
