"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import {
  BackButton,
  Button,
  ButtonLink,
  Caption,
  Chip,
  Empty,
  ErrorInline,
  NumberedContent,
  Screen,
  Sheet,
  Skeleton,
  Surface,
  TextButton,
  focusRing,
} from "@/components/kit";
import { ApiError, apiErrorMessage, moveProductCard, mutateProductCard, updateProductCardDraft, type CardDetailDto } from "@/lib/api";
import { cardQuery, productCategoriesQuery, queryKeys } from "@/lib/query";
import { CardAssignment } from "@/components/checklist/card-assignment";
import { checklistKeys } from "@/lib/query";
import { useApp } from "@/lib/store";
import { FactCardEditFooter, FactCardPanel, FactCardSheets, useFactCardEditor } from "@/components/owner/fact-card/fact-card-panel";

const STATUS: Record<CardDetailDto["review_status"], { label: string; tone: "brand" | "warn" | "neutral" | "danger" }> = {
  PENDING: { label: "공개 전", tone: "neutral" },
  NEEDS_REVIEW: { label: "확인이 필요해요", tone: "warn" },
  APPROVED: { label: "공개 중", tone: "brand" },
  EXCLUDED: { label: "지운 카드", tone: "danger" },
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric" });
}

// O10 카드 보기: 공개본·초안·근거·고치기·지우기(제외)·카테고리 이동.
// 사실 카드(card.fact_card)는 W3b 사실 단위 편집(/cards/{id}/facts)으로 고친다. 제목은 읽기 전용(D-7).
// 사실 카드가 아닌 옛 카드는 아래 자유 글 편집을 그대로 쓴다.
export default function OwnerCardPage() {
  const params = useParams<{ cardId: string }>();
  const cardId = /^\d+$/.test(params.cardId) ? Number(params.cardId) : 0;
  const { state } = useApp();
  const client = useQueryClient();
  const detail = useQuery(cardQuery(state.token, state.storeId, cardId));
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ title: "", content: "" });
  const [confirmExclude, setConfirmExclude] = useState(false);
  const [moving, setMoving] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const factCard = Boolean(detail.data?.fact_card);
  const factEditor = useFactCardEditor(cardId, factCard);

  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) }),
      client.invalidateQueries({ queryKey: queryKeys.card(state.storeId, cardId) }),
      client.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
      client.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) }),
      client.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
      client.invalidateQueries({ queryKey: queryKeys.faqs(state.storeId) }),
    ]);
  const onConflict = async (error: unknown) => {
    if (error instanceof ApiError && error.status === 409) await detail.refetch();
  };

  const card = detail.data;
  const saveDraft = useMutation({
    mutationFn: () => {
      const version = card?.draft?.version_id ?? card?.published?.version_id;
      if (!version) throw new Error("고칠 버전을 찾지 못했어요.");
      return updateProductCardDraft(cardId, form.title, form.content, version, state.token!);
    },
    onSuccess: async () => {
      setEditing(false);
      await refresh();
    },
    onError: onConflict,
  });
  const status = useMutation({
    mutationFn: (action: "approve" | "exclude" | "restore") => mutateProductCard(cardId, action, state.token!),
    onSuccess: async (_result, action) => {
      setConfirmExclude(false);
      // 마지막 사실을 빼려다 카드를 지운 경우: 편집 초안을 닫는다
      if (action === "exclude") factEditor.cancel();
      await refresh();
    },
    onError: onConflict,
  });

  if (!cardId) {
    return (
      <Screen>
        <BackButton href="/owner/cards" label="카드" />
        <Empty title="잘못된 카드 주소예요" action={<ButtonLink href="/owner/cards">카드 목록으로</ButtonLink>} />
      </Screen>
    );
  }
  if (detail.isLoading) {
    return (
      <Screen>
        <BackButton href="/owner/cards" label="카드" />
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-40" />
      </Screen>
    );
  }
  if (detail.error || !card) {
    const missing = detail.error instanceof ApiError && [403, 404].includes(detail.error.status);
    return (
      <Screen>
        <BackButton href="/owner/cards" label="카드" />
        {missing ? (
          <Empty title="이 카드를 볼 수 없어요" description="다른 매장의 카드이거나 없는 카드예요." action={<ButtonLink href="/owner/cards">카드 목록으로</ButtonLink>} />
        ) : (
          <ErrorInline message={apiErrorMessage(detail.error, "카드를 불러오지 못했어요.")} onRetry={() => void detail.refetch()} retrying={detail.isRefetching} />
        )}
      </Screen>
    );
  }

  const shown = card.draft ?? card.published;
  const title = shown?.title ?? "";
  const content = shown?.content ?? "";
  const unpublishedDraft = Boolean(card.draft && card.published && card.draft.version_id !== card.published.version_id);
  const excluded = card.review_status === "EXCLUDED";
  const canPublish = card.review_status === "PENDING" || card.review_status === "NEEDS_REVIEW" || unpublishedDraft;
  const sourceDeleted = card.source?.source_availability === "DELETED";
  const statusView = STATUS[card.review_status];
  const actionError = status.error;

  const startEdit = () => {
    setForm({ title, content });
    setEditing(true);
    saveDraft.reset();
  };

  if (editing) {
    return (
      <Screen
        footer={
          <>
            {saveDraft.error && (
              <ErrorInline
                message={
                  saveDraft.error instanceof ApiError && saveDraft.error.status === 409
                    ? "그사이 카드가 바뀌었어요. 최신 내용을 확인한 뒤 다시 저장해 주세요. 입력 내용은 그대로 두었어요."
                    : apiErrorMessage(saveDraft.error, "이 변경은 저장되지 않았어요. 입력 내용은 그대로 두었어요.")
                }
              />
            )}
            <Button loading={saveDraft.isPending} disabled={!form.title.trim() || !form.content.trim()} onClick={() => saveDraft.mutate()}>
              고친 내용 저장
            </Button>
            <Button variant="secondary" disabled={saveDraft.isPending} onClick={() => setEditing(false)}>
              그만두기
            </Button>
          </>
        }
      >
        <p className="text-[30px] font-bold leading-[1.28] tracking-[-0.9px] text-ink">고치기</p>
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium text-ink-muted">제목</span>
          <input
            value={form.title}
            onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
            className={`min-h-12 rounded-[16px] bg-surface px-4 text-[16px] text-ink shadow-card ${focusRing}`}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="text-[13px] font-medium text-ink-muted">내용 · 한 줄에 하나씩</span>
          <textarea
            value={form.content}
            onChange={(event) => setForm((prev) => ({ ...prev, content: event.target.value }))}
            rows={8}
            className={`min-h-48 rounded-[16px] bg-surface p-4 text-[16px] leading-[1.6] text-ink shadow-card ${focusRing}`}
          />
        </label>
        <Caption>저장하면 고친 내용은 공개 전 상태로 남아요. 공개하기를 눌러야 직원에게 보여요.</Caption>
      </Screen>
    );
  }

  const screen = (
    <Screen
      footer={
        factEditor.editing ? (
          <FactCardEditFooter editor={factEditor} />
        ) : (
        <>
          {actionError && status.variables !== "exclude" && (
            <ErrorInline
              message={apiErrorMessage(actionError, "이 변경은 저장되지 않았어요.")}
              onRetry={() => status.variables && status.mutate(status.variables)}
              retrying={status.isPending}
            />
          )}
          {excluded ? (
            <Button loading={status.isPending} onClick={() => status.mutate("restore")}>
              다시 살리기
            </Button>
          ) : (
            <>
              {canPublish && (
                <Button loading={status.isPending && status.variables === "approve"} onClick={() => status.mutate("approve")}>
                  공개하기
                </Button>
              )}
              {card.fact_card ? (
                factEditor.canEdit && (
                  <Button variant={canPublish ? "secondary" : "primary"} onClick={factEditor.start}>
                    고치기
                  </Button>
                )
              ) : (
                <Button variant={canPublish ? "secondary" : "primary"} onClick={startEdit}>
                  고치기
                </Button>
              )}
              <Button variant="secondary" onClick={() => setConfirmExclude(true)}>
                지우기
              </Button>
            </>
          )}
        </>
        )
      }
    >
      <BackButton href="/owner/cards" label="카드" />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setMoving(true)}
          disabled={excluded}
          aria-label={`카테고리 ${card.category?.name ?? "기타"} · 옮기기`}
          className={`min-h-8 text-[13px] font-bold text-primary underline-offset-2 hover:underline ${focusRing}`}
        >
          {card.category?.name ?? "기타"}
        </button>
        <Chip size="sm" tone={statusView.tone}>{statusView.label}</Chip>
        {unpublishedDraft && <Chip size="sm" tone="warn">고친 내용 공개 전</Chip>}
      </div>
      <h1 className="text-[30px] font-bold leading-[1.28] tracking-[-0.9px] text-ink [word-break:keep-all]">{title}</h1>
      {card.fact_card && <Caption className="-mt-2">제목은 메뉴·업무 이름이에요</Caption>}
      {card.review_status === "NEEDS_REVIEW" && card.needs_review_reason && (
        <p className="rounded-[14px] bg-warn-50 px-3.5 py-2.5 text-[13px] leading-[1.45] text-warn-700">{card.needs_review_reason}</p>
      )}
      {card.fact_card ? (
        <FactCardPanel editor={factEditor} card={card} />
      ) : (
        <Surface className="px-[18px] py-4">
          <NumberedContent content={content} />
        </Surface>
      )}
      {!excluded && card.review_status === "APPROVED" && card.published && <CardAssignment cardId={cardId} />}
      {unpublishedDraft && card.published && <Caption>직원에게는 아직 이전 내용이 보여요 · {card.published.title}</Caption>}
      <Caption>
        출처 · {card.source?.title ?? "알 수 없음"}
        {card.published ? ` · ${formatDate(card.published.created_at)}` : ""}
        {sourceDeleted ? " · 인용 끊김" : ""}
      </Caption>
      {card.evidence.length > 0 && (
        <TextButton onClick={() => setShowEvidence((value) => !value)} aria-expanded={showEvidence}>
          {showEvidence ? "근거 접기" : `근거 보기 · ${card.evidence.length}`}
        </TextButton>
      )}
      {showEvidence && (
        <ul className="flex flex-col gap-2">
          {card.evidence.map((item) => (
            <li key={item.evidence_id} className="rounded-[14px] bg-surface px-3.5 py-2.5 text-[13px] leading-[1.45] text-ink shadow-card">
              <p className="whitespace-pre-wrap">{item.excerpt ?? "원문 위치만 남아 있어요"}</p>
              <p className="mt-1 text-[12px] text-ink-muted">
                {item.source.title ?? "자료"}
                {item.source.source_availability === "DELETED" ? " · 인용 끊김 (원본이 지워졌어요)" : ""}
              </p>
            </li>
          ))}
        </ul>
      )}

      <Sheet
        open={confirmExclude}
        onClose={() => setConfirmExclude(false)}
        title="이 카드를 지울까요?"
        description="직원에게 더는 보이지 않고 버디도 이 카드로 답하지 않아요. 나중에 다시 살릴 수 있어요."
      >
        {status.error !== null && status.variables === "exclude" && <ErrorInline message={apiErrorMessage(status.error, "지우지 못했어요.")} />}
        <Button variant="danger" loading={status.isPending} onClick={() => status.mutate("exclude")}>
          지우기
        </Button>
        <Button variant="secondary" onClick={() => setConfirmExclude(false)}>
          그대로 두기
        </Button>
      </Sheet>
      <MoveCategorySheet open={moving} onClose={() => setMoving(false)} card={card} onMoved={refresh} />
    </Screen>
  );
  if (!card.fact_card) return screen;
  return (
    <>
      {screen}
      <FactCardSheets
        editor={factEditor}
        onExcludeCard={() => status.mutate("exclude")}
        excludePending={status.isPending && status.variables === "exclude"}
        excludeError={status.variables === "exclude" ? status.error : null}
      />
    </>
  );
}

function MoveCategorySheet({
  open,
  onClose,
  card,
  onMoved,
}: {
  open: boolean;
  onClose: () => void;
  card: CardDetailDto;
  onMoved: () => Promise<unknown>;
}) {
  const { state } = useApp();
  const categories = useQuery({ ...productCategoriesQuery(state.token, state.storeId), enabled: open && Boolean(state.token && state.storeId) });
  const move = useMutation({
    mutationFn: (categoryId: number) => moveProductCard(card.card_id, categoryId, card.updated_at, state.token!),
    onSuccess: async () => {
      await onMoved();
      onClose();
    },
  });
  return (
    <Sheet open={open} onClose={onClose} title="어디로 옮길까요?" description="옮겨도 공개 상태와 직원 학습 기록은 그대로예요.">
      {categories.isLoading && <Skeleton className="h-32" />}
      {categories.error && <ErrorInline message="카테고리를 불러오지 못했어요." onRetry={() => void categories.refetch()} />}
      {move.error && (
        <ErrorInline
          message={
            move.error instanceof ApiError && move.error.status === 409
              ? "그사이 카드가 바뀌었어요. 닫고 다시 시도해 주세요."
              : apiErrorMessage(move.error, "옮기지 못했어요.")
          }
        />
      )}
      <ul className="flex max-h-[50dvh] flex-col gap-1 overflow-y-auto">
        {categories.data?.items.map((category) => {
          const current = category.category_id === card.category?.category_id;
          return (
            <li key={category.category_id}>
              <button
                type="button"
                disabled={current || move.isPending}
                onClick={() => move.mutate(category.category_id)}
                className={`flex min-h-12 w-full items-center justify-between rounded-[14px] bg-surface px-4 text-left text-[15px] text-ink disabled:opacity-60 ${focusRing}`}
              >
                {category.name}
                {current && <Chip size="sm">지금 여기</Chip>}
              </button>
            </li>
          );
        })}
      </ul>
    </Sheet>
  );
}
