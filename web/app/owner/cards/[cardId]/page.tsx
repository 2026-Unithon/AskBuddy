"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Input, Select, Textarea, TopBar } from "@/components/ui";
import {
  ApiError,
  moveProductCard,
  mutateProductCard,
  updateProductCardDraft,
} from "@/lib/api";
import { cardQuery, productCategoriesQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

import { CardStatusBadge } from "@/components/owner/status-badge";
import { TaskCardDetail } from "@/components/owner/task-card-detail";
import { InlineError } from "@/components/owner/inline-error";
import { SkeletonList } from "@/components/owner/skeleton-list";

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
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

  function refreshRelated() {
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.card(state.storeId, cardId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.faqs(state.storeId) }),
    ]);
  }

  const saveDraft = useMutation({
    mutationFn: () => {
      const version = detail.data?.draft?.version_id;
      if (!version) throw new Error("저장할 초안 버전을 찾지 못했어요.");
      return updateProductCardDraft(cardId, draft.title, draft.content, version, state.token!);
    },
    onSuccess: () => {
      setEditing(false);
      refreshRelated();
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) await detail.refetch();
    },
  });

  const statusMutation = useMutation({
    mutationFn: (action: "approve" | "exclude" | "restore") =>
      mutateProductCard(cardId, action, state.token!),
    onSuccess: refreshRelated,
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) await detail.refetch();
    },
  });

  const moveCategory = useMutation({
    mutationFn: (categoryId: number) =>
      moveProductCard(cardId, categoryId, detail.data!.updated_at, state.token!),
    onSuccess: refreshRelated,
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) await detail.refetch();
    },
  });

  const card = detail.data;
  const title = card?.draft?.title ?? card?.published?.title ?? "";
  const content = card?.draft?.content ?? card?.published?.content ?? "";
  const hasUnpublishedDraft = Boolean(
    card?.draft && card.draft.version_id !== card.published?.version_id
  );

  const requestError = detail.error ?? saveDraft.error ?? statusMutation.error ?? moveCategory.error;
  const errorMessage =
    requestError instanceof ApiError
      ? requestError.detail || "요청을 처리하지 못했어요."
      : requestError
      ? "서버에 연결할 수 없습니다."
      : null;

  return (
    <div className="flex-1 flex flex-col w-full bg-background min-h-dvh relative">
      {/* 상단 TopBar */}
      <TopBar title="카드 상세" backHref="/owner/cards" />

      {/* 메인 스크롤 영역 (하단 엄지 CTA 바 고려 pb-36) */}
      <main className="flex-1 space-y-4 overflow-y-auto px-4 py-3 pb-36">
        {/* 오류 알림 */}
        {errorMessage && (
          <InlineError
            message={errorMessage}
            isRetrying={detail.isFetching}
            onRetry={() => void detail.refetch()}
          />
        )}

        {/* 로딩 스켈레톤 */}
        {detail.isLoading && (
          <div className="space-y-4 pt-1">
            <SkeletonList count={3} heightClass="h-28" label="카드 상세 불러오는 중" />
          </div>
        )}

        {/* 카드 상세 본문 */}
        {card && (
          <>
            {/* 상태 및 메타 배지 */}
            <div className="flex items-center justify-between gap-2 flex-wrap px-1">
              <div className="flex items-center gap-1.5">
                <CardStatusBadge status={card.review_status} />
                <Badge tone="neutral">
                  {card.assignment_type === "MANUAL" ? "수동 분류" : "자동 분류"}
                </Badge>
              </div>
              <span className="text-xs text-muted">
                최종 수정: {formatDate(card.updated_at)}
              </span>
            </div>

            {/* card_type 계약 도입 전에는 추측하지 않고 일반 업무 카드로 표시한다. */}
            {editing ? (
              <Card className="p-4 space-y-3.5 border-brand-500 bg-surface shadow-xs">
                <div className="space-y-1">
                  <label htmlFor="card-title-input" className="text-xs font-bold text-foreground">
                    카드 제목
                  </label>
                  <Input
                    id="card-title-input"
                    value={draft.title}
                    onChange={(e) => setDraft((prev) => ({ ...prev, title: e.target.value }))}
                    aria-label="카드 제목"
                    className="font-bold"
                  />
                </div>

                <div className="space-y-1">
                  <label htmlFor="card-content-input" className="text-xs font-bold text-foreground">
                    카드 내용
                  </label>
                  <Textarea
                    id="card-content-input"
                    value={draft.content}
                    onChange={(e) => setDraft((prev) => ({ ...prev, content: e.target.value }))}
                    rows={9}
                    aria-label="카드 내용"
                    className="bg-background font-normal"
                  />
                </div>

                <p className="text-sm text-muted leading-relaxed">
                  초안을 저장해도 직원에게 즉시 공개되지 않습니다. 하단 &apos;공개&apos; 버튼을 눌러야 직원의 로드맵과 채팅에 반영됩니다.
                </p>

                <div className="flex gap-2 pt-1">
                  <Button
                    size="md"
                    variant="primary"
                    loading={saveDraft.isPending}
                    loadingLabel="초안 저장 중"
                    disabled={!draft.title.trim() || !draft.content.trim()}
                    onClick={() => saveDraft.mutate()}
                    className="flex-1 min-h-[44px] text-xs font-bold"
                  >
                    초안 저장
                  </Button>
                  <Button
                    size="md"
                    variant="secondary"
                    disabled={saveDraft.isPending}
                    onClick={() => setEditing(false)}
                    className="min-h-[44px] text-xs font-bold"
                  >
                    취소
                  </Button>
                </div>
              </Card>
            ) : (
              <div className="space-y-3">
                <TaskCardDetail
                  title={title}
                  content={content}
                  categoryName={card.category?.name}
                />

                {/* 미공개 초안 안내 */}
                {hasUnpublishedDraft && card.published && (
                  <div className="rounded-xl border border-accent-500/40 bg-accent-50/60 p-3 text-xs text-accent-900 leading-relaxed font-medium">
                    ⚠️ 수정한 초안이 아직 공개되지 않았습니다. 직원은 이전 공개본(#{card.published.version_no})을 보고 있습니다.
                  </div>
                )}

                {/* 수정 버튼 */}
                {card.review_status !== "EXCLUDED" && card.draft && (
                  <Button
                    variant="secondary"
                    size="md"
                    className="w-full min-h-[44px] text-xs font-bold active:scale-98"
                    onClick={() => {
                      setDraft({ title, content });
                      setEditing(true);
                    }}
                  >
                    ✏️ 카드 내용 수정하기
                  </Button>
                )}
              </div>
            )}

            {/* 카테고리 변경 섹션 */}
            <Card className="p-4 space-y-2.5 border-border bg-surface shadow-2xs">
              <label htmlFor="card-category-select" className="text-xs font-bold text-foreground">
                업무 카테고리 이동
              </label>
              <Select
                id="card-category-select"
                value={card.category?.category_id ?? ""}
                disabled={moveCategory.isPending || card.review_status === "EXCLUDED"}
                onChange={(e) => moveCategory.mutate(Number(e.target.value))}
                aria-busy={moveCategory.isPending || undefined}
                className="w-full bg-background"
              >
                <option value="" disabled>
                  카테고리 선택
                </option>
                {categories.data?.items.map((cat) => (
                  <option key={cat.category_id} value={cat.category_id}>
                    {cat.name}
                  </option>
                ))}
              </Select>
              <p className="text-sm text-muted">
                직접 이동하면 수동 분류로 기록되어 AI 자동 재분류가 덮어쓰지 않습니다.
              </p>
            </Card>

            {/* 근거 원본 섹션 */}
            <section className="space-y-2.5 pt-1" aria-labelledby="evidence-heading">
              <h2 id="evidence-heading" className="text-xs font-bold text-brand-700 uppercase tracking-wider px-1">
                연결된 근거 원본 ({card.evidence.length}건)
              </h2>
              {card.evidence.length === 0 ? (
                <Card className="p-4 text-center text-xs text-muted">
                  연결된 근거 자료가 없습니다.
                </Card>
              ) : (
                card.evidence.map((evidence) => (
                  <Card key={evidence.evidence_id} className="p-3.5 space-y-2 border-border text-xs bg-surface shadow-2xs">
                    <strong className="font-semibold text-foreground block truncate">
                      📎 {evidence.source.title ?? `자료 #${evidence.source.source_id}`}
                    </strong>
                    {evidence.excerpt && (
                      <blockquote className="border-l-2 border-brand-500 bg-brand-50/40 p-2 rounded-r text-sm leading-relaxed text-foreground/85 italic">
                        &ldquo;{evidence.excerpt}&rdquo;
                      </blockquote>
                    )}
                    {evidence.source.read_url && (
                      <a
                        href={evidence.source.read_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex min-h-[44px] items-center text-xs font-bold text-brand-600 hover:text-brand-700"
                      >
                        원본 파일 열기 ↗
                      </a>
                    )}
                  </Card>
                ))
              )}
            </section>

            {/* 변경 이력 섹션 */}
            <section className="space-y-2 pt-1" aria-labelledby="history-heading">
              <h2 id="history-heading" className="text-xs font-bold text-muted uppercase tracking-wider px-1">
                변경 이력 ({card.events.length}건)
              </h2>
              {card.events.length === 0 ? (
                <Card className="p-3 text-center text-xs text-muted">
                  아직 변경 기록이 없습니다.
                </Card>
              ) : (
                <div className="space-y-1.5">
                  {card.events.map((event) => (
                    <Card key={event.event_id} className="p-2.5 text-xs flex items-center justify-between border-border">
                      <span className="font-semibold text-foreground">{event.action}</span>
                      <span className="text-xs text-muted">{formatDate(event.created_at)}</span>
                    </Card>
                  ))}
                </div>
              )}
            </section>
          </>
        )}

        {/* 유효하지 않은 cardId */}
        {!cardId && (
          <Card className="p-6 text-center space-y-3">
            <p className="text-xs font-bold text-danger-600">유효하지 않은 카드 링크입니다.</p>
            <Button size="md" onClick={() => router.replace("/owner/cards")}>
              카드 목록으로 돌아가기
            </Button>
          </Card>
        )}
      </main>

      {/* 하단 엄지 영역 고정 액션 바 (Bottom Fixed Action Bar) */}
      {card && (
        <div className="fixed bottom-0 left-0 right-0 z-20 mx-auto w-full max-w-[480px] border-t border-border bg-surface/95 backdrop-blur-md px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] shadow-[0_-4px_12px_rgba(0,0,0,0.06)]">
          <div className="flex gap-2">
            {card.review_status !== "EXCLUDED" && (
              <>
                {(card.review_status !== "APPROVED" || hasUnpublishedDraft) && (
                  <Button
                    size="lg"
                    variant="primary"
                    loading={statusMutation.isPending && statusMutation.variables === "approve"}
                    loadingLabel="공개 처리 중"
                    disabled={statusMutation.isPending}
                    onClick={() => statusMutation.mutate("approve")}
                    className="flex-1 min-h-[50px] text-xs font-bold shadow-xs active:scale-[0.98]"
                  >
                    {card.review_status === "APPROVED"
                      ? "수정본 직원 공개"
                      : "직원에게 공개하기"}
                  </Button>
                )}
                <Button
                  size="lg"
                  variant="secondary"
                  loading={statusMutation.isPending && statusMutation.variables === "exclude"}
                  loadingLabel="제외 중"
                  disabled={statusMutation.isPending}
                  onClick={() => {
                    if (window.confirm("이 카드를 직원 화면과 검색에서 제외할까요? 나중에 다시 복원할 수 있습니다.")) {
                      statusMutation.mutate("exclude");
                    }
                  }}
                  className={`min-h-[50px] text-xs font-bold active:scale-[0.98] ${
                    card.review_status === "APPROVED" && !hasUnpublishedDraft ? "w-full" : "px-5"
                  }`}
                >
                  제외
                </Button>
              </>
            )}

            {card.review_status === "EXCLUDED" && (
              <Button
                size="lg"
                variant="primary"
                loading={statusMutation.isPending && statusMutation.variables === "restore"}
                loadingLabel="복원 중"
                disabled={statusMutation.isPending}
                onClick={() => statusMutation.mutate("restore")}
                className="w-full min-h-[50px] text-xs font-bold shadow-xs active:scale-[0.98]"
              >
                카드를 다시 복원하기
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
