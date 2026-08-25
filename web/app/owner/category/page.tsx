"use client";

import { useRouter } from "next/navigation";
import { BottomCta, Button, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { BUSINESS_TYPES } from "@/lib/types";

export default function CategoryPage() {
  const router = useRouter();
  const { state, dispatch } = useApp();

  const canContinue = state.businessType !== null;

  return (
    <Shell>
      <TopBar title="업종 선택" />
      <div className="flex-1 overflow-y-auto px-5 pt-1 pb-4 flex flex-col">
        <p className="text-sm text-muted">우리 매장의 업종을 골라주세요</p>

        <div className="grid grid-cols-3 gap-2.5 pt-4 pb-8">
          {BUSINESS_TYPES.map((b) => {
            const selected = state.businessType === b.key;
            return (
              <button
                key={b.key}
                onClick={() => dispatch({ type: "SET_BUSINESS_TYPE", value: b.key })}
                className={`flex flex-col items-center gap-1.5 rounded-2xl py-4 border transition-colors ${
                  selected
                    ? "border-brand-500 bg-brand-50 text-brand-700"
                    : "border-border bg-surface text-foreground"
                }`}
              >
                <span className="text-2xl">{b.emoji}</span>
                <span className="text-xs font-bold">{b.label}</span>
              </button>
            );
          })}
        </div>

        <div>
          <h2 className="text-base font-bold text-brand-700">업무 카테고리</h2>
          <p className="text-xs text-muted/80 mt-0.5">우리 매장에서 안 하는 항목은 꺼주세요</p>
        </div>

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
      <BottomCta>
        <Button
          size="lg"
          className="w-full"
          disabled={!canContinue}
          onClick={() => router.push("/owner/upload")}
        >
          다음으로 →
        </Button>
      </BottomCta>
    </Shell>
  );
}
