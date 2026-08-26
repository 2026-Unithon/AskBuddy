"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BuddyBubble, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { approveCards, listReviewCards, type ReviewCard } from "@/lib/api";
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
  // 같은 내용이 여러 자료에서 반복해 나온다. 화면에 세 번 찍히면 읽을 수 없으므로
  // 제목+본문이 같으면 한 줄로 합친다.
  const seen = new Set<string>();
  const unique = cards.filter((c) => {
    const key = `${c.title}\u0000${c.content}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  const buckets = new Map<string, ReviewCard[]>();
  for (const card of unique) {
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
    items: group.map((c) => ({
      id: `card-${c.card_id}`,
      text: c.title,
      detail: c.content,
    })),
  }));
}

export default function PreviewPage() {
  const router = useRouter();
  const fromDashboard = useSearchParams().get("from") === "dashboard";
  const backHref = fromDashboard ? "/owner/dashboard" : "/owner/upload";
  const { state, dispatch } = useApp();
  const [live, setLive] = useState(false);
  const [loaded, setLoaded] = useState(false);
  // 승인 대상 card_id. 화면은 카테고리로 묶여 있어 따로 들고 있어야 한다
  const [pendingIds, setPendingIds] = useState<number[]>([]);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);

  // "학습 완료" = 점주 승인이다. 이 순간 카드가 검색 대상이 되고 임베딩이 만들어진다.
  // 백엔드가 승인과 임베딩을 한 트랜잭션에 묶으므로, 성공했다면 벡터까지 들어간 것이다.
  async function handleFinish() {
    if (!state.token || pendingIds.length === 0) {
      router.push("/owner/complete");
      return;
    }
    setApproving(true);
    setApproveError(null);
    try {
      const results = await approveCards(pendingIds, state.token);
      const failed = results.filter((r) => !r.is_verified);
      if (failed.length > 0) {
        // 일부만 실패해도 그냥 넘어가면 검색에 안 잡히는 카드가 생긴다
        setApproveError(
          `${failed.length}건 저장 실패 — ${failed[0].error ?? "알 수 없는 오류"}`
        );
        return;
      }
      setPendingIds([]);
      router.push("/owner/complete");
    } catch (e) {
      setApproveError(
        e instanceof Error ? e.message : "지식 저장에 실패했어요. 다시 눌러주세요"
      );
    } finally {
      setApproving(false);
    }
  }

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
        setPendingIds(cards.filter((x) => !x.is_verified).map((x) => x.card_id));
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
      <TopBar title="학습 미리보기" backHref={backHref} />
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
                    <div className="min-w-0">
                      <p className="text-foreground font-semibold">{item.text}</p>
                      {item.detail && (
                        <p className="text-xs text-muted mt-0.5 leading-relaxed">{item.detail}</p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
              {/* 승인 전에는 "확인 필요", 승인 뒤에는 "검증 완료" 로 바뀐다 */}
              {pendingIds.length === 0 ? (
                <p className="text-xs text-brand-600 mt-3 font-semibold flex items-center gap-1">
                  <span aria-hidden>✅</span> 검증 완료 · 신입이 물어보면 답할 수 있어요
                </p>
              ) : (
                low && (
                  <p className="text-xs text-warn-700 mt-3 font-medium">
                    확인이 필요해요. 검수 후 승인해주세요.
                  </p>
                )
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
        {approveError && (
          <div role="alert" className="mb-3 flex items-start gap-2 rounded-2xl bg-danger-50 px-4 py-3 text-danger-700">
            <span className="text-base leading-5">⚠️</span>
            <p className="flex-1 text-sm font-medium leading-5">{approveError}</p>
          </div>
        )}
        <button
          disabled={approving}
          onClick={handleFinish}
          className="w-full py-4 bg-brand-700 text-white rounded-2xl font-bold text-lg active:scale-95 transition-all shadow-[0_6px_22px_rgba(46,107,60,0.4)]"
        >
          {approving ? "지식으로 저장하는 중…" : "🎉 학습 완료!"}
        </button>
        <p className="text-xs text-center text-muted mt-2 font-medium">{pendingIds.length > 0 ? `${pendingIds.length}건을 매장 지식으로 저장해요` : "저장 완료 · 이제 신입이 물어볼 수 있어요"}</p>
      </div>
    </Shell>
  );
}
