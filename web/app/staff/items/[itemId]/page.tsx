"use client";

import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, TopBar } from "@/components/ui";
import { ApiError, setLearnItemCompletion } from "@/lib/api";
import { learnItemQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

function message(error: unknown) {
  return error instanceof ApiError
    ? error.detail || "학습 내용을 처리하지 못했어요."
    : "서버에 연결할 수 없습니다.";
}

export default function LearnItemPage() {
  const params = useParams<{ itemId: string }>();
  const itemId = /^\d+$/.test(params.itemId) ? Number(params.itemId) : 0;
  const { state } = useApp();
  const queryClient = useQueryClient();

  const item = useQuery(learnItemQuery(state.token, state.storeId, state.userId, itemId));

  const completion = useMutation({
    mutationFn: (completed: boolean) =>
      setLearnItemCompletion(itemId, item.data!.published_version_id, completed, state.token!),
    onSuccess: () => {
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.learnItem(state.storeId, state.userId, itemId),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.roadmap(state.storeId, state.userId),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.staff(state.storeId),
        }),
      ]);
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) {
        await item.refetch();
      }
    },
  });

  const data = item.data;
  const error = item.error ?? completion.error;

  const isDone = data?.status === "DONE";

  return (
    <div className="flex-1 flex flex-col w-full bg-background min-h-dvh relative">
      {/* 상단 TopBar (뒤로가기 시 명확히 /staff/roadmap으로 안전 복귀) */}
      <TopBar
        title={data?.category.name ?? "학습 카드"}
        backHref="/staff/roadmap"
        right={
          item.isFetching && !item.isLoading ? (
            <span className="text-xs font-medium text-muted bg-surface-muted px-2 py-0.5 rounded-full">
              갱신 중
            </span>
          ) : undefined
        }
      />

      {/* 스크롤 가능한 본문 영역 (하단 고정 CTA 바를 고려한 pb-36) */}
      <main className="flex-1 space-y-4 overflow-y-auto px-4 py-3 pb-36">
        {/* 로딩 스켈레톤 */}
        {item.isLoading && (
          <div className="space-y-4" aria-label="학습 내용 불러오는 중">
            <div className="h-10 w-24 motion-safe:animate-pulse rounded-lg bg-surface-muted/70" />
            <div className="h-64 motion-safe:animate-pulse rounded-3xl bg-surface-muted/60" />
            <div className="h-32 motion-safe:animate-pulse rounded-2xl bg-surface-muted/50" />
          </div>
        )}

        {/* 에러 상태 */}
        {error && (
          <Card className="space-y-3 p-5 text-center">
            <p role="alert" className="text-xs font-semibold text-danger-500">
              {message(error)}
            </p>
            <Button
              variant="secondary"
              size="md"
              className="min-h-[44px]"
              onClick={() => void item.refetch()}
            >
              최신 내용 다시 불러오기
            </Button>
          </Card>
        )}

        {/* 정상 데이터 렌더링 */}
        {data && (
          <>
            {/* 핵심 업무 카드 */}
            <Card className="space-y-3.5 p-5 border-border shadow-sm">
              {/* 상단 배지 메타데이터 */}
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="neutral">{data.category.name}</Badge>
                {isDone && (
                  <Badge tone="brand">✅ 학습 완료됨</Badge>
                )}
                <span className="ml-auto text-xs font-medium text-muted">
                  버전 #{data.published_version_id}
                </span>
              </div>

              {/* 카드 제목 */}
              <h1 className="text-lg font-extrabold text-foreground leading-snug">
                {data.title}
              </h1>

              {/* 카드 핵심 업무 본문 */}
              <div className="border-t border-border/60 pt-3">
                <p className="whitespace-pre-wrap text-base font-normal leading-relaxed text-foreground/90 select-text">
                  {data.content}
                </p>
              </div>
            </Card>

            {/* 보조 영역: 근거 원본 (Evidence) */}
            <section className="space-y-2.5 pt-1" aria-labelledby="evidence-heading">
              <div className="flex items-center justify-between px-1">
                <h2 id="evidence-heading" className="text-xs font-bold text-muted uppercase tracking-wider">
                  매장 원본 근거
                </h2>
                <span className="text-xs text-muted">
                  {data.evidence.length}건
                </span>
              </div>

              {data.evidence.length === 0 ? (
                <Card className="p-4 text-center text-xs text-muted">
                  연결된 원본 근거가 없습니다.
                </Card>
              ) : (
                data.evidence.map((evidence) => (
                  <Card
                    key={evidence.evidence_id}
                    className="space-y-2 p-3.5 border-border/80 bg-surface/80 text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <strong className="font-semibold text-foreground truncate">
                        📎 {evidence.source.title ?? "매장 등록 업무 자료"}
                      </strong>
                      {evidence.source.source_type && (
                        <span className="text-xs text-muted shrink-0 bg-surface-muted px-1.5 py-0.5 rounded">
                          {evidence.source.source_type}
                        </span>
                      )}
                    </div>

                    {evidence.excerpt && (
                      <blockquote className="border-l-2 border-brand-400 bg-brand-50/40 p-2.5 rounded-r text-sm leading-relaxed text-foreground/80 italic">
                        &ldquo;{evidence.excerpt}&rdquo;
                      </blockquote>
                    )}

                    {evidence.source.read_url && (
                      <div className="pt-1">
                        <a
                          href={evidence.source.read_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex min-h-[44px] items-center text-xs font-bold text-brand-600 hover:text-brand-700 transition-colors"
                        >
                          원본 자료 열기 ↗
                        </a>
                      </div>
                    )}
                  </Card>
                ))
              )}
            </section>
          </>
        )}

        {/* 유효하지 않은 itemId */}
        {!itemId && (
          <Card className="p-6 text-center text-sm text-danger-500">
            잘못된 학습 링크입니다.
          </Card>
        )}
      </main>

      {/* 하단 엄지 영역 고정 CTA (Bottom Fixed CTA) */}
      {data && (
        <div className="fixed bottom-0 left-0 right-0 z-20 mx-auto w-full max-w-[480px] border-t border-border bg-surface/95 backdrop-blur-md px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] shadow-[0_-4px_12px_rgba(0,0,0,0.06)]">
          <div className="space-y-1.5">
            <Button
              size="lg"
              variant={isDone ? "secondary" : "primary"}
              className="w-full min-h-[50px] font-bold text-sm shadow-sm transition-transform active:scale-[0.98]"
              loading={completion.isPending}
              loadingLabel="학습 상태 저장 중"
              onClick={() => completion.mutate(!isDone)}
            >
              {isDone ? "완료 취소" : "이해했어요"}
            </Button>
            <p className="text-center text-xs text-muted">
              이 업무를 학습한 것으로 기록됩니다.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
