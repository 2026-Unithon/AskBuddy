"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Badge, BottomCta, Button, Card, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { listCards, type KnowledgeCard } from "@/lib/api";
import type { KnowledgeSection } from "@/lib/types";

const CATEGORY_ICON: Record<string, string> = {
  오픈업무: "🌅",
  재고정리: "📦",
  음료제작: "☕",
  마감업무: "🌙",
  베이킹: "🥐",
};

// 카드는 한 장씩 오고 화면은 카테고리 묶음으로 보여준다. 여기서 접는다.
function groupByCategory(cards: KnowledgeCard[]): KnowledgeSection[] {
  const buckets = new Map<string, KnowledgeCard[]>();
  for (const card of cards) {
    const key = card.category ?? "미분류";
    const list = buckets.get(key);
    if (list) list.push(card);
    else buckets.set(key, [card]);
  }
  return [...buckets.entries()].map(([label, group]) => ({
    id: `cat-${label}`,
    categoryKey: label,
    label,
    icon: CATEGORY_ICON[label] ?? "📋",
    // 카테고리 신뢰도는 그 안 카드들의 평균이다. 낮은 카드가 하나라도 있으면 눈에 띈다.
    confidence: Math.round(
      group.reduce((sum, c) => sum + Number(c.confidence), 0) / group.length
    ),
    items: group.map((c) => ({ id: `card-${c.id}`, text: c.title })),
  }));
}

export default function PreviewPage() {
  const router = useRouter();
  const { state, dispatch } = useApp();
  const [live, setLive] = useState(false);

  // 실제 매장 지식을 불러온다. 실패하면 mock 이 그대로 남아 데모가 끊기지 않는다.
  useEffect(() => {
    let cancelled = false;
    listCards(state.storeSlug, state.token ?? undefined)
      .then((cards) => {
        if (cancelled || cards.length === 0) return;
        dispatch({ type: "SET_KNOWLEDGE_SECTIONS", sections: groupByCategory(cards) });
        setLive(true);
      })
      .catch(() => {
        // 백엔드 미연결 — mock 유지
      });
    return () => {
      cancelled = true;
    };
  }, [state.storeSlug, state.token, dispatch]);

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
          {!live && " (예시 데이터 — 백엔드에 연결되면 실제 카드로 바뀝니다)"}
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
