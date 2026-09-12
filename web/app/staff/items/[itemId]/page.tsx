"use client";

import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Shell, TopBar } from "@/components/ui";
import { ApiError, setLearnItemCompletion } from "@/lib/api";
import { learnItemQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

function message(error: unknown) {
  return error instanceof ApiError ? error.detail || "학습 내용을 처리하지 못했어요." : "서버에 연결할 수 없습니다.";
}

export default function LearnItemPage() {
  const params = useParams<{ itemId: string }>();
  const itemId = /^\d+$/.test(params.itemId) ? Number(params.itemId) : 0;
  const { state } = useApp();
  const queryClient = useQueryClient();
  const item = useQuery(learnItemQuery(state.token, state.storeId, state.userId, itemId));
  const completion = useMutation({
    mutationFn: (completed: boolean) => setLearnItemCompletion(itemId, item.data!.published_version_id, completed, state.token!),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.learnItem(state.storeId, state.userId, itemId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.roadmap(state.storeId, state.userId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.staff(state.storeId) }),
      ]);
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) await item.refetch();
    },
  });
  const data = item.data;
  const error = item.error ?? completion.error;

  return (
    <Shell>
      <TopBar title={data?.category.name ?? "학습 카드"} backHref="/staff/roadmap" />
      <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-8">
        {item.isLoading && <div className="h-80 animate-pulse rounded-3xl bg-surface-muted" aria-label="학습 내용 불러오는 중" />}
        {error && <Card className="space-y-3 p-5 text-center"><p role="alert" className="text-sm text-danger-500">{message(error)}</p><Button variant="secondary" onClick={() => void item.refetch()}>최신 내용 다시 불러오기</Button></Card>}
        {data && (
          <>
            <Card className="space-y-4 p-5">
              <div className="flex flex-wrap items-center gap-2"><Badge tone="neutral">{data.category.name}</Badge>{data.status === "RECONFIRM_REQUIRED" && <Badge tone="warn">내용 변경 · 재확인 필요</Badge>}{item.isFetching && <span className="text-[11px] text-muted">갱신 중…</span>}</div>
              <h1 className="text-xl font-bold text-brand-700">{data.title}</h1>
              <p className="whitespace-pre-wrap text-sm leading-7">{data.content}</p>
              <Button className="w-full" disabled={completion.isPending} onClick={() => completion.mutate(data.status !== "DONE")}>{completion.isPending ? "저장 중…" : data.status === "DONE" ? "완료 취소" : data.status === "RECONFIRM_REQUIRED" ? "최신 내용 확인 완료" : "이해했어요"}</Button>
              <p className="text-center text-[11px] text-muted">현재 공개 버전 #{data.published_version_id}을 확인한 것으로 기록됩니다.</p>
            </Card>
            <section className="space-y-3"><h2 className="text-sm font-bold text-brand-700">근거</h2>{data.evidence.length === 0 ? <Card className="p-4 text-xs text-muted">표시할 근거가 없습니다.</Card> : data.evidence.map((evidence) => <Card key={evidence.evidence_id} className="space-y-2 p-4"><p className="text-xs font-bold">{evidence.source.title ?? "업무 원본"}</p>{evidence.excerpt && <blockquote className="border-l-2 border-brand-500 pl-3 text-xs leading-relaxed text-muted">{evidence.excerpt}</blockquote>}{evidence.source.read_url && <a href={evidence.source.read_url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center text-xs font-bold text-brand-500">원본 열기</a>}</Card>)}</section>
          </>
        )}
        {!itemId && <Card className="p-6 text-center text-sm text-danger-500">잘못된 학습 링크입니다.</Card>}
      </div>
    </Shell>
  );
}
