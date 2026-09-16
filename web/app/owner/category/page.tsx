"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BottomCta, Button, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { BUSINESS_TYPES } from "@/lib/types";
import { ApiError, updateCategories } from "@/lib/api";
import { categoriesQuery, queryKeys } from "@/lib/query";

// 이번 릴리스는 카페만 구현한다. 나머지 업종은 기본 카테고리가 없어
// 자료를 올려도 카드가 만들어지지 않는다 — 고를 수 없게 막는다.
const IMPLEMENTED: string[] = ["CAFE"];

const CATEGORY_ICON: Record<string, string> = {
  오픈업무: "🌅",
  재고정리: "📦",
  음료제작: "☕",
  마감업무: "🌙",
  베이킹: "🥐",
};

export default function CategoryPage() {
  const router = useRouter();
  const { state, dispatch } = useApp();
  const queryClient = useQueryClient();
  const categories = useQuery(categoriesQuery(state.token, state.storeId));
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const rows = (categories.data ?? []).map((row) => ({
    ...row,
    is_enabled: overrides[row.category_name] ?? row.is_enabled,
  }));
  const save = useMutation({
    mutationFn: () => updateCategories(
      rows.map((row) => ({ category_name: row.category_name, is_enabled: row.is_enabled })),
      state.token!
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.categories(state.storeId) });
      router.push("/owner/upload");
    },
  });

  async function handleNext() {
    // 토글은 화면에서 즉시 반영하고, 넘어갈 때 한 번만 저장한다.
    if (state.token) {
      save.mutate();
      return;
    }
    router.push("/owner/upload");
  }

  const canContinue = state.businessType !== null;

  return (
    <Shell>
      <TopBar title="업종 선택" backHref="/owner/intent" />
      <div className="flex-1 overflow-y-auto px-5 pt-1 pb-4 flex flex-col">
        <p className="text-sm text-muted">우리 매장의 업종을 골라주세요</p>

        <div className="grid grid-cols-3 gap-2.5 pt-4 pb-8">
          {BUSINESS_TYPES.map((b) => {
            const selected = state.businessType === b.key;
            const ready = IMPLEMENTED.includes(b.key);
            return (
              <button
                key={b.key}
                disabled={!ready}
                onClick={() => dispatch({ type: "SET_BUSINESS_TYPE", value: b.key })}
                className={`flex flex-col items-center gap-1.5 rounded-2xl py-4 border transition-colors ${
                  selected
                    ? "border-brand-500 bg-brand-50 text-brand-700"
                    : ready
                      ? "border-border bg-surface text-foreground"
                      : "border-border bg-surface-muted text-muted/60 cursor-not-allowed"
                }`}
              >
                <span className="text-2xl">{b.emoji}</span>
                <span className="text-xs font-bold">{b.label}</span>
                {!ready && <span className="text-[10px] text-muted/70">준비 중</span>}
              </button>
            );
          })}
        </div>

        {state.businessType && (
          <div className="animate-[fadeIn_0.25s_ease-out]">
            <h2 className="text-base font-bold text-brand-700">업무 카테고리</h2>
            <p className="text-xs text-muted/80 mt-0.5">우리 매장에서 안 하는 항목은 꺼주세요</p>

            <div className="flex flex-col gap-2.5 pt-3">
              {categories.isPending && (
                <div className="space-y-2.5" aria-label="업무 카테고리 불러오는 중">
                  {[0, 1, 2].map((item) => (
                    <div key={item} className="h-14 rounded-2xl bg-surface-muted animate-pulse" />
                  ))}
                </div>
              )}
              {categories.isError && (
                <div role="alert" className="rounded-2xl border border-danger-200 bg-danger-50 p-4">
                  <p className="text-sm font-semibold text-danger-700">업무 카테고리를 불러오지 못했어요</p>
                  <button
                    type="button"
                    className="mt-3 min-h-11 rounded-xl border border-danger-200 px-4 text-sm font-bold text-danger-700"
                    onClick={() => void categories.refetch()}
                  >
                    다시 시도
                  </button>
                </div>
              )}
              {categories.isSuccess && rows.length === 0 && (
                <div className="rounded-2xl border border-border bg-surface p-4 text-sm leading-6 text-muted">
                  등록된 업무 카테고리가 없습니다. 관리자에게 문의해주세요.
                </div>
              )}
              {rows.map((c) => (
                <button
                  key={c.category_name}
                  onClick={() => setOverrides((current) => ({
                    ...current,
                    [c.category_name]: !c.is_enabled,
                  }))}
                  className="w-full flex items-center gap-3 rounded-2xl bg-surface px-4 py-4 text-left shadow-[0_1px_2px_-1px_rgba(0,0,0,0.10),0_1px_3px_rgba(0,0,0,0.10)]"
                >
                  <span className="text-xl">{CATEGORY_ICON[c.category_name] ?? "📋"}</span>
                  <span className="flex-1 text-sm font-semibold">{c.category_name}</span>
                  <span
                    className={`w-12 h-6 rounded-full relative transition-colors ${
                      c.is_enabled ? "bg-brand-500" : "bg-surface-muted"
                    }`}
                  >
                    <span
                      className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                        c.is_enabled ? "translate-x-[26px]" : "translate-x-1"
                      }`}
                    />
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <BottomCta>
        <Button
          size="lg"
          className="w-full"
          disabled={!canContinue || categories.isPending || categories.isError || rows.length === 0 || save.isPending}
          onClick={handleNext}
        >
          {save.isPending ? "저장 중…" : "다음으로 →"}
        </Button>
        {save.error && (
          <p className="mt-2 text-center text-xs font-medium text-danger-500">
            {save.error instanceof ApiError ? save.error.detail || "저장에 실패했어요" : "서버에 연결할 수 없습니다"}
          </p>
        )}
      </BottomCta>
    </Shell>
  );
}
