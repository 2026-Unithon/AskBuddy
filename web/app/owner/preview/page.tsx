"use client";

import { useRouter } from "next/navigation";
import { BuddyBubble, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";

export default function PreviewPage() {
  const router = useRouter();
  const { state } = useApp();

  return (
    <Shell>
      <TopBar title="학습 미리보기" />
      <div className="px-5 pt-1 pb-3">
        <BuddyBubble text="Buddy가 이렇게 이해했어요! 틀리거나 빠진 부분이 있으면 소스를 추가해주세요 😊" />
      </div>
      <div className="px-5 flex-1 overflow-y-auto pb-4 space-y-4">
        {state.knowledgeSections.map((s) => {
          const low = s.confidence < 60;
          return (
            <div key={s.id} className="bg-surface rounded-3xl p-5 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xl">{s.icon}</span>
                  <h3 className="font-bold text-brand-700">{s.label}</h3>
                </div>
                <span
                  className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                    low ? "text-warn-700 bg-warn-50" : "text-brand-500 bg-brand-50"
                  }`}
                >
                  {low && "⚠️ "}
                  {s.confidence}%
                </span>
              </div>
              <div className="h-1.5 bg-surface-muted rounded-full mb-4 overflow-hidden">
                <div
                  className={`h-full rounded-full ${low ? "bg-warn-500" : "bg-brand-500"}`}
                  style={{ width: `${s.confidence}%` }}
                />
              </div>
              <ul className="space-y-1.5">
                {s.items.map((item) => (
                  <li key={item.id} className="flex items-start gap-2 text-sm">
                    <span className="text-brand-500 font-bold mt-0.5 shrink-0">✓</span>
                    <span className="text-foreground font-medium">{item.text}</span>
                  </li>
                ))}
              </ul>
              {low && (
                <p className="text-xs text-warn-700 mt-3 font-medium">
                  확인이 필요해요. 검수 후 승인해주세요.
                </p>
              )}
            </div>
          );
        })}

        <button
          onClick={() => router.push("/owner/upload")}
          className="w-full py-3 rounded-2xl border-2 border-border font-semibold text-sm bg-surface active:scale-[0.98] transition-all"
        >
          ＋ 소스 추가하기
        </button>
      </div>
      <div className="px-5 pb-8 pt-4 bg-gradient-to-t from-background via-background to-transparent">
        <button
          onClick={() => router.push("/owner/complete")}
          className="w-full py-4 bg-brand-700 text-white rounded-2xl font-bold text-lg active:scale-95 transition-all shadow-[0_6px_22px_rgba(46,107,60,0.4)]"
        >
          🎉 학습 완료!
        </button>
        <p className="text-xs text-center text-muted mt-2 font-medium">완료 후 사장님께 알림이 전송돼요</p>
      </div>
    </Shell>
  );
}
