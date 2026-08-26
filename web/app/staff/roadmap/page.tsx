"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import { Buddy } from "@/components/ui";
import { useApp } from "@/lib/store";
import { ROADMAP_BG_SIZE } from "@/lib/mock";
import type { RoadmapNode } from "@/lib/types";
import { getRoadmap, patchRoadmapItem, type RoadmapStageDto } from "@/lib/api";
import type { NodeStatus } from "@/lib/types";

// 단계의 항목이 전부 DONE 이면 그 칸도 DONE. 앞이 끝나야 다음이 열린다.
function nodeStatuses(stages: RoadmapStageDto[]): NodeStatus[] {
  let prevDone = true;
  return stages.map((st) => {
    const done = st.items.length > 0 && st.items.every((i) => i.status === "DONE");
    const status: NodeStatus = done ? "DONE" : prevDone ? "IN_PROGRESS" : "LOCKED";
    prevDone = done;
    return status;
  });
}

export default function RoadmapPage() {
  const router = useRouter();
  const { state, dispatch } = useApp();
  const [openNodeId, setOpenNodeId] = useState<string | null>(null);
  const openNode = state.roadmap.find((n) => n.id === openNodeId) ?? null;
  const openIndex = openNode ? state.roadmap.findIndex((n) => n.id === openNode.id) : -1;

  const hearts = useMemo(() => Array.from({ length: 3 }, (_, i) => i < state.hearts), [state.hearts]);

  // 화면의 노드는 그림 위 좌표를 가진 연출용이고, 진도율의 근거는 DB 의 roadmap_items 다.
  // 노드 순서와 단계 순서를 맞춰 두고, 노드를 끝내면 그 단계의 항목을 전부 DONE 으로 보낸다.
  const [stages, setStages] = useState<RoadmapStageDto[]>([]);
  const syncing = useRef(false);

  useEffect(() => {
    if (!state.token) return;
    let cancelled = false;
    getRoadmap(state.token)
      .then((r) => {
        if (cancelled) return;
        setStages(r.stages);
        dispatch({ type: "SET_ROADMAP_STATUS", statuses: nodeStatuses(r.stages) });
      })
      .catch(() => {
        // 백엔드 미연결 — 화면은 로컬 상태로 계속 돈다
      });
    return () => {
      cancelled = true;
    };
  }, [state.token, dispatch]);

  // 점주 대시보드는 store_members.progress_rate 를 2초 폴링한다.
  // 항목을 DONE 으로 보내면 백엔드가 그 값을 다시 계산하므로 곧바로 반영된다.
  const syncStage = useCallback(
    async (nodeIndex: number) => {
      const token = state.token;
      const stage = stages[nodeIndex];
      if (!token || !stage || syncing.current) return;
      syncing.current = true;
      try {
        for (const item of stage.items) {
          if (item.status !== "DONE") {
            await patchRoadmapItem(item.item_id, "DONE", token);
          }
        }
        const fresh = await getRoadmap(token);
        setStages(fresh.stages);
        dispatch({ type: "SET_ROADMAP_STATUS", statuses: nodeStatuses(fresh.stages) });
      } catch {
        // 실패해도 화면 진행은 막지 않는다. 다음 노드에서 다시 시도된다
      } finally {
        syncing.current = false;
      }
    },
    [state.token, stages, dispatch]
  );

  return (
    <div className="min-h-dvh w-full flex justify-center bg-brand-500">
      <div className="w-full max-w-[480px] min-h-dvh flex flex-col relative">
        {/* HUD — 스트릭 · 하트 */}
        <div className="sticky top-0 z-20 h-14 px-4 flex items-center bg-white/95 backdrop-blur">
          <Link
            href="/role"
            aria-label="뒤로가기"
            className="w-9 h-9 rounded-full flex items-center justify-center text-brand-700 hover:bg-surface-muted transition-colors"
          >
            ←
          </Link>
          <div className="w-[90px] flex items-center gap-1.5 pl-1">
            <span className="text-lg">🔥</span>
            <span className="text-xs font-semibold text-brand-700">{state.streakDays}일 연속</span>
          </div>
          <div className="flex-1 text-center text-[15px] font-bold text-brand-700">AskBuddy</div>
          <div className="w-[90px] flex items-center justify-end gap-1">
            {hearts.map((full, i) => (
              <span key={i} className={full ? "opacity-100" : "opacity-30 grayscale"}>
                ❤️
              </span>
            ))}
          </div>
        </div>

        {/* Buddy AI — 로드맵 위에 상시로 둔다. 모르는 게 생겼을 때
            미션을 진행하던 중이든 아니든 바로 물어볼 수 있어야 한다 */}
        <div className="px-4 pt-3 pb-1">
          <button
            onClick={() => router.push("/staff/chat")}
            className="w-full bg-white rounded-[20px] px-4 py-3.5 flex items-center gap-3 shadow-[0_6px_24px_rgba(0,0,0,0.12)] active:scale-[0.99] transition-transform"
          >
            <Buddy size={44} />
            <div className="flex-1 text-left min-w-0">
              <p className="text-[15px] font-bold text-foreground">Buddy AI</p>
              <p className="text-[13px] text-muted mt-0.5">편하게 질문 하세요~</p>
            </div>
            <span className="text-muted">→</span>
          </button>
        </div>

        {/* 경로 캔버스 */}
        <div className="flex-1 flex flex-col justify-center py-4">
          <div
            className="relative w-full"
            style={{ aspectRatio: `${ROADMAP_BG_SIZE.width} / ${ROADMAP_BG_SIZE.height}` }}
          >
            <Image
              src="/images/roadmap-bg.png"
              alt=""
              fill
              className="object-contain select-none"
              sizes="480px"
              priority
            />
            {state.roadmap.map((node) => (
              <NodeButton
                key={node.id}
                node={node}
                current={node.status === "IN_PROGRESS"}
                onOpen={() => node.status !== "LOCKED" && setOpenNodeId(node.id)}
              />
            ))}
          </div>
        </div>

        {openNode && (
          <NodeDetailOverlay
            node={openNode}
            step={`${openIndex + 1}/${state.roadmap.length} 단계`}
            onClose={() => setOpenNodeId(null)}
            onComplete={() => {
              dispatch({ type: "COMPLETE_ROADMAP_NODE", nodeId: openNode.id });
              void syncStage(openIndex);
              setOpenNodeId(null);
            }}
          />
        )}
      </div>
    </div>
  );
}

function NodeButton({
  node,
  current,
  onOpen,
}: {
  node: RoadmapNode;
  current: boolean;
  onOpen: () => void;
}) {
  const locked = node.status === "LOCKED";
  const done = node.status === "DONE";
  const leftPct = (node.pos.x / ROADMAP_BG_SIZE.width) * 100;
  const topPct = (node.pos.y / ROADMAP_BG_SIZE.height) * 100;

  return (
    <div
      className="absolute"
      style={{ left: `${leftPct}%`, top: `${topPct}%`, transform: "translate(-50%, -50%)", zIndex: current ? 12 : 10 }}
    >
      {current && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5">
          <Buddy size={52} />
        </div>
      )}
      {current && (
        <div
          className="absolute rounded-full animate-pulse pointer-events-none bg-accent-500/30"
          style={{ width: 76, height: 76, left: "50%", top: "50%", transform: "translate(-50%, -50%)" }}
        />
      )}
      <button
        onClick={onOpen}
        disabled={locked}
        className={`relative z-10 w-14 h-14 rounded-full flex items-center justify-center text-2xl transition-transform active:scale-90 focus:outline-none ${
          done
            ? "bg-brand-500 shadow-[0_4px_18px_rgba(91,191,106,0.55)] ring-2 ring-white/90"
            : current
              ? "bg-accent-500 shadow-[0_4px_18px_rgba(240,123,138,0.42)] ring-[3px] ring-white/90"
              : "bg-white/20 ring-1 ring-white/40"
        }`}
      >
        {done ? "✓" : locked ? "🔒" : current ? "⭐" : node.emoji}
      </button>
      <div className="absolute top-full left-1/2 -translate-x-1/2 mt-1.5 w-[88px] text-center pointer-events-none">
        <span
          className={`block text-[11px] leading-tight ${
            current ? "font-bold text-white" : locked ? "text-white/60" : "font-semibold text-white/90"
          }`}
          style={!locked ? { textShadow: "0 1px 5px rgba(0,0,0,0.45)" } : undefined}
        >
          {node.label}
        </span>
      </div>
    </div>
  );
}

function NodeDetailOverlay({
  node,
  step,
  onClose,
  onComplete,
}: {
  node: RoadmapNode;
  step: string;
  onClose: () => void;
  onComplete: () => void;
}) {
  return (
    <div className="absolute inset-0 z-30 flex flex-col bg-background">
      <div className="shrink-0 flex items-center px-4 bg-surface border-b border-border h-14">
        <button
          onClick={onClose}
          className="w-9 h-9 flex items-center justify-center rounded-full hover:bg-surface-muted transition-colors"
        >
          ←
        </button>
        <div className="flex-1 text-center">
          <p className="text-[17px] font-bold text-foreground leading-tight">{node.label}</p>
          <p className="text-xs text-muted mt-0.5">{step}</p>
        </div>
        <div className="w-9" />
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 pb-24">
        <div className="space-y-3">
          {node.details.map((card, i) =>
            card.type === "doc" ? (
              <div key={i} className="bg-surface p-4 rounded-2xl">
                <p className="text-[15px] font-bold text-foreground mb-3">{card.title}</p>
                {card.image && (
                  <div className="relative w-full h-[200px] rounded-xl overflow-hidden mb-3">
                    <Image src={card.image} alt={card.title} fill className="object-cover" />
                  </div>
                )}
                <p className="text-[13px] text-foreground/80 leading-relaxed whitespace-pre-line">{card.text}</p>
                {card.tags && card.tags.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-3">
                    {card.tags.map((tag) => (
                      <span key={tag} className="bg-brand-50 text-brand-700 text-[11px] font-medium px-2.5 py-1 rounded-full">
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div key={i} className="flex items-start gap-3 p-4 rounded-2xl bg-background border border-border">
                <Buddy size={32} />
                <p className="text-[13px] text-brand-700 leading-relaxed pt-0.5">{card.text}</p>
              </div>
            )
          )}
        </div>
      </div>

      <div className="absolute bottom-0 left-0 right-0 px-4 pb-6 pt-4 bg-gradient-to-t from-background via-background to-transparent">
        <button
          onClick={onComplete}
          className="w-full h-[52px] rounded-2xl bg-brand-500 text-white font-bold text-[15px] shadow-[0_4px_16px_rgba(91,191,106,0.38)] active:scale-[0.98] transition-transform"
        >
          이 단계 완료!
        </button>
      </div>
    </div>
  );
}
