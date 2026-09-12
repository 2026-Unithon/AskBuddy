"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, type FormEvent } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { OwnerPrimaryNav } from "@/components/owner-primary-nav";
import { Badge, BuddyBubble, Button, Card, Input, Shell, TopBar } from "@/components/ui";
import {
  ApiError,
  mutateProductCard,
  resolveKnowledgeProposal,
  type CardFilters,
  type CardListItem,
  type KnowledgeProposal,
} from "@/lib/api";
import { cardsInfiniteQuery, proposalsQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

const FILTERS = [
  ["pending", "미확인"],
  ["needs_review", "검토 필요"],
  ["approved", "공개 중"],
  ["excluded", "제외됨"],
  ["all", "전체"],
] as const;

function statusBadge(status: CardListItem["review_status"]) {
  if (status === "APPROVED") return { tone: "brand" as const, label: "공개 중" };
  if (status === "EXCLUDED") return { tone: "neutral" as const, label: "제외됨" };
  if (status === "NEEDS_REVIEW") return { tone: "danger" as const, label: "검토 필요" };
  return { tone: "warn" as const, label: "미확인" };
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.detail || "요청을 처리하지 못했어요." : "서버에 연결할 수 없습니다.";
}

export default function CardsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { state } = useApp();
  const queryClient = useQueryClient();
  const rawStatus = params.get("status");
  const status = FILTERS.some(([value]) => value === rawStatus)
    ? rawStatus as CardFilters["status"]
    : "pending";
  const rawJobId = params.get("job_id");
  const jobId = rawJobId && /^\d+$/.test(rawJobId) ? Number(rawJobId) : undefined;
  const queryText = params.get("query")?.trim() ?? "";
  const filters = useMemo<CardFilters>(() => ({ status, jobId, query: queryText || undefined }), [status, jobId, queryText]);
  const cards = useInfiniteQuery(cardsInfiniteQuery(state.token, state.storeId, filters));
  const proposals = useQuery(proposalsQuery(state.token, state.storeId));
  const items = cards.data?.pages.flatMap((page) => page.items) ?? [];
  const total = cards.data?.pages[0]?.total ?? 0;

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

  function setFilter(next: string) {
    const query = new URLSearchParams(params.toString());
    query.set("status", next);
    router.replace(`/owner/cards?${query}`);
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = new FormData(event.currentTarget).get("query");
    const search = typeof value === "string" ? value.trim() : "";
    const query = new URLSearchParams(params.toString());
    if (search) query.set("query", search);
    else query.delete("query");
    router.replace(`/owner/cards?${query}`);
  }

  return (
    <Shell>
      <TopBar title="카드 목록" backHref="/owner/dashboard" />
      <div className="px-5 pb-3"><OwnerPrimaryNav /></div>
      <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-8">
        {jobId && (
          <BuddyBubble text={`작업 #${jobId}에서 만든 카드만 보고 있어요. 오래된 링크여도 현재 카드 상태를 표시합니다.`} />
        )}

        {proposals.isLoading && <div className="h-20 animate-pulse rounded-2xl bg-surface-muted" aria-label="답변 반영 제안 불러오는 중" />}
        {(proposals.data?.items.length ?? 0) > 0 && (
          <section className="space-y-3" aria-labelledby="proposal-title">
            <div className="flex items-center justify-between">
              <h2 id="proposal-title" className="text-sm font-bold text-brand-700">답변 반영 검토</h2>
              {proposals.isFetching && <span className="text-[11px] text-muted">갱신 중…</span>}
            </div>
            {proposals.data?.items.map((proposal) => (
              <ProposalCard key={proposal.proposal_id} proposal={proposal} mutation={proposalAction} />
            ))}
          </section>
        )}
        {proposals.error && (
          <Card className="flex items-center gap-3 p-4">
            <p role="alert" className="flex-1 text-xs text-danger-500">답변 반영 제안을 불러오지 못했어요.</p>
            <Button variant="secondary" onClick={() => void proposals.refetch()}>재시도</Button>
          </Card>
        )}

        <form onSubmit={submitSearch} className="flex gap-2">
          <Input key={queryText} name="query" defaultValue={queryText} placeholder="카드 제목이나 내용 검색" aria-label="카드 검색" />
          <Button type="submit" variant="secondary">검색</Button>
        </form>
        <div className="flex justify-end"><Link href="/owner/categories" className="inline-flex min-h-11 items-center px-2 text-xs font-bold text-brand-500">카테고리 관리 →</Link></div>
        <div className="flex gap-2 overflow-x-auto pb-1" aria-label="카드 상태 필터">
          {FILTERS.map(([value, label]) => (
            <button key={value} onClick={() => setFilter(value)} className={`min-h-11 shrink-0 rounded-full px-4 text-xs font-bold ${status === value ? "bg-brand-700 text-white" : "bg-surface-muted text-muted"}`}>
              {label}
            </button>
          ))}
          {jobId && <button onClick={() => router.replace(`/owner/cards?status=${status}`)} className="min-h-11 shrink-0 rounded-full px-4 text-xs font-bold text-danger-500">작업 필터 해제</button>}
        </div>

        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-muted">{total}개</p>
          {cards.isFetching && !cards.isLoading && <span className="text-[11px] text-muted">최신 정보 확인 중…</span>}
        </div>
        {cards.isLoading && <CardsSkeleton />}
        {cards.error && (
          <Card className="space-y-3 p-5 text-center">
            <p role="alert" className="text-sm text-danger-500">{errorMessage(cards.error)}</p>
            <Button onClick={() => void cards.refetch()} variant="secondary">다시 시도</Button>
          </Card>
        )}
        {!cards.isLoading && !cards.error && items.length === 0 && (
          <Card className="space-y-2 p-6 text-center">
            <p className="text-sm font-bold">표시할 카드가 없어요.</p>
            <p className="text-xs text-muted">필터를 바꾸거나 새 자료를 업로드해 주세요.</p>
            <Link href="/owner/upload?from=dashboard" className="inline-flex min-h-11 items-center justify-center text-sm font-bold text-brand-500">자료 업로드</Link>
          </Card>
        )}
        <div className="space-y-3">
          {items.map((card) => <KnowledgeCard key={card.card_id} card={card} mutation={cardAction} />)}
        </div>
        {cards.hasNextPage && (
          <Button className="w-full" variant="secondary" disabled={cards.isFetchingNextPage} onClick={() => void cards.fetchNextPage()}>
            {cards.isFetchingNextPage ? "불러오는 중…" : "더 보기"}
          </Button>
        )}
      </div>
    </Shell>
  );
}

function KnowledgeCard({ card, mutation }: { card: CardListItem; mutation: ReturnType<typeof useMutation<unknown, Error, { cardId: number; action: "approve" | "exclude" | "restore" }>> }) {
  const badge = statusBadge(card.review_status);
  const working = mutation.isPending && mutation.variables?.cardId === card.card_id;
  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-bold">{card.title}</h3>
            <Badge tone={badge.tone}>{badge.label}</Badge>
            {card.assignment_type === "MANUAL" && <Badge tone="neutral">수동 분류</Badge>}
          </div>
          <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-xs leading-relaxed text-muted">{card.content}</p>
          <p className="mt-2 text-[11px] text-muted">{card.category?.name ?? "미분류"}{card.source?.title ? ` · ${card.source.title}` : ""}</p>
        </div>
        <Link href={`/owner/cards/${card.card_id}`} className="flex min-h-11 shrink-0 items-center px-2 text-xs font-bold text-brand-500">상세</Link>
      </div>
      {card.needs_review_reason && <p className="rounded-xl bg-danger-50 px-3 py-2 text-xs text-danger-500">{card.needs_review_reason}</p>}
      <div className="flex gap-2">
        {(card.review_status === "PENDING" || card.review_status === "NEEDS_REVIEW") && <Button disabled={working} onClick={() => mutation.mutate({ cardId: card.card_id, action: "approve" })}>공개</Button>}
        {card.review_status !== "EXCLUDED" ? (
          <Button variant="secondary" disabled={working} onClick={() => mutation.mutate({ cardId: card.card_id, action: "exclude" })}>제외</Button>
        ) : (
          <Button disabled={working} onClick={() => mutation.mutate({ cardId: card.card_id, action: "restore" })}>복원</Button>
        )}
        {working && <span className="self-center text-xs text-muted">처리 중…</span>}
      </div>
      {mutation.error && mutation.variables?.cardId === card.card_id && <p role="alert" className="text-xs text-danger-500">{errorMessage(mutation.error)}</p>}
    </Card>
  );
}

function ProposalCard({ proposal, mutation }: { proposal: KnowledgeProposal; mutation: ReturnType<typeof useMutation<unknown, Error, { proposalId: number; action: "approve" | "dismiss" }>> }) {
  const working = mutation.isPending && mutation.variables?.proposalId === proposal.proposal_id;
  return (
    <Card className="space-y-3 border-accent-500/40 p-4">
      <div className="flex items-center gap-2"><Badge tone={proposal.relation_type === "CONFLICT" ? "danger" : "warn"}>{proposal.relation_type === "CONFLICT" ? "충돌" : "보완"}</Badge><p className="text-xs text-muted">직원 질문: {proposal.question_text}</p></div>
      {proposal.current_content && <div><p className="text-[11px] font-bold text-muted">현재 공개 내용</p><p className="mt-1 text-xs whitespace-pre-wrap">{proposal.current_content}</p></div>}
      <div><p className="text-[11px] font-bold text-brand-700">제안 내용</p><p className="mt-1 text-sm font-semibold">{proposal.proposed_title}</p><p className="mt-1 text-xs whitespace-pre-wrap">{proposal.proposed_content}</p></div>
      {proposal.reason && <p className="text-[11px] text-muted">판단 근거: {proposal.reason}</p>}
      <div className="flex gap-2"><Button disabled={working} onClick={() => mutation.mutate({ proposalId: proposal.proposal_id, action: "approve" })}>반영</Button><Button variant="secondary" disabled={working} onClick={() => mutation.mutate({ proposalId: proposal.proposal_id, action: "dismiss" })}>유지</Button></div>
      {mutation.error && mutation.variables?.proposalId === proposal.proposal_id && <p role="alert" className="text-xs text-danger-500">{errorMessage(mutation.error)}</p>}
    </Card>
  );
}

function CardsSkeleton() {
  return <div className="space-y-3" aria-label="카드 불러오는 중">{[0, 1, 2].map((item) => <div key={item} className="h-32 animate-pulse rounded-2xl bg-surface-muted" />)}</div>;
}
