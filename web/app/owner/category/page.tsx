"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BottomCta, Button, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { BUSINESS_TYPES } from "@/lib/types";
import { listCategories, updateCategories } from "@/lib/api";

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
  const [saving, setSaving] = useState(false);

  // 매장 생성 시 백엔드가 카페 기본 카테고리를 넣어둔다. 그걸 그대로 받아 쓴다.
  useEffect(() => {
    if (!state.token) return;
    let cancelled = false;
    listCategories(state.token)
      .then((rows) => {
        if (cancelled || rows.length === 0) return;
        dispatch({
          type: "SET_CATEGORIES",
          categories: rows.map((r) => ({
            key: r.category_name,
            label: r.category_name,
            icon: CATEGORY_ICON[r.category_name] ?? "📋",
            enabled: r.is_enabled,
          })),
        });
      })
      .catch(() => {
        // 백엔드 미연결 — mock 카테고리 유지
      });
    return () => {
      cancelled = true;
    };
  }, [state.token, dispatch]);

  async function handleNext() {
    // 토글은 화면에서 즉시 반영하고, 넘어갈 때 한 번만 저장한다.
    if (state.token) {
      setSaving(true);
      try {
        await updateCategories(
          state.categories.map((c) => ({ category_name: c.key, is_enabled: c.enabled })),
          state.token
        );
      } catch {
        // 저장 실패해도 흐름은 막지 않는다 — 켜짐 여부는 추출 품질에만 영향
      } finally {
        setSaving(false);
      }
    }
    router.push("/owner/upload");
  }

  const canContinue = state.businessType !== null;

  return (
    <Shell>
      <TopBar title="업종 선택" />
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
              {state.categories.map((c) => (
                <button
                  key={c.key}
                  onClick={() => dispatch({ type: "TOGGLE_CATEGORY", key: c.key })}
                  className="w-full flex items-center gap-3 rounded-2xl bg-surface px-4 py-4 text-left shadow-[0_1px_2px_-1px_rgba(0,0,0,0.10),0_1px_3px_rgba(0,0,0,0.10)]"
                >
                  <span className="text-xl">{c.icon}</span>
                  <span className="flex-1 text-sm font-semibold">{c.label}</span>
                  <span
                    className={`w-12 h-6 rounded-full relative transition-colors ${
                      c.enabled ? "bg-brand-500" : "bg-surface-muted"
                    }`}
                  >
                    <span
                      className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                        c.enabled ? "translate-x-[26px]" : "translate-x-1"
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
          disabled={!canContinue || saving}
          onClick={handleNext}
        >
          {saving ? "저장 중…" : "다음으로 →"}
        </Button>
      </BottomCta>
    </Shell>
  );
}
