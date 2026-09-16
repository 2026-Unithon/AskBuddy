"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input, Shell, TopBar } from "@/components/ui";
import {
  ApiError,
  createProductCategory,
  deleteProductCategory,
  retryReclassificationJob,
} from "@/lib/api";
import { productCategoriesQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

function message(error: unknown) {
  return error instanceof ApiError ? error.detail || "카테고리를 처리하지 못했어요." : "서버에 연결할 수 없습니다.";
}

export default function CategoriesPage() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const categories = useQuery(productCategoriesQuery(state.token, state.storeId));
  const [name, setName] = useState("");
  const refresh = () => {
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.productCategories(state.storeId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
    ]);
  };
  const create = useMutation({
    mutationFn: (categoryName: string) => createProductCategory(categoryName, categories.data?.items.length ?? 0, state.token!),
    onSuccess: () => { setName(""); refresh(); },
  });
  const remove = useMutation({
    mutationFn: (categoryId: number) => deleteProductCategory(categoryId, state.token!),
    onSuccess: refresh,
  });
  const retry = useMutation({
    mutationFn: (jobId: number) => retryReclassificationJob(jobId, state.token!),
    onSuccess: refresh,
  });
  const error = categories.error ?? create.error ?? remove.error ?? retry.error;
  const reclass = categories.data?.reclassification;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim() && !create.isPending) create.mutate(name.trim());
  }

  return (
    <Shell>
      <TopBar title="카테고리 관리" backHref="/owner/cards" />
      <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-8">
        <p className="text-xs leading-relaxed text-muted">카테고리를 바꾸면 자동 분류 카드만 백그라운드에서 다시 분류합니다. 직접 옮긴 카드는 보호됩니다.</p>
        <form onSubmit={submit} className="flex gap-2"><Input value={name} onChange={(event) => setName(event.target.value)} maxLength={50} placeholder="새 업무 카테고리" aria-label="새 카테고리 이름" /><Button type="submit" disabled={!name.trim() || create.isPending}>{create.isPending ? "추가 중" : "추가"}</Button></form>
        {reclass && (reclass.status === "QUEUED" || reclass.status === "RUNNING") && <Card className="bg-brand-50 p-4 text-xs font-semibold text-brand-700">기존 카드 재분류 중이에요. 다른 화면을 사용해도 계속 진행됩니다.</Card>}
        {reclass?.status === "FAILED" && <Card className="flex items-center gap-3 border-danger-500/30 p-4"><p className="flex-1 text-xs text-danger-500">재분류에 실패했어요. 기존 카드 분류는 유지됩니다.</p><Button variant="secondary" disabled={retry.isPending} onClick={() => retry.mutate(reclass.job_id)}>재시도</Button></Card>}
        {categories.isFetching && !categories.isLoading && <p className="text-[11px] text-muted">최신 상태 확인 중…</p>}
        {categories.isLoading && <div className="space-y-2" aria-label="카테고리 불러오는 중">{[0, 1, 2].map((item) => <div key={item} className="h-16 animate-pulse rounded-2xl bg-surface-muted" />)}</div>}
        {error && <Card className="space-y-3 p-5 text-center"><p role="alert" className="text-sm text-danger-500">{message(error)}</p><Button variant="secondary" onClick={() => void categories.refetch()}>다시 시도</Button></Card>}
        <div className="space-y-2">{categories.data?.items.map((category) => <Card key={category.category_id} className="flex min-h-16 items-center gap-3 p-4"><div className="flex-1"><p className="text-sm font-bold">{category.name}</p><p className="text-[11px] text-muted">{category.is_system ? "필수 시스템 카테고리" : "사용자 카테고리"}</p></div>{!category.is_system && <Button variant="secondary" disabled={remove.isPending} onClick={() => { if (window.confirm(`'${category.name}' 카테고리를 삭제할까요? 수동 분류 카드는 기타로 이동합니다.`)) remove.mutate(category.category_id); }}>삭제</Button>}</Card>)}</div>
      </div>
    </Shell>
  );
}
