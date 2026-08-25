"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { StaffTabBar } from "@/components/StaffTabBar";
import { useApp } from "@/lib/store";
import type { RoadmapNode } from "@/lib/types";

const ZIGZAG = ["justify-start pl-10", "justify-center", "justify-end pr-10"];

export default function RoadmapPage() {
  const router = useRouter();
  const { state, dispatch, progressPct } = useApp();
  const currentNode = state.roadmap.find((n) => n.status === "IN_PROGRESS") ?? state.roadmap[0];
  const [openNodeId, setOpenNodeId] = useState<string | null>(null);
  const openNode = state.roadmap.find((n) => n.id === openNodeId) ?? null;

  const hearts = useMemo(() => Array.from({ length: 3 }, (_, i) => i < state.hearts), [state.hearts]);

  return (
    <div className="min-h-dvh w-full flex justify-center bg-brand-500">
      <div className="w-full max-w-[480px] min-h-dvh flex flex-col relative">
        {/* 상단 바 — 스트릭 · 하트 */}
        <div className="sticky top-0 z-20 h-14 px-4 flex items-center bg-white/95 backdrop-blur">
          <button
            aria-label="뒤로가기"
            onClick={() => router.back()}
            className="w-9 h-9 rounded-full flex items-center justify-center text-brand-700 hover:bg-surface-muted transition-colors"
          >
            ←
          </button>
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

        {/* 경로 캔버스 */}
        <div className="flex-1 relative px-2 py-10 overflow-y-auto">
          <div className="absolute left-1/2 top-4 bottom-4 w-0 border-l-2 border-dashed border-white/35 -translate-x-1/2" />
          <div className="relative flex flex-col gap-12">
            {state.roadmap.map((node, i) => (
              <div key={node.id} className={`flex ${ZIGZAG[i % ZIGZAG.length]}`}>
                <NodeButton node={node} onOpen={() => node.status !== "LOCKED" && setOpenNodeId(node.id)} />
              </div>
            ))}
          </div>
        </div>

        {/* 진행도 + 현재 미션 토스트 */}
        <div className="px-4 pb-2">
          <div className="h-1.5 rounded-full bg-white/30 overflow-hidden mb-3">
            <div
              className="h-full rounded-full bg-white transition-[width] duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          {currentNode && (
            <button
              onClick={() => setOpenNodeId(currentNode.id)}
              className="w-full bg-white rounded-[20px] px-4 py-3.5 flex items-center gap-3 shadow-[0_6px_24px_rgba(0,0,0,0.12),0_-2px_24px_rgba(0,0,0,0.10)]"
            >
              <div className="w-11 h-11 rounded-full bg-accent-100 flex items-center justify-center text-xl shrink-0">
                {currentNode.emoji}
              </div>
              <div className="flex-1 text-left min-w-0">
                <p className="text-[13px] font-bold text-foreground truncate">
                  {currentNode.label} 미션 시작!
                </p>
                <p className="text-xs text-muted mt-0.5 truncate">{currentNode.introMessage}</p>
              </div>
              <span className="text-muted">→</span>
            </button>
          )}
        </div>

        <div className="bg-background">
          <StaffTabBar />
        </div>

        {openNode && (
          <NodeSheet node={openNode} onClose={() => setOpenNodeId(null)} onToggle={(itemId) => dispatch({ type: "TOGGLE_ROADMAP_ITEM", nodeId: openNode.id, itemId })} />
        )}
      </div>
    </div>
  );
}

function NodeButton({ node, onOpen }: { node: RoadmapNode; onOpen: () => void }) {
  const locked = node.status === "LOCKED";
  const current = node.status === "IN_PROGRESS";
  const done = node.status === "DONE";
  return (
    <button onClick={onOpen} disabled={locked} className="flex flex-col items-center gap-1.5 w-20">
      <span
        className={`w-14 h-14 rounded-full flex items-center justify-center text-2xl transition-transform ${
          current
            ? "bg-accent-500 shadow-[0_4px_18px_rgba(240,123,138,0.55),0_0_0_10px_rgba(240,123,138,0.22)] ring-2 ring-white/90 scale-105"
            : done
              ? "bg-white text-brand-700 ring-2 ring-white/90"
              : "bg-white/20 ring-1 ring-white/40"
        }`}
      >
        {locked ? "🔒" : done ? "✓" : node.emoji}
      </span>
      <span
        className={`text-xs text-center leading-tight ${
          current ? "font-bold text-white" : locked ? "text-white/50" : "font-semibold text-white/90"
        }`}
      >
        {node.label}
      </span>
    </button>
  );
}

function NodeSheet({
  node,
  onClose,
  onToggle,
}: {
  node: RoadmapNode;
  onClose: () => void;
  onToggle: (itemId: string) => void;
}) {
  return (
    <div className="absolute inset-0 z-30 flex items-end">
      <button aria-label="닫기" onClick={onClose} className="absolute inset-0 bg-black/40" />
      <div className="relative w-full bg-surface rounded-t-[28px] px-6 pt-5 pb-8 max-h-[75%] overflow-y-auto">
        <div className="w-10 h-1.5 rounded-full bg-border mx-auto mb-4" />
        <div className="flex items-center gap-3 mb-1">
          <span className="text-2xl">{node.emoji}</span>
          <h2 className="text-lg font-bold text-brand-700">{node.label}</h2>
        </div>
        <p className="text-sm text-muted italic mb-4">&ldquo;{node.introMessage}&rdquo;</p>
        <div className="flex flex-col gap-1">
          {node.items.map((item) => (
            <label key={item.id} className="flex items-center gap-2.5 py-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={item.done}
                onChange={() => onToggle(item.id)}
                className="w-4 h-4 rounded accent-[var(--brand-500)]"
              />
              <span className={item.done ? "line-through text-muted" : ""}>{item.text}</span>
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
