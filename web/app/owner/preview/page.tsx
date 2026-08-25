"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { Badge, BottomCta, Button, Card, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";

export default function PreviewPage() {
  const router = useRouter();
  const { state } = useApp();

  // D3 — 신뢰도 0.6(60) 미만은 검수 화면 상단에 우선 노출한다.
  const sorted = useMemo(
    () => [...state.knowledgeSections].sort((a, b) => a.confidence - b.confidence),
    [state.knowledgeSections]
  );

  return (
    <Shell>
      <TopBar title="학습 미리보기" />
      <div className="flex-1 overflow-y-auto px-6 pt-2 pb-4 flex flex-col gap-4">
        <p className="text-sm text-muted">
          Buddy가 파악한 내용이에요. 신뢰도가 낮은 항목부터 확인해주세요.
        </p>

        {sorted.map((section) => {
          const low = section.confidence < 60;
          return (
            <Card key={section.id} className={`p-4 ${low ? "border-warn-500/60" : ""}`}>
              <div className="flex items-center gap-3 mb-3">
                <span className="text-xl">{section.icon}</span>
                <span className="flex-1 font-semibold text-sm">{section.label}</span>
                <Badge tone={low ? "warn" : "brand"}>
                  {low ? "⚠️ " : ""}신뢰도 {section.confidence}%
                </Badge>
              </div>
              <ul className="space-y-1.5">
                {section.items.map((item) => (
                  <li key={item.id} className="text-sm text-foreground/90 pl-3 relative">
                    <span className="absolute left-0 text-brand-500">·</span>
                    {item.text}
                  </li>
                ))}
              </ul>
              {low && (
                <p className="text-xs text-warn-700 mt-2">
                  확인이 필요해요. 사장님이 직접 검수한 뒤 승인해주세요.
                </p>
              )}
            </Card>
          );
        })}

        <button
          onClick={() => router.push("/owner/upload")}
          className="text-sm text-brand-700 font-medium py-3 text-center"
        >
          + 자료 추가로 등록하기
        </button>
      </div>
      <BottomCta>
        <Button size="lg" className="w-full" onClick={() => router.push("/owner/complete")}>
          검수 완료, 학습 마치기
        </Button>
      </BottomCta>
    </Shell>
  );
}
