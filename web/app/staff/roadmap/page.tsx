"use client";

import Image from "next/image";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Buddy } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { roadmapQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

const NODE_POSITIONS = [
  { left: "65%", top: "69%" },
  { left: "29%", top: "54%" },
  { left: "57%", top: "44%" },
  { left: "57%", top: "32%" },
  { left: "43%", top: "22%" },
  { left: "22%", top: "13%" },
  { left: "35%", top: "4%" },
] as const;

function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.detail || "로드맵을 불러오지 못했어요."
    : "서버에 연결할 수 없습니다.";
}

export default function RoadmapPage() {
  const { state } = useApp();
  const roadmap = useQuery(roadmapQuery(state.token, state.storeId, state.userId));
  const items = roadmap.data?.stages.flatMap((stage) =>
    stage.items.map((item) => ({ ...item, stageName: stage.name }))
  ) ?? [];
  const foundActiveIndex = items.findIndex(
    (item) => item.item_id === roadmap.data?.continue_item_id
  );
  const activeIndex = foundActiveIndex >= 0 ? foundActiveIndex : 0;
  const activeItem = items[activeIndex];

  return (
    <main className="relative min-h-dvh w-full overflow-hidden bg-brand-500 text-foreground">
      <Image
        src="/images/roadmap-bg.png"
        alt="잔디 위에 놓인 AskBuddy 학습 길"
        fill
        priority
        sizes="(max-width: 480px) 100vw, 480px"
        className="object-cover object-center"
      />

      <header className="absolute inset-x-0 top-0 z-20 flex h-14 items-center bg-white/95 px-5 backdrop-blur-xl">
        <div className="flex w-[90px] items-center gap-1.5 text-xs font-medium text-brand-700">
          <span className="text-lg" aria-hidden="true">🔥</span>
          <span>3일 연속</span>
        </div>
        <p className="flex-1 text-center text-[15px] font-bold text-brand-700">AskBuddy</p>
        <div className="flex w-[90px] justify-end text-lg tracking-[-4px]" aria-label="남은 하트 3개">❤️❤️❤️</div>
      </header>

      <section data-testid="roadmap-path" className="absolute inset-x-0 bottom-[104px] top-14 z-10" aria-label="학습 로드맵">
        {items.slice(0, NODE_POSITIONS.length).map((item, index) => {
          const isDone = item.status === "DONE";
          const isActive = item.item_id === roadmap.data?.continue_item_id || (foundActiveIndex < 0 && index === 0);
          const isLocked = !isDone && !isActive && index > activeIndex;
          return (
            <Link
              key={item.item_id}
              href={isLocked ? "#" : `/staff/items/${item.item_id}`}
              aria-disabled={isLocked}
              onClick={(event) => isLocked && event.preventDefault()}
              className="absolute -translate-x-1/2"
              style={NODE_POSITIONS[index]}
            >
              {isActive && (
                <Buddy size={92} className="absolute bottom-[38px] left-1/2 z-10 -translate-x-1/2 drop-shadow-[0_10px_14px_rgba(255,255,255,0.75)]" />
              )}
              <span className={`relative flex h-14 w-14 items-center justify-center rounded-full border-2 text-2xl shadow-lg ${
                isActive
                  ? "scale-110 border-white/90 bg-accent-500 text-white shadow-accent-500/50"
                  : isDone
                    ? "border-white/90 bg-brand-500 text-white shadow-brand-800/30"
                    : "border-white/40 bg-surface-muted text-brand-700/35"
              }`}>
                <span aria-hidden="true">{isActive ? "★" : isDone ? "✓" : "▢"}</span>
              </span>
              <span className={`absolute top-16 left-1/2 w-28 -translate-x-1/2 text-center text-sm font-bold drop-shadow-sm ${isLocked ? "text-white/55" : "text-white"}`}>
                {item.title}
              </span>
            </Link>
          );
        })}
      </section>

      {roadmap.isLoading && (
        <div data-testid="roadmap-loading" aria-label="로드맵 불러오는 중" className="absolute inset-0 z-30 bg-brand-700/25 pt-24 backdrop-blur-sm">
          <div className="mx-auto h-14 w-14 animate-pulse rounded-full bg-white/80" />
          <div className="mx-auto mt-24 h-14 w-14 animate-pulse rounded-full bg-white/70" />
          <div className="absolute inset-x-4 bottom-4 h-20 animate-pulse rounded-[20px] bg-white/85" />
        </div>
      )}
      {roadmap.error && (
        <div data-testid="roadmap-error" className="absolute inset-x-4 top-20 z-30 rounded-2xl bg-white p-4 text-center shadow-lg">
          <p className="text-sm font-semibold text-danger-600">{errorMessage(roadmap.error)}</p>
          <button type="button" onClick={() => void roadmap.refetch()} className="mt-3 rounded-xl bg-brand-500 px-4 py-2 text-xs font-bold text-white">다시 시도</button>
        </div>
      )}
      {!roadmap.isLoading && !roadmap.error && items.length === 0 && (
        <div data-testid="roadmap-empty" className="absolute inset-x-4 top-20 z-30 rounded-2xl bg-white/95 p-5 text-center shadow-lg">
          <Buddy size={46} className="mx-auto" />
          <p className="mt-2 text-sm font-bold">아직 공개된 학습 카드가 없어요</p>
        </div>
      )}

      {activeItem && (
        <Link data-testid="roadmap-continue" href={`/staff/items/${activeItem.item_id}`} className="absolute inset-x-4 bottom-4 z-20 flex min-h-20 items-center gap-3 rounded-[20px] bg-white px-4 py-3.5 shadow-[0_-2px_12px_rgba(0,0,0,0.10),0_6px_12px_rgba(0,0,0,0.12)]">
          <span className="grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-full bg-accent-50"><Buddy size={44} /></span>
          <span className="min-w-0">
            <strong className="block truncate text-[13px]">{activeItem.title} 미션 시작! ☕</strong>
            <span className="mt-0.5 block truncate text-xs text-[#5a6a63]">{activeItem.stageName} 순서대로 따라가 봐요 🌿</span>
          </span>
        </Link>
      )}
    </main>
  );
}
