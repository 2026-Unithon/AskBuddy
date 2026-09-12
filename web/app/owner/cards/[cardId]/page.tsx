"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Input, Shell, TopBar } from "@/components/ui";
import {
  ApiError,
  moveProductCard,
  mutateProductCard,
  updateProductCardDraft,
} from "@/lib/api";
import { cardQuery, productCategoriesQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

function message(error: unknown) {
  return error instanceof ApiError ? error.detail || "요청을 처리하지 못했어요." : "서버에 연결할 수 없습니다.";
}

export default function CardDetailPage() {
  const params = useParams<{ cardId: string }>();
  const router = useRouter();
  const cardId = /^\d+$/.test(params.cardId) ? Number(params.cardId) : 0;
  const { state } = useApp();
  const queryClient = useQueryClient();
  const detail = useQuery(cardQuery(state.token, state.storeId, cardId));
  const categories = useQuery(productCategoriesQuery(state.token, state.storeId));
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ title: "", content: "" });

  async function refreshRelated() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.card(state.storeId, cardId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.faqs(state.storeId) }),
    ]);
  }

  const save = useMutation({
    mutationFn: () => {
      const version = detail.data?.draft?.version_id;
      if (!version) throw new Error("저장할 초안을 찾지 못했어요.");
      return updateProductCardDraft(cardId, draft.title, draft.content, version, state.token!);
    },
    onSuccess: async () => {
      setEditing(false);
      await refreshRelated();
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) await detail.refetch();
    },
  });
  const statusMutation = useMutation({
    mutationFn: (action: "approve" | "exclude" | "restore") => mutateProductCard(cardId, action, state.token!),
    onSuccess: refreshRelated,
  });
  const move = useMutation({
    mutationFn: (categoryId: number) => moveProductCard(cardId, categoryId, detail.data!.updated_at, state.token!),
    onSuccess: refreshRelated,
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) await detail.refetch();
    },
  });

  const card = detail.data;
  const hasUnpublishedDraft = Boolean(
    card?.draft && card.draft.version_id !== card.published?.version_id
  );
  const requestError = detail.error ?? save.error ?? statusMutation.error ?? move.error;
  return (
    <Shell>
      <TopBar title="카드 상세" backHref="/owner/cards" />
      <div className="flex-1 space-y-4 overflow-y-auto px-5 pb-8">
        {detail.isLoading && <div className="h-72 animate-pulse rounded-3xl bg-surface-muted" aria-label="카드 불러오는 중" />}
        {requestError && (
          <Card className="space-y-3 p-5 text-center">
            <p role="alert" className="text-sm text-danger-500">{message(requestError)}</p>
            <Button variant="secondary" onClick={() => void detail.refetch()}>최신 내용 다시 불러오기</Button>
          </Card>
        )}
        {card && (
          <>
            <Card className="space-y-4 p-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={card.review_status === "APPROVED" ? "brand" : card.review_status === "EXCLUDED" ? "neutral" : "warn"}>{card.review_status}</Badge>
                <Badge tone="neutral">{card.assignment_type === "MANUAL" ? "수동 분류" : "자동 분류"}</Badge>
                {detail.isFetching && <span className="text-[11px] text-muted">갱신 중…</span>}
              </div>
              {editing ? (
                <div className="space-y-3">
                  <Input value={draft.title} onChange={(event) => setDraft((value) => ({ ...value, title: event.target.value }))} aria-label="카드 제목" />
                  <textarea value={draft.content} onChange={(event) => setDraft((value) => ({ ...value, content: event.target.value }))} rows={8} aria-label="카드 내용" className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm leading-relaxed" />
                  <div className="flex gap-2"><Button disabled={save.isPending || !draft.title.trim() || !draft.content.trim()} onClick={() => save.mutate()}>초안 저장</Button><Button variant="secondary" onClick={() => setEditing(false)}>취소</Button></div>
                  <p className="text-xs text-muted">초안을 저장해도 직원에게 바로 공개되지 않습니다. 공개 버튼을 눌러야 반영됩니다.</p>
                </div>
              ) : (
                <div>
                  <h1 className="text-lg font-bold text-brand-700">{card.draft?.title ?? card.published?.title ?? "제목 없음"}</h1>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{card.draft?.content ?? card.published?.content}</p>
                  {hasUnpublishedDraft && card.published && <p className="mt-3 rounded-xl bg-accent-50 px-3 py-2 text-xs text-muted">수정한 초안이 아직 공개되지 않았습니다. 현재 직원에게는 이전 공개본이 보입니다.</p>}
                  {card.review_status !== "EXCLUDED" && card.draft && <Button variant="secondary" className="mt-4" onClick={() => { setDraft({ title: card.draft!.title, content: card.draft!.content }); setEditing(true); }}>수정</Button>}
                </div>
              )}
              <div className="border-t border-border pt-4">
                <label htmlFor="card-category" className="text-xs font-bold text-muted">업무 카테고리</label>
                <select id="card-category" value={card.category?.category_id ?? ""} disabled={move.isPending || card.review_status === "EXCLUDED"} onChange={(event) => move.mutate(Number(event.target.value))} className="mt-2 min-h-11 w-full rounded-xl border border-border bg-surface px-3 text-sm">
                  <option value="" disabled>카테고리 선택</option>
                  {categories.data?.items.map((category) => <option key={category.category_id} value={category.category_id}>{category.name}</option>)}
                </select>
                <p className="mt-1 text-[11px] text-muted">직접 이동하면 수동 분류로 기록되어 자동 재분류가 덮어쓰지 않습니다.</p>
              </div>
              <div className="flex flex-wrap gap-2 border-t border-border pt-4">
                {card.review_status !== "EXCLUDED" && (card.review_status !== "APPROVED" || hasUnpublishedDraft) && <Button disabled={statusMutation.isPending} onClick={() => statusMutation.mutate("approve")}>{card.review_status === "APPROVED" ? "수정본 공개" : "공개"}</Button>}
                {card.review_status !== "EXCLUDED" ? <Button variant="secondary" disabled={statusMutation.isPending} onClick={() => statusMutation.mutate("exclude")}>제외</Button> : <Button disabled={statusMutation.isPending} onClick={() => statusMutation.mutate("restore")}>복원</Button>}
              </div>
            </Card>

            <section className="space-y-3">
              <h2 className="text-sm font-bold text-brand-700">근거 원본</h2>
              {card.evidence.length === 0 ? <Card className="p-4 text-xs text-muted">연결된 근거가 없습니다.</Card> : card.evidence.map((evidence) => (
                <Card key={evidence.evidence_id} className="space-y-2 p-4">
                  <p className="text-xs font-bold">{evidence.source.title ?? `원본 #${evidence.source.source_id}`}</p>
                  {evidence.excerpt && <blockquote className="border-l-2 border-brand-500 pl-3 text-xs text-muted">{evidence.excerpt}</blockquote>}
                  <p className="text-[11px] text-muted">{evidence.locator_type} · {JSON.stringify(evidence.locator)}</p>
                  {evidence.source.read_url && <a href={evidence.source.read_url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center text-xs font-bold text-brand-500">원본 열기</a>}
                </Card>
              ))}
            </section>

            <section className="space-y-3">
              <h2 className="text-sm font-bold text-brand-700">변경 기록</h2>
              {card.events.length === 0 ? <Card className="p-4 text-xs text-muted">아직 변경 기록이 없습니다.</Card> : card.events.map((event) => (
                <Card key={event.event_id} className="p-3 text-xs"><span className="font-bold">{event.action}</span><span className="ml-2 text-muted">{new Date(event.created_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</span></Card>
              ))}
            </section>
          </>
        )}
        {!cardId && <Card className="p-6 text-center text-sm text-danger-500">잘못된 카드 링크입니다.<Button className="mt-3" onClick={() => router.replace("/owner/cards")}>카드 목록으로</Button></Card>}
      </div>
    </Shell>
  );
}
