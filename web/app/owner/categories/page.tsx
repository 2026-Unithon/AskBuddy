"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BackButton,
  Banner,
  Button,
  ConfirmDialog,
  ErrorInline,
  PageHeader,
  Screen,
  Skeleton,
  SwipeRow,
  useFeedback,
} from "@/components/kit";
import { apiErrorMessage, createProductCategory, deleteProductCategory, retryReclassificationJob } from "@/lib/api";
import { productCategoriesQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

type Removing = { id: number; name: string };

/** 카테고리(o17a·o17b). 추가 칸은 상태를 칸에서 바로 보이고, 지우기는 밀어서 확인 창 뒤. */
export default function CategoriesPage() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const feedback = useFeedback();
  const categories = useQuery(productCategoriesQuery(state.token, state.storeId));
  // 입력 초안(서버 값 아님)
  const [name, setName] = useState("");
  const [removing, setRemoving] = useState<Removing | null>(null);
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.productCategories(state.storeId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
    ]);
  const create = useMutation({
    mutationFn: (categoryName: string) => createProductCategory(categoryName, categories.data?.items.length ?? 0, state.token!),
    onSuccess: () => {
      setName("");
      feedback.toast("카테고리를 추가했어요");
      void refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (category: Removing) => deleteProductCategory(category.id, state.token!),
    onSuccess: () => {
      setRemoving(null);
      feedback.toast("카테고리를 지웠어요");
      void refresh();
    },
  });
  const retry = useMutation({
    mutationFn: (jobId: number) => retryReclassificationJob(jobId, state.token!),
    onSuccess: () => void refresh(),
  });
  const reclass = categories.data?.reclassification;
  const trimmed = name.trim();
  const duplicate = Boolean(trimmed) && Boolean(categories.data?.items.some((c) => c.name.trim() === trimmed));
  const fieldError = duplicate ? "이미 있는 카테고리예요" : create.error ? apiErrorMessage(create.error, "카테고리를 추가하지 못했어요.") : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (trimmed && !duplicate && !create.isPending) create.mutate(trimmed);
  }

  return (
    <Screen>
      <BackButton parent="/owner/settings" />
      <PageHeader title="카테고리" />
      <form onSubmit={submit} className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <input
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              if (create.error) create.reset();
            }}
            maxLength={50}
            placeholder="새 카테고리"
            aria-label="새 카테고리 이름"
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={fieldError ? "category-error" : undefined}
            className={`min-h-12 min-w-0 flex-1 rounded-[14px] bg-surface px-4 text-[16px] text-ink shadow-card outline-none focus:ring-2 ${
              fieldError ? "ring-2 ring-danger-500 focus:ring-danger-500" : "focus:ring-primary"
            }`}
          />
          <Button type="submit" className="min-h-12 w-auto! shrink-0 whitespace-nowrap px-5 py-2.5!" loading={create.isPending} disabled={!trimmed || duplicate}>
            추가
          </Button>
        </div>
        {fieldError && (
          <p id="category-error" role="alert" className="px-1 text-[13px] font-semibold text-danger-700">
            {fieldError}
          </p>
        )}
      </form>
      {reclass && (reclass.status === "QUEUED" || reclass.status === "RUNNING") && <Banner tone="info">카드를 다시 나누는 중이에요</Banner>}
      {reclass?.status === "FAILED" && (
        <Banner tone="danger" action={{ label: retry.isPending ? "다시 하는 중" : "다시", onClick: () => !retry.isPending && retry.mutate(reclass.job_id) }}>
          카드를 다시 나누지 못했어요
        </Banner>
      )}
      {retry.error && <ErrorInline message={apiErrorMessage(retry.error, "다시 나누기를 시작하지 못했어요.")} />}
      {categories.isLoading && <Skeleton className="h-48" />}
      {categories.error && (
        <ErrorInline message={apiErrorMessage(categories.error, "카테고리를 불러오지 못했어요.")} onRetry={() => void categories.refetch()} retrying={categories.isFetching} />
      )}
      <ul className="flex flex-col gap-2">
        {categories.data?.items.map((category) => {
          const row = (
            <div className="flex min-h-14 items-center rounded-[20px] bg-surface px-[18px] shadow-card">
              <p className="truncate text-[16px] font-bold text-ink">{category.name}</p>
            </div>
          );
          return (
            <li key={category.category_id} data-category="">
              {category.is_system ? (
                row
              ) : (
                <SwipeRow
                  left={{
                    label: "지우기",
                    ariaLabel: `${category.name} 지우기`,
                    tone: "danger",
                    onAction: () => setRemoving({ id: category.category_id, name: category.name }),
                  }}
                >
                  {row}
                </SwipeRow>
              )}
            </li>
          );
        })}
      </ul>
      <ConfirmDialog
        open={Boolean(removing)}
        title={`'${removing?.name ?? ""}' 카테고리를 지울까요?`}
        description="직접 옮긴 카드는 기타로 가요."
        confirmLabel="지우기"
        tone="danger"
        loading={remove.isPending}
        error={remove.error ? apiErrorMessage(remove.error, "카테고리를 지우지 못했어요.") : null}
        onConfirm={() => removing && remove.mutate(removing)}
        onCancel={() => {
          remove.reset();
          setRemoving(null);
        }}
      />
    </Screen>
  );
}
