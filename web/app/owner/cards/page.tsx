"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button } from "@/components/ui";
import {
  ApiError,
  mutateProductCard,
  resolveKnowledgeProposal,
  type CardFilters,
} from "@/lib/api";
import { cardsInfiniteQuery, productCategoriesQuery, proposalsQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

import { KnowledgeCardListItem } from "@/components/owner/knowledge-card-list-item";
import { EmptyState } from "@/components/owner/empty-state";
import { InlineError } from "@/components/owner/inline-error";
import { SkeletonList } from "@/components/owner/skeleton-list";
import { OwnerPageHeader } from "@/components/owner/owner-page-header";

const STATUS_FILTERS = [
  { value: "needs_review", label: "검토 필요" },
  { value: "pending", label: "미확인" },
  { value: "approved", label: "공개됨" },
  { value: "excluded", label: "제외됨" },
  { value: "all", label: "전체" },
] as const;

export default function CardsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { state } = useApp();
  const queryClient = useQueryClient();

  const rawStatus = searchParams.get("status");
  const status = STATUS_FILTERS.some((f) => f.value === rawStatus)
    ? (rawStatus as CardFilters["status"])
    : "needs_review";

  const rawJobId = searchParams.get("job_id");
  const jobId = rawJobId && /^\d+$/.test(rawJobId) ? Number(rawJobId) : undefined;
  const rawCategoryId = searchParams.get("category_id");
  const categoryId = rawCategoryId && /^\d+$/.test(rawCategoryId) ? Number(rawCategoryId) : undefined;
  const queryText = searchParams.get("query")?.trim() ?? "";

  const [searchInput, setSearchInput] = useState(queryText);

  const filters = useMemo<CardFilters>(
    () => ({
      status,
      jobId,
      categoryId,
      query: queryText || undefined,
    }),
    [status, jobId, categoryId, queryText]
  );

  const cards = useInfiniteQuery(cardsInfiniteQuery(state.token, state.storeId, filters));
  const categories = useQuery(productCategoriesQuery(state.token, state.storeId));
  const proposals = useQuery(proposalsQuery(state.token, state.storeId));

  const items = cards.data?.pages.flatMap((page) => page.items) ?? [];
  const total = cards.data?.pages[0]?.total ?? 0;

  const pendingProposals = useMemo(
    () => proposals.data?.items.filter((p) => p.status === "PENDING_REVIEW") ?? [],
    [proposals.data?.items]
  );

  const cardAction = useMutation({
    mutationFn: ({ cardId, action }: { cardId: number; action: "approve" | "exclude" | "restore" }) =>
      mutateProductCard(cardId, action, state.token!),
    onSuccess: async (_, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.card(state.storeId, variables.cardId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.faqs(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.notificationsRoot(state.storeId) }),
      ]);
    },
  });

  const proposalAction = useMutation({
    mutationFn: ({ proposalId, action }: { proposalId: number; action: "approve" | "dismiss" }) =>
      resolveKnowledgeProposal(proposalId, action, state.token!),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.proposals(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.staff(state.storeId) }),
      ]);
    },
  });

  function setFilterStatus(nextStatus: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("status", nextStatus);
    router.replace(`/owner/cards?${params.toString()}`);
  }

  function setFilterCategory(nextCategoryId: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (nextCategoryId) {
      params.set("category_id", nextCategoryId);
    } else {
      params.delete("category_id");
    }
    router.replace(`/owner/cards?${params.toString()}`);
  }

  function handleSearchSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const params = new URLSearchParams(searchParams.toString());
    const trimmed = searchInput.trim();
    if (trimmed) {
      params.set("query", trimmed);
    } else {
      params.delete("query");
    }
    router.replace(`/owner/cards?${params.toString()}`);
  }

  const error =
    cards.error ??
    categories.error ??
    proposals.error ??
    cardAction.error ??
    proposalAction.error;
  const errorMessage =
    error instanceof ApiError
      ? error.detail || "카드 목록을 불러오지 못했어요."
      : error
      ? "서버에 연결할 수 없습니다."
      : null;

  return (
    <div className="flex-1 flex flex-col w-full bg-background min-h-dvh">
      <OwnerPageHeader
        title="카드 목록"
        subtitle={`총 ${total}개의 매장 업무 지식 카드`}
        isFetching={cards.isFetching}
        isLoading={cards.isLoading}
      />

      {/* 메인 콘텐츠 (하단 탭 바 높이 고려 pb-24) */}
      <main className="flex-1 space-y-3 px-4 py-3.5 pb-24 overflow-y-auto">
        {/* 검색 폼 */}
        <form onSubmit={handleSearchSubmit} className="flex items-center gap-2">
          <div className="relative flex-1">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="카드 제목 또는 내용 검색…"
              className="w-full min-h-[44px] rounded-xl border border-border bg-surface px-3.5 text-xs text-foreground placeholder:text-muted outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 shadow-2xs"
            />
            {searchInput && (
              <button
                type="button"
                onClick={() => {
                  setSearchInput("");
                  const params = new URLSearchParams(searchParams.toString());
                  params.delete("query");
                  router.replace(`/owner/cards?${params.toString()}`);
                }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted hover:text-foreground p-1"
                aria-label="검색어 지우기"
              >
                ✕
              </button>
            )}
          </div>
          <button
            type="submit"
            className="min-h-[44px] px-3.5 rounded-xl bg-brand-500 text-white font-bold text-xs active:scale-95 shadow-2xs hover:bg-brand-600 transition-all shrink-0"
          >
            검색
          </button>
        </form>

        {/* 카테고리 필터 셀렉트 */}
        {categories.data && categories.data.items.length > 0 && (
          <div className="flex items-center gap-2">
            <label htmlFor="category-select" className="text-xs font-bold text-muted shrink-0">
              분류:
            </label>
            <select
              id="category-select"
              value={categoryId ? String(categoryId) : ""}
              onChange={(e) => setFilterCategory(e.target.value)}
              className="flex-1 min-h-[44px] rounded-xl border border-border bg-surface px-3 text-xs font-medium text-foreground outline-none focus:border-brand-500"
            >
              <option value="">전체 카테고리</option>
              {categories.data.items.map((cat) => (
                <option key={cat.category_id} value={cat.category_id}>
                  {cat.name}
                </option>
              ))}
            </select>
            <Link
              href="/owner/categories"
              className="inline-flex min-h-[44px] shrink-0 items-center px-2 text-xs font-bold text-brand-700 active:scale-[0.95]"
            >
              관리
            </Link>
          </div>
        )}

        {/* 상태 필터 수평 스크롤 탭 */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 no-scrollbar">
          {STATUS_FILTERS.map((f) => {
            const active = status === f.value;
            return (
              <button
                key={f.value}
                type="button"
                onClick={() => setFilterStatus(f.value)}
                aria-pressed={active}
                className={`min-h-[44px] shrink-0 rounded-full px-4 text-xs font-bold transition-all active:scale-[0.95] ${
                  active
                    ? "bg-brand-700 text-white shadow-sm"
                    : "bg-surface-muted text-muted hover:text-foreground"
                }`}
              >
                {f.label}
              </button>
            );
          })}
        </div>

        {/* 오류 알림 */}
        {errorMessage && (
          <InlineError
            message={errorMessage}
            onRetry={() => {
              void Promise.all([cards.refetch(), categories.refetch(), proposals.refetch()]);
            }}
          />
        )}

        {jobId && (
          <div className="flex min-h-[44px] items-center justify-between gap-3 rounded-xl border border-brand-200 bg-brand-50 px-3 text-xs text-brand-800">
            <span>작업 #{jobId}에서 만든 카드만 표시 중이에요.</span>
            <button
              type="button"
              className="min-h-[44px] shrink-0 px-2 font-bold text-brand-700 active:scale-[0.95]"
              onClick={() => {
                const params = new URLSearchParams(searchParams.toString());
                params.delete("job_id");
                router.replace(`/owner/cards?${params.toString()}`);
              }}
            >
              필터 해제
            </button>
          </div>
        )}

        {/* 지식 보완/충돌 제안 배너 */}
        {pendingProposals.length > 0 && (
          <div className="rounded-2xl border border-accent-500/40 bg-accent-50/50 p-3.5 space-y-2">
            <div className="flex items-center justify-between">
              <strong className="text-xs font-bold text-accent-700">
                💡 점주 답변에서 도출된 새 제안 {pendingProposals.length}건
              </strong>
              <Link
                href="/owner/cards/review"
                className="text-xs font-bold text-brand-700 underline hover:text-brand-800"
              >
                일괄 검토 →
              </Link>
            </div>
            <div className="space-y-2 pt-1">
              {pendingProposals.slice(0, 2).map((proposal) => (
                <div
                  key={proposal.proposal_id}
                  className="rounded-xl bg-surface p-3 border border-border text-xs space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <Badge tone={proposal.relation_type === "CONFLICT" ? "danger" : "brand"}>
                      {proposal.relation_type === "CONFLICT" ? "충돌 검토" : "보완 제안"}
                    </Badge>
                  </div>
                  <p className="font-semibold text-foreground line-clamp-2">
                    {proposal.proposed_content}
                  </p>
                  <div className="flex justify-end gap-2 pt-1">
                    <button
                      type="button"
                      disabled={proposalAction.isPending}
                      onClick={() => proposalAction.mutate({ proposalId: proposal.proposal_id, action: "approve" })}
                      className="px-2.5 py-1 rounded-lg bg-brand-500 text-white font-bold text-[11px] active:scale-95 disabled:opacity-50"
                    >
                      승인·반영
                    </button>
                    <button
                      type="button"
                      disabled={proposalAction.isPending}
                      onClick={() => proposalAction.mutate({ proposalId: proposal.proposal_id, action: "dismiss" })}
                      className="px-2.5 py-1 rounded-lg bg-surface-muted text-muted font-bold text-[11px] active:scale-95 disabled:opacity-50"
                    >
                      기각
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 로딩 스켈레톤 */}
        {cards.isLoading && (
          <div className="space-y-2.5 pt-1">
            <SkeletonList count={5} heightClass="h-24" label="카드 목록 불러오는 중" />
          </div>
        )}

        {/* 빈 상태 */}
        {!cards.isLoading && !errorMessage && items.length === 0 && (
          <EmptyState
            icon="🗂"
            title="조건에 맞는 카드가 없어요"
            description="다른 필터를 선택하거나 새로운 업무 자료를 올려 카드를 생성해보세요."
            actionHref="/owner/upload"
            actionLabel="새 자료 올리기 →"
          />
        )}

        {/* 카드 목록 */}
        <div className="space-y-2">
          {items.map((card) => (
            <KnowledgeCardListItem
              key={card.card_id}
              card={card}
              onApprove={(id) => cardAction.mutate({ cardId: id, action: "approve" })}
              onExclude={(id) => cardAction.mutate({ cardId: id, action: "exclude" })}
              isActing={
                cardAction.isPending && cardAction.variables?.cardId === card.card_id
              }
            />
          ))}
        </div>

        {/* 무한 스크롤 / 더보기 버튼 */}
        {cards.hasNextPage && (
          <div className="pt-2 text-center">
            <Button
              variant="secondary"
              size="md"
              disabled={cards.isFetchingNextPage}
              onClick={() => void cards.fetchNextPage()}
              className="w-full min-h-[44px] text-xs font-bold active:scale-98"
            >
              {cards.isFetchingNextPage ? "추가 카드 불러오는 중…" : "다음 카드 더보기 ↓"}
            </Button>
          </div>
        )}
      </main>
    </div>
  );
}
