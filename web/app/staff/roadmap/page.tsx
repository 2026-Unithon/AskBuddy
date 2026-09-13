"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Badge, Buddy, Button, Card } from "@/components/ui";
import { ApiError, type RoadmapDto } from "@/lib/api";
import { roadmapQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

function message(error: unknown) {
  return error instanceof ApiError
    ? error.detail || "로드맵을 불러오지 못했어요."
    : "서버에 연결할 수 없습니다.";
}

function findContinueTarget(roadmapData: RoadmapDto | undefined) {
  const continueItemId = roadmapData?.continue_item_id;
  if (!continueItemId || !roadmapData?.stages) return null;
  for (const stage of roadmapData.stages) {
    const found = stage.items.find((it) => it.item_id === continueItemId);
    if (found) {
      return { item: found, stageName: stage.name };
    }
  }
  return null;
}

export default function RoadmapPage() {
  const { state } = useApp();
  const roadmap = useQuery(roadmapQuery(state.token, state.storeId, state.userId));
  const counts = roadmap.data?.counts;
  const progress = counts?.total ? Math.round((counts.done / counts.total) * 100) : 0;

  // continue_item_id에 해당하는 카드를 탐색
  const continueTarget = findContinueTarget(roadmap.data);

  const allCompleted = counts && counts.total > 0 && counts.done === counts.total;


  return (
    <div className="flex-1 flex flex-col w-full bg-background min-h-dvh">
      {/* 컴팩트 상단 헤더 */}
      <header className="shrink-0 bg-brand-700 px-4 pt-5 pb-5 text-white shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <Buddy size={40} className="drop-shadow-sm" />
            <div className="min-w-0">
              <p className="text-[11px] font-medium text-white/75 truncate">
                {state.displayName ?? "직원"}님의 업무 학습
              </p>
              <h1 className="text-lg font-bold truncate text-white">
                {roadmap.data?.store.name ?? state.storeName}
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {roadmap.isFetching && !roadmap.isLoading && (
              <span className="text-[10px] bg-white/15 px-2 py-0.5 rounded-full text-white/90">
                갱신 중
              </span>
            )}
            <Link
              href="/role"
              className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-xs font-semibold text-white/80 hover:text-white transition-colors active:scale-95"
              aria-label="역할 선택 화면으로 나가기"
            >
              나가기
            </Link>
          </div>
        </div>

        {/* 전체 진도 바 */}
        <div className="mt-4 bg-black/10 rounded-xl p-3 border border-white/10">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-white/90">전체 학습 진도</span>
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-white/75">
                {counts ? `${counts.done}/${counts.total} 완료` : "-"}
              </span>
              <span className="font-extrabold text-white text-sm">{progress}%</span>
            </div>
          </div>
          <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-white/20">
            <div
              className="h-full rounded-full bg-accent-500 transition-all duration-500"
              style={{ width: `${progress}%` }}
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`전체 학습 진도 ${progress}%`}
            />
          </div>
        </div>
      </header>

      {/* 메인 학습 콘텐츠 (하단 탭 높이 64px + 여백 고려 pb-24) */}
      <main className="flex-1 space-y-4 px-4 py-4 pb-24 overflow-y-auto">
        {/* 사장님 수정 재확인 알림 배너 */}
        {counts && counts.reconfirm_required > 0 && (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-2xl border border-warn-500/40 bg-warn-50 p-3.5 text-foreground shadow-sm"
          >
            <span className="text-xl shrink-0" aria-hidden="true">
              🔄
            </span>
            <div className="space-y-0.5 min-w-0">
              <strong className="text-xs font-bold text-warn-700 block">
                {counts.reconfirm_required}개 업무 내용이 바뀌었어요
              </strong>
              <p className="text-[11px] text-muted leading-tight">
                최신 내용을 다시 확인하면 완료 상태로 갱신됩니다.
              </p>
            </div>
          </div>
        )}

        {/* 최우선 CTA: 오늘 이어서 학습할 카드 (Resume Card) */}
        {continueTarget && (
          <div className="rounded-2xl border-2 border-brand-500 bg-gradient-to-b from-brand-50/50 to-surface p-4 shadow-sm">
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <span className="text-[11px] font-bold text-brand-700 bg-brand-100/70 px-2 py-0.5 rounded-full">
                {continueTarget.stageName}
              </span>
              <span className="text-[11px] font-medium text-brand-600">오늘의 추천 학습</span>
            </div>
            <h2 className="text-base font-bold text-foreground line-clamp-2">
              {continueTarget.item.title}
            </h2>
            <div className="mt-3 flex items-center justify-between gap-2">
              <Badge
                tone={
                  continueTarget.item.status === "RECONFIRM_REQUIRED" ? "warn" : "neutral"
                }
              >
                {continueTarget.item.status === "RECONFIRM_REQUIRED"
                  ? "다시 확인 필요"
                  : "미완료"}
              </Badge>
              <Link
                href={`/staff/items/${continueTarget.item.item_id}`}
                className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-brand-500 px-4 text-xs font-bold text-white shadow-sm transition-transform active:scale-[0.97] hover:bg-brand-600"
              >
                이어서 학습하기 →
              </Link>
            </div>
          </div>
        )}

        {/* 전체 완료 시 축하 메시지 */}
        {allCompleted && !continueTarget && (
          <Card className="p-4 text-center space-y-1.5 bg-brand-50/60 border-brand-200">
            <p className="text-base font-bold text-brand-700">🎉 모든 학습 카드를 완료했어요!</p>
            <p className="text-xs text-muted">
              새로운 업무가 추가되거나 내용이 변경되면 바로 여기에 업데이트됩니다.
            </p>
          </Card>
        )}

        {/* 초기 로딩 스켈레톤 */}
        {roadmap.isLoading && (
          <div className="space-y-3" aria-label="로드맵 불러오는 중">
            {[0, 1, 2].map((item) => (
              <div
                key={item}
                className="h-24 animate-pulse rounded-2xl bg-surface-muted/60"
              />
            ))}
          </div>
        )}

        {/* 오류 상태 */}
        {roadmap.error && (
          <Card className="space-y-3 p-5 text-center">
            <p role="alert" className="text-xs font-semibold text-danger-500">
              {message(roadmap.error)}
            </p>
            <Button
              variant="secondary"
              size="md"
              className="min-h-[44px]"
              onClick={() => void roadmap.refetch()}
            >
              다시 시도
            </Button>
          </Card>
        )}

        {/* 빈 상태 */}
        {!roadmap.isLoading && !roadmap.error && (counts?.total ?? 0) === 0 && (
          <Card className="space-y-2 p-6 text-center">
            <Buddy size={48} className="mx-auto opacity-70" />
            <p className="text-sm font-bold text-foreground">아직 공개된 학습 카드가 없어요</p>
            <p className="text-xs text-muted leading-relaxed">
              사장님이 업무 자료를 올리고 카드를 공개하면 여기에 단계별로 나타납니다.
            </p>
          </Card>
        )}

        {/* 카테고리별 카드 목록 */}
        {roadmap.data?.stages.map((stage) => (
          <section
            key={stage.category_id}
            className="space-y-2 pt-1"
            aria-labelledby={`stage-${stage.category_id}`}
          >
            <div className="flex items-center justify-between px-1">
              <h2
                id={`stage-${stage.category_id}`}
                className="text-xs font-bold text-brand-700 uppercase tracking-wider"
              >
                {stage.name}
              </h2>
              <span className="text-[11px] text-muted font-medium">
                {stage.items.filter((i) => i.status === "DONE").length}/{stage.items.length}
              </span>
            </div>

            <div className="space-y-2">
              {stage.items.map((item) => {
                const isDone = item.status === "DONE";
                const isReconfirm = item.status === "RECONFIRM_REQUIRED";

                return (
                  <Link
                    key={item.item_id}
                    href={`/staff/items/${item.item_id}`}
                    className="block group"
                  >
                    <Card
                      className={`flex min-h-[58px] items-center gap-3 p-3.5 transition-all active:scale-[0.98] ${
                        isReconfirm
                          ? "border-warn-500/50 bg-warn-50/30 hover:border-warn-500"
                          : isDone
                          ? "border-border/60 bg-surface hover:border-brand-200"
                          : "border-border bg-surface hover:border-brand-300"
                      }`}
                    >
                      {/* 상태 아이콘 */}
                      <span className="text-lg shrink-0" aria-hidden="true">
                        {isDone ? "✅" : isReconfirm ? "🔄" : "📖"}
                      </span>

                      {/* 제목 (말줄임 안전성) */}
                      <span
                        className={`min-w-0 flex-1 text-xs font-semibold leading-snug truncate ${
                          isDone ? "text-foreground/75" : "text-foreground"
                        }`}
                      >
                        {item.title}
                      </span>

                      {/* 상태 배지 */}
                      <Badge
                        tone={isDone ? "brand" : isReconfirm ? "warn" : "neutral"}
                      >
                        {isDone ? "완료" : isReconfirm ? "다시 확인" : "시작"}
                      </Badge>

                      <span
                        className="text-muted text-xs transition-transform group-hover:translate-x-0.5"
                        aria-hidden="true"
                      >
                        →
                      </span>
                    </Card>
                  </Link>
                );
              })}
            </div>
          </section>
        ))}
      </main>
    </div>
  );
}
