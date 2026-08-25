"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { BuddyBubble, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { listReviewCards, type ReviewCard } from "@/lib/api";
import type { KnowledgeSection } from "@/lib/types";

const CATEGORY_ICON: Record<string, string> = {
  오픈업무: "🌅",
  재고정리: "📦",
  음료제작: "☕",
  마감업무: "🌙",
  베이킹: "🥐",
};

// 카드는 한 장씩 오고 화면은 카테고리 묶음으로 보여준다. 여기서 접는다.
function groupByCategory(cards: ReviewCard[]): KnowledgeSection[] {
  const buckets = new Map<string, ReviewCard[]>();
  for (const card of cards) {
    const key = card.category_name || "미분류";
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
    items: group.map((c) => ({ id: `card-${c.card_id}`, text: c.title })),
  }));
}

export default function PreviewPage() {
  const router = useRouter();
  const { state, dispatch } = useApp();
  const [live, setLive] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // D3 — 신뢰도 0.6(60) 미만은 검수 화면 상단에 우선 노출한다.
  const sorted = useMemo(
    () => [...state.knowledgeSections].sort((a, b) => a.confidence - b.confidence),
    [state.knowledgeSections]
  );

  // 이번에 올린 자료에서 나온 카드만 보여준다.
  // /reg/cards 는 승인된 카드만 주므로 방금 등록한 건(미승인) 이 거기엔 없다.
  useEffect(() => {
    if (!state.token) return;
    let cancelled = false;

    const justUploaded = state.uploadSources
      .map((u) => u.sourceId)
      .filter((v): v is number => typeof v === "number");

    async function load(token: string) {
      if (justUploaded.length > 0) {
        const groups = await Promise.all(
          justUploaded.map((sourceId) =>
            listReviewCards(token, { sourceId, limit: 100 }).then((r) => r.cards)
          )
        );
        return groups.flat();
      }
      // 이번 세션에 올린 게 없으면(대시보드에서 바로 들어온 경우) 검수 대기 전부를 보여준다
      const res = await listReviewCards(token, { verified: false, limit: 100 });
      return res.cards;
    }

    load(state.token)
      .then((cards) => {
        if (cancelled) return;
        setLoaded(true);
        if (cards.length === 0) return;
        dispatch({ type: "SET_KNOWLEDGE_SECTIONS", sections: groupByCategory(cards) });
        setLive(true);
      })
      .catch(() => {
        // 백엔드 미연결 — mock 유지
      });
    return () => {
      cancelled = true;
    };
  }, [state.token, state.uploadSources, dispatch]);

  return (
    <Shell>
      <TopBar title="학습 미리보기" backHref="/owner/upload" />
      <div className="px-5 pt-1 pb-3">
        <BuddyBubble text="Buddy가 이렇게 이해했어요! 틀리거나 빠진 부분이 있으면 소스를 추가해주세요 😊" />
      </div>
      <div className="px-5 flex-1 overflow-y-auto pb-4 space-y-4">
        {loaded && !live && (
          <p className="text-xs text-muted -mt-1">이번에 등록한 자료에서 새로 만들어진 카드가 없어요</p>
        )}
        {!loaded && !live && (
          <p className="text-xs text-muted -mt-1">예시 데이터예요 — 백엔드에 연결되면 실제 카드로 바뀝니다</p>
        )}
        {sorted.map((s) => {
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
