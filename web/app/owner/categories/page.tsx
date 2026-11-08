"use client";

import { useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BackButton,
  Banner,
  Button,
  ConfirmDialog,
  ErrorInline,
  PageHeader,
  Screen,
  Sheet,
  Skeleton,
  Icon,
  SortableList,
  focusRing,
  useFeedback,
} from "@/components/kit";
import { apiErrorMessage, createProductCategory, deleteProductCategory, orderProductCategories, retryReclassificationJob, updateProductCategory, type ProductCategory, type ProductCategoryList } from "@/lib/api";
import { KIND_LABEL, cardKind, type CardKind } from "@/lib/card-kind";
import { productCategoriesQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

type Removing = { id: number; name: string };
const KINDS: CardKind[] = ["RECIPE", "TASK", "INFO"];

/** 카테고리(o17a·o17b). 추가 칸은 상태를 칸에서 바로 보이고, 지우기는 휴지통에서 확인 창 뒤. */
export default function CategoriesPage() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const feedback = useFeedback();
  const categories = useQuery(productCategoriesQuery(state.token, state.storeId));
  // 입력 초안(서버 값 아님)
  const [name, setName] = useState("");
  const [removing, setRemoving] = useState<Removing | null>(null);
  // 종류를 고르는 시트·이름을 고치는 시트를 연 카테고리(화면 상태)
  const [kindFor, setKindFor] = useState<ProductCategory | null>(null);
  const [renameFor, setRenameFor] = useState<ProductCategory | null>(null);
  const [newName, setNewName] = useState("");
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
  // 종류: 분류 AI 가 정한 값을 사장님이 고친다. 근무조 고르기·목록 두 칸이 이것을 따른다
  const setKind = useMutation({
    mutationFn: ({ id, kind }: { id: number; kind: CardKind }) => updateProductCategory(id, { kind }, state.token!),
    onSuccess: async () => {
      setKindFor(null);
      await Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: queryKeys.cardDetails(state.storeId) })]);
    },
  });
  const rename = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => updateProductCategory(id, { name }, state.token!),
    onSuccess: async () => {
      setRenameFor(null);
      await Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: queryKeys.cardDetails(state.storeId) })]);
    },
  });
  // 끌어서 순서 바꾸기(o17, 계획 7 Task 9): 끄는 동안은 캐시에 바로 반영하고, 놓을 때 한 번만 저장한다
  const order = useMutation({
    mutationFn: (ids: number[]) => orderProductCategories(ids, state.token!),
    onSettled: refresh,
  });
  const dragStart = useRef<number[] | null>(null);
  const listKey = queryKeys.productCategories(state.storeId);
  const moveCategory = (key: string, dir: -1 | 1) => {
    const current = queryClient.getQueryData<ProductCategoryList>(listKey)?.items ?? categories.data?.items ?? [];
    dragStart.current ??= current.map((c) => c.category_id);
    const next = [...current];
    const index = next.findIndex((c) => c.category_id === Number(key));
    [next[index], next[index + dir]] = [next[index + dir], next[index]];
    void queryClient.cancelQueries({ queryKey: listKey });
    queryClient.setQueryData<ProductCategoryList>(listKey, (data) => (data ? { ...data, items: next } : data));
  };
  const saveOrder = () => {
    const before = dragStart.current;
    dragStart.current = null;
    const ids = (queryClient.getQueryData<ProductCategoryList>(listKey)?.items ?? []).map((c) => c.category_id);
    if (before && before.join() !== ids.join()) order.mutate(ids);
  };
  const retry = useMutation({
    mutationFn: (jobId: number) => retryReclassificationJob(jobId, state.token!),
    onSuccess: () => void refresh(),
  });
  const reclass = categories.data?.reclassification;
  const trimmed = name.trim();
  // 'Coffee'·'coffee' 처럼 대소문자만 다른 이름도 같은 이름으로 본다
  const duplicate = Boolean(trimmed) && Boolean(categories.data?.items.some((c) => c.name.trim().toLowerCase() === trimmed.toLowerCase()));
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
      {order.error && <ErrorInline message={apiErrorMessage(order.error, "순서를 저장하지 못했어요.")} onRetry={() => order.variables && order.mutate(order.variables)} />}
      {categories.data && (
        <SortableList
          items={categories.data.items.map((c) => ({ ...c, key: String(c.category_id), label: c.name }))}
          canMove={() => !order.isPending}
          onMove={moveCategory}
          onEnd={saveOrder}
          renderItem={(category) => {
            const kind = KIND_LABEL[cardKind(category)];
            const row = (
              <div data-category="" className="flex min-h-14 items-center gap-2 rounded-[20px] bg-surface pl-[18px] pr-3 shadow-card">
                {category.is_system ? (
                  <p className="min-w-0 flex-1 truncate text-[16px] font-bold text-ink">{category.name}</p>
                ) : (
                  <button
                    type="button"
                    aria-label={`${category.name} 이름 고치기`}
                    onClick={() => {
                      setNewName(category.name);
                      setRenameFor(category);
                    }}
                    className={`min-w-0 flex-1 truncate text-left text-[16px] font-bold text-ink ${focusRing}`}
                  >
                    {category.name}
                  </button>
                )}
                <button
                  type="button"
                  aria-label={`${category.name} 종류 바꾸기, 지금 ${kind}`}
                  onClick={() => setKindFor(category)}
                  className={`relative flex h-8 shrink-0 items-center gap-1 rounded-full bg-empty px-3 text-[13px] font-bold text-primary before:absolute before:inset-x-0 before:-inset-y-1.5 ${focusRing}`}
                >
                  {kind}
                  <span aria-hidden>▾</span>
                </button>
                {/* 밀어서 지우기 대신 늘 보이는 휴지통(2026-11-08 사용자). 누르면 확인 창 */}
                {!category.is_system && (
                  <button
                    type="button"
                    aria-label={`${category.name} 지우기`}
                    onClick={() => setRemoving({ id: category.category_id, name: category.name })}
                    className={`flex size-10 shrink-0 items-center justify-center rounded-full text-ink-muted hover:text-danger-700 ${focusRing}`}
                  >
                    <Icon name="trash" size={18} />
                  </button>
                )}
              </div>
            );
            // 순서 바꾸기 목록은 줄 사이가 없어서 카드 사이 간격을 여기서 둔다
            return <div className="py-1">{row}</div>;
          }}
        />
      )}
      <Sheet open={renameFor !== null} onClose={() => !rename.isPending && setRenameFor(null)} title="카테고리 이름 고치기">
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (renameFor && newName.trim() && !rename.isPending) rename.mutate({ id: renameFor.category_id, name: newName.trim() });
          }}
        >
          <label className="flex flex-col gap-1.5">
            <span className="text-[14px] font-bold text-ink">이름</span>
            <input
              value={newName}
              maxLength={50}
              onChange={(event) => {
                setNewName(event.target.value);
                if (rename.error) rename.reset();
              }}
              className={`min-h-12 rounded-[14px] bg-surface px-4 text-[16px] text-ink shadow-card outline-none ${focusRing}`}
            />
          </label>
          {rename.error && <ErrorInline message={apiErrorMessage(rename.error, "이름을 바꾸지 못했어요.")} />}
          <Button type="submit" loading={rename.isPending} disabled={!newName.trim()}>
            저장
          </Button>
        </form>
      </Sheet>
      <Sheet open={kindFor !== null} onClose={() => !setKind.isPending && setKindFor(null)} title={`'${kindFor?.name ?? ""}'는 어떤 카드인가요?`}>
        {setKind.error && <ErrorInline message={apiErrorMessage(setKind.error, "종류를 바꾸지 못했어요.")} />}
        <div className="flex flex-col gap-2">
          {KINDS.map((kind) => {
            const current = kindFor !== null && cardKind(kindFor) === kind;
            return (
              <Button
                key={kind}
                variant={current ? "primary" : "secondary"}
                loading={setKind.isPending && setKind.variables?.kind === kind}
                disabled={setKind.isPending}
                onClick={() => kindFor && (current ? setKindFor(null) : setKind.mutate({ id: kindFor.category_id, kind }))}
              >
                {KIND_LABEL[kind]}
              </Button>
            );
          })}
        </div>
      </Sheet>
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
