"use client";

import { useState } from "react";
import { Badge, Card, ProgressBar, Shell, TopBar } from "@/components/ui";
import { StaffTabBar } from "@/components/StaffTabBar";
import { useApp } from "@/lib/store";
import type { NodeStatus } from "@/lib/types";

const STATUS_LABEL: Record<NodeStatus, string> = {
  DONE: "완료",
  IN_PROGRESS: "진행 중",
  LOCKED: "잠김",
};

export default function RoadmapPage() {
  const { state, dispatch, progressPct } = useApp();
  const [openId, setOpenId] = useState<string | null>(
    state.roadmap.find((n) => n.status === "IN_PROGRESS")?.id ?? null
  );

  return (
    <Shell>
      <TopBar title="로드맵" />
      <div className="flex-1 overflow-y-auto px-6 pt-2 pb-4 flex flex-col gap-5">
        <div className="space-y-2">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-semibold text-muted">전체 진행도</span>
            <span className="text-sm font-bold text-brand-700">{progressPct}%</span>
          </div>
          <ProgressBar pct={progressPct} />
        </div>

        <div className="flex flex-col gap-3">
          {state.roadmap.map((node) => {
            const locked = node.status === "LOCKED";
            const open = openId === node.id;
            return (
              <Card key={node.id} className={locked ? "opacity-60" : ""}>
                <button
                  disabled={locked}
                  onClick={() => setOpenId(open ? null : node.id)}
                  className="w-full flex items-center gap-3.5 p-4 text-left disabled:cursor-not-allowed"
                >
                  <div
                    className={`w-12 h-12 rounded-2xl flex items-center justify-center text-xl shrink-0 ${
                      node.status === "DONE"
                        ? "bg-brand-500 text-white"
                        : node.status === "IN_PROGRESS"
                          ? "bg-brand-100 text-brand-700"
                          : "bg-surface-muted text-muted"
                    }`}
                  >
                    {locked ? "🔒" : node.status === "DONE" ? "✓" : node.emoji}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold">{node.label}</p>
                    <p className="text-xs text-muted mt-0.5">
                      {node.items.filter((i) => i.done).length}/{node.items.length} 완료
                    </p>
                  </div>
                  <Badge tone={node.status === "DONE" ? "brand" : "neutral"}>
                    {STATUS_LABEL[node.status]}
                  </Badge>
                </button>

                {open && !locked && (
                  <div className="px-4 pb-4 space-y-2 border-t border-border pt-3">
                    <p className="text-xs text-muted italic">&ldquo;{node.introMessage}&rdquo;</p>
                    {node.items.map((item) => (
                      <label
                        key={item.id}
                        className="flex items-center gap-2.5 py-1.5 text-sm cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={item.done}
                          onChange={() =>
                            dispatch({
                              type: "TOGGLE_ROADMAP_ITEM",
                              nodeId: node.id,
                              itemId: item.id,
                            })
                          }
                          className="w-4 h-4 rounded accent-[var(--brand-500)]"
                        />
                        <span className={item.done ? "line-through text-muted" : ""}>
                          {item.text}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      </div>
      <StaffTabBar />
    </Shell>
  );
}
