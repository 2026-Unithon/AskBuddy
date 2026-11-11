"use client";

import { useState } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { BackButton, Button, ConfirmDialog, Empty, ErrorInline, PageHeader, Screen, Skeleton, focusRing } from "@/components/kit";
import { apiErrorMessage, deleteIngestSource, type UploadedSource } from "@/lib/api";
import { queryKeys, sourcesQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

/** 올린 자료 관리(계획 8 Task 5, 사장님). 지우면 원본 파일만 지워지고 만든 카드는 남는다(D20) */
export function SourcesScreen() {
  const { state } = useApp();
  const client = useQueryClient();
  const sources = useInfiniteQuery(sourcesQuery(state.token, state.storeId));
  const items = sources.data?.pages.flatMap((page) => page.items) ?? [];
  // 지울지 묻는 자료(화면 상태)
  const [asking, setAsking] = useState<UploadedSource | null>(null);

  const remove = useMutation({
    mutationFn: (sourceId: number) => deleteIngestSource(sourceId, state.token!),
    onSuccess: () => {
      setAsking(null);
      // 자료 목록, 그리고 근거 표시('인용 끊김')가 바뀌는 카드 목록을 서버 값으로 맞춘다
      void client.invalidateQueries({ queryKey: queryKeys.sources(state.storeId) });
      void client.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) });
    },
  });

  return (
    <Screen>
      <BackButton parent="/owner/settings/app" />
      <PageHeader title="올린 자료 관리" />
      {sources.isLoading && <Skeleton className="h-40" />}
      {sources.error && (
        <ErrorInline
          message={apiErrorMessage(sources.error, "올린 자료를 불러오지 못했어요.")}
          onRetry={() => void sources.refetch()}
          retrying={sources.isRefetching}
        />
      )}
      {sources.data && items.length === 0 && <Empty title="올린 자료가 없어요" description="자료를 올리면 여기에 보여요." />}
      {items.length > 0 && (
        <ul className="flex flex-col divide-y divide-empty">
          {items.map((source) => {
            const name = source.title || "이름 없는 자료";
            return (
              <li key={source.source_id} className="flex min-h-14 items-center gap-3 py-2">
                <span className="min-w-0 flex-1 truncate text-[16px] font-bold text-ink">{name}</span>
                <button
                  type="button"
                  aria-label={`${name} 지우기`}
                  onClick={() => {
                    remove.reset();
                    setAsking(source);
                  }}
                  className={`min-h-11 shrink-0 rounded-full px-3 text-[14px] font-bold text-danger-700 ${focusRing}`}
                >
                  지우기
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {sources.hasNextPage && (
        <Button variant="secondary" loading={sources.isFetchingNextPage} onClick={() => void sources.fetchNextPage()}>
          더 보기
        </Button>
      )}
      {asking && (
        <ConfirmDialog
          open
          title="이 자료를 지울까요?"
          description="원본 파일은 지워지고, 만든 카드는 남아요."
          confirmLabel="지우기"
          tone="danger"
          loading={remove.isPending}
          error={remove.error ? apiErrorMessage(remove.error, "지우지 못했어요. 다시 눌러 주세요.") : null}
          onConfirm={() => remove.mutate(asking.source_id)}
          onCancel={() => setAsking(null)}
        />
      )}
    </Screen>
  );
}
