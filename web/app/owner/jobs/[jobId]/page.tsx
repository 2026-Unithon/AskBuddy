"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Shell, TopBar } from "@/components/ui";
import { ApiError, deleteIngestSource, isIngestJobActive, retryIngestJob } from "@/lib/api";
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
    onSuccess: () => {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.ingestJob(state.storeId, jobId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) }),
      ]);
    },
  });
  const removeSource = useMutation({
    mutationFn: (sourceId: number) => deleteIngestSource(sourceId, state.token!),
    onSuccess: () => {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.ingestJob(state.storeId, jobId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) }),
      ]);
    },
  });
  const data = job.data;
  const error = job.error ?? retry.error;
  const sourceBusy = data ? isIngestJobActive(data.status) : true;
  return (
    <Shell>
      <TopBar title="처리 작업 상세" backHref="/owner/upload" />
      <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-8">
        {job.isLoading && <div className="h-56 motion-safe:animate-pulse rounded-3xl bg-surface-muted" aria-label="작업 불러오는 중" />}
        {error && <Card className="space-y-3 p-5 text-center"><p role="alert" className="text-sm text-danger-500">{message(error)}</p><Button variant="secondary" loading={job.isFetching} loadingLabel="다시 확인 중" onClick={() => void job.refetch()}>다시 시도</Button></Card>}
        {data && <>
          <Card className="space-y-4 p-5">
            <div className="flex items-center gap-2"><Badge tone={isIngestJobActive(data.status) ? "warn" : data.status === "SUCCEEDED" ? "brand" : data.status === "PARTIAL" ? "warn" : "danger"}>{isIngestJobActive(data.status) ? "처리 중" : data.status}</Badge>{job.isFetching && <span className="text-xs text-muted">갱신 중…</span>}</div>
            <h1 className="text-lg font-bold text-brand-700">{data.title ?? `작업 #${data.job_id}`}</h1>
            <div className="grid grid-cols-5 gap-2 text-center">{[["자료", data.counts.sources], ["성공", data.counts.succeeded], ["부분", data.counts.partial], ["실패", data.counts.failed], ["카드", data.counts.cards]].map(([label, value]) => <div key={label} className="rounded-xl bg-surface-muted p-2"><p className="text-base font-bold">{value}</p><p className="text-xs text-muted">{label}</p></div>)}</div>
            {isIngestJobActive(data.status) && <p className="text-xs text-muted">다른 화면으로 이동해도 서버에서 계속 처리합니다.</p>}
            {(data.status === "FAILED" || data.status === "NO_RESULT" || data.status === "PARTIAL") && <Button loading={retry.isPending} loadingLabel="작업 재시도 중" onClick={() => retry.mutate()}>작업 재시도</Button>}
            {data.counts.cards > 0 && <Link href={data.review_destination} className="flex min-h-11 items-center justify-center rounded-xl bg-brand-500 px-4 text-sm font-bold text-white">이 작업의 카드 검토</Link>}
          </Card>
          <section className="space-y-3"><h2 className="text-sm font-bold text-brand-700">자료별 상태</h2>{data.sources.map((source) => {
            const deleted = source.source_availability === "DELETED";
            const deleting = removeSource.isPending && removeSource.variables === source.source_id;
            const deleteError = removeSource.isError && removeSource.variables === source.source_id ? removeSource.error : null;
            return <Card key={source.source_id} className="space-y-2 p-4" data-testid={`job-source-${source.source_id}`}>
              <div className="flex items-center justify-between gap-3"><p className={`truncate text-sm font-semibold ${deleted ? "text-muted line-through" : ""}`}>{source.filename}</p><span className="shrink-0 text-xs font-bold text-muted">{deleted ? "삭제됨" : source.status}</span></div>
              <p className="text-xs text-muted">생성 카드 {source.card_count}개</p>
              {deleted && <p className="text-xs text-muted">원본은 더 이상 열 수 없어요. 만든 카드와 답변 근거는 남고 &lsquo;인용 끊김&rsquo;으로 표시돼요.</p>}
              {source.error && !deleted && <p role="alert" className="rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger-600">{source.error.message}</p>}
              {deleteError && <p role="alert" className="rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger-600">{deleteError instanceof ApiError ? deleteError.detail || "자료를 삭제하지 못했어요." : "서버에 연결할 수 없습니다."}</p>}
              {!deleted && <Button variant="secondary" disabled={sourceBusy || removeSource.isPending} loading={deleting} loadingLabel="자료 삭제 중" aria-label={`${source.filename} 자료 삭제`} onClick={() => {
                if (window.confirm("이 자료를 삭제할까요? 원본 파일은 더 이상 열 수 없고 다시 처리할 수 없습니다. 이미 만든 카드와 답변 근거는 남고 '인용 끊김'으로 표시됩니다.")) removeSource.mutate(source.source_id);
              }}>자료 삭제</Button>}
              {!deleted && sourceBusy && <p className="text-xs text-muted">처리가 끝난 뒤 삭제할 수 있어요.</p>}
            </Card>;
          })}</section>
        </>}
        {!jobId && <Card className="p-6 text-center text-sm text-danger-500">잘못된 작업 링크입니다.</Card>}
      </div>
    </Shell>
  );
}
