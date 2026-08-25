"use client";

import { useRouter } from "next/navigation";
import { BottomCta, Button, Card, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { BUSINESS_TYPES } from "@/lib/types";

export default function CategoryPage() {
  const router = useRouter();
  const { state, dispatch } = useApp();

  const canContinue = state.businessType !== null;

  return (
    <Shell>
      <TopBar title="업종 · 업무 선택" />
      <div className="flex-1 overflow-y-auto px-6 pt-2 pb-4 flex flex-col gap-8">
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-muted">업종을 선택해주세요</h2>
          <div className="grid grid-cols-3 gap-2.5">
            {BUSINESS_TYPES.map((b) => {
              const selected = state.businessType === b.key;
              return (
                <button
                  key={b.key}
                  onClick={() => dispatch({ type: "SET_BUSINESS_TYPE", value: b.key })}
                  className={`flex flex-col items-center gap-1.5 rounded-[var(--radius-md)] py-4 border transition-colors ${
                    selected
                      ? "border-brand-500 bg-brand-50 text-brand-700"
                      : "border-border bg-surface text-foreground hover:border-brand-200"
                  }`}
                >
                  <span className="text-2xl">{b.emoji}</span>
                  <span className="text-xs font-medium">{b.label}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-muted">가르칠 업무 카테고리를 켜주세요</h2>
          <Card className="divide-y divide-border">
            {state.categories.map((c) => (
              <button
                key={c.key}
                onClick={() => dispatch({ type: "TOGGLE_CATEGORY", key: c.key })}
                className="w-full flex items-center gap-3 px-4 py-3.5 text-left"
              >
                <span className="text-xl">{c.icon}</span>
                <span className="flex-1 text-sm font-medium">{c.label}</span>
                <span
                  className={`w-11 h-6 rounded-full relative transition-colors ${
                    c.enabled ? "bg-brand-500" : "bg-surface-muted"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
                      c.enabled ? "translate-x-[22px]" : "translate-x-0.5"
                    }`}
                  />
                </span>
              </button>
            ))}
          </Card>
        </section>
      </div>
      <BottomCta>
        <Button
          size="lg"
          className="w-full"
          disabled={!canContinue}
          onClick={() => router.push("/owner/upload")}
        >
          다음
        </Button>
      </BottomCta>
    </Shell>
  );
}
