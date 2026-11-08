"use client";

import { reviewReasonText } from "@/lib/review-reason";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { sharedTitleProps } from "@/lib/shared-title";
import {
  BackButton,
  Button,
  ButtonLink,
  Chip,
  Empty,
  ErrorInline,
  NumberedContent,
  Screen,
  Sheet,
  Skeleton,
  Surface,
  focusRing,
  useFeedback,
} from "@/components/kit";
import { ApiError, apiErrorMessage, moveProductCard, mutateProductCard, type CardDetailDto } from "@/lib/api";
import { cardQuery, productCategoriesQuery, queryKeys } from "@/lib/query";
import { CardAssignment } from "@/components/checklist/card-assignment";
import { checklistKeys } from "@/lib/query";
import { useApp } from "@/lib/store";
import { FactCardEditFooter, FactCardPanel, FactCardSheets, useFactCardEditor } from "@/components/owner/fact-card/fact-card-panel";
import { evidenceNames } from "@/components/owner/fact-card/fact-row";
import { compactRecipe } from "@/components/owner/fact-card/fact-group";
import { isRecipeCategory } from "@/lib/recipe-category";
import { pressable } from "@/components/kit/buttons";

// O10 카드 보기: 공개본·초안·근거·고치기·지우기(제외)·카테고리 이동.
// 사실 카드(card.fact_card)는 W3b 사실 단위 편집(/cards/{id}/facts)으로 고친다. 제목은 읽기 전용(D-7).
// 사실 카드가 아닌 카드는 읽기만 한다(1회 삭제 뒤엔 없다).
export default function OwnerCardPage() {
  const params = useParams<{ cardId: string }>();
  const cardId = /^\d+$/.test(params.cardId) ? Number(params.cardId) : 0;
  const { state } = useApp();
  const client = useQueryClient();
  const { snackbar } = useFeedback();
  const detail = useQuery(cardQuery(state.token, state.storeId, cardId));
  const [moving, setMoving] = useState(false);
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
  const status = useMutation({
    mutationFn: (action: "approve" | "exclude" | "restore") => mutateProductCard(cardId, action, state.token!),
    onSuccess: async (_result, action) => {
      // 마지막 사실을 빼려다 카드를 지운 경우: 편집 초안을 닫고, 삭제는 5초 되돌리기만 남긴다
      if (action === "exclude") {
        factEditor.cancel();
        snackbar({ message: "삭제했어요", actionLabel: "되돌리기", onAction: () => status.mutate("restore") });
      }
      await refresh();
    },
    onError: async (error, action) => {
      // 삭제한 뒤엔 삭제 안내 화면이라 아래 오류 줄이 안 보인다. 되돌리기 실패는 스낵바로 '다시'
      if (action === "restore") snackbar({ message: "되돌리지 못했어요", actionLabel: "다시", onAction: () => status.mutate("restore") });
      await onConflict(error);
    },
  });

  if (!cardId) {
    return (
      <Screen>
        <BackButton parent="/owner/cards" label="카드" />
        <Empty title="잘못된 카드 주소예요" action={<ButtonLink href="/owner/cards">카드 목록으로</ButtonLink>} />
      </Screen>
    );
  }
  if (detail.isLoading) {
    return (
      <Screen>
        <BackButton parent="/owner/cards" label="카드" />
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-40" />
      </Screen>
    );
  }
  if (detail.error || !card) {
    const missing = detail.error instanceof ApiError && [403, 404].includes(detail.error.status);
    return (
      <Screen>
        <BackButton parent="/owner/cards" label="카드" />
        {missing ? (
          <Empty title="이 카드를 볼 수 없어요" description="다른 매장의 카드이거나 없는 카드예요." action={<ButtonLink href="/owner/cards">카드 목록으로</ButtonLink>} />
        ) : (
          <ErrorInline message={apiErrorMessage(detail.error, "카드를 불러오지 못했어요.")} onRetry={() => void detail.refetch()} retrying={detail.isRefetching} />
        )}
      </Screen>
    );
  }

  const shown = card.draft ?? card.published;
  // 레시피 한눈에 보기면 가격은 제목 옆에(2026-11-08 사용자 스케치)
  const recipe = card.fact_card && factEditor.facts.data ? compactRecipe(factEditor.facts.data.blocks) : null;
  const price = recipe && !factEditor.editing ? recipe.price : null;
  const title = shown?.title ?? "";
  const content = shown?.content ?? "";
  const unpublishedDraft = Boolean(card.draft && card.published && card.draft.version_id !== card.published.version_id);
  const canPublish = card.review_status === "PENDING" || card.review_status === "NEEDS_REVIEW" || unpublishedDraft;
  const actionError = status.error;

  // 삭제한 카드는 어디에서도 보이지 않는다(2026-11-06 사용자). 옛 알림·뒤로가기로 와도 안내만
  if (card.review_status === "EXCLUDED") {
    return (
      <Screen>
        <BackButton parent="/owner/cards" label="카드" />
        <Empty title="삭제한 카드예요" description="이 카드는 이제 어디에도 보이지 않아요." />
      </Screen>
    );
  }

  // 근거 자료 한 줄(o06c): 사실 카드는 모든 사실의 근거, 아니면 카드 근거의 자료 이름
  const evidence = card.fact_card
    ? evidenceNames(factEditor.facts.data?.blocks.flatMap((block) => block.facts.flatMap((fact) => fact.origins)) ?? [])
    : [...new Set(card.evidence.map((item) => `${item.source.title ?? "자료"}${item.source.source_availability === "DELETED" ? " (원본 지워짐)" : ""}`))];
  const statusLine = unpublishedDraft
    ? { dot: "bg-warn-500", text: "고친 내용은 아직 공개 전이에요" }
    : card.review_status === "APPROVED"
      ? { dot: "bg-primary", text: "직원에게 보여요" }
      : card.review_status === "PENDING"
        ? { dot: "bg-ink-muted", text: "아직 공개 전이에요" }
        : null;

  const screen = (
    <Screen
      footer={
        factEditor.editing ? (
          <FactCardEditFooter editor={factEditor} />
        ) : (
          canPublish && (
            <>
              {actionError && (
                <ErrorInline
                  message={apiErrorMessage(actionError, "이 변경은 저장되지 않았어요.")}
                  onRetry={() => status.variables && status.mutate(status.variables)}
                  retrying={status.isPending}
                />
              )}
              {/* 검수 필요의 '미공개'는 서버 전환이 생긴 뒤(백로그) */}
              <Button loading={status.isPending && status.variables === "approve"} onClick={() => status.mutate("approve")}>
                공개
              </Button>
            </>
          )
        )
      }
    >
      <div className="flex items-center justify-between gap-2">
        {/* 수정 중에는 하단 '돌아가기'(버릴지 묻는다)로만 나간다. 뒤로 버튼은 묻지 않고 떠나므로 숨긴다 */}
        {factEditor.editing ? <span /> : <BackButton parent="/owner/cards" label="카드" />}
        {card.fact_card && factEditor.canEdit && !factEditor.editing && (
          <button
            type="button"
            onClick={factEditor.start}
            className={`min-h-11 rounded-full bg-surface px-4 text-[14px] font-bold text-primary shadow-card ${pressable} ${focusRing}`}
          >
            수정하기
          </button>
        )}
      </div>
      <button
        type="button"
        onClick={() => setMoving(true)}
        aria-label={`카테고리 바꾸기, 지금 ${card.category?.name ?? "기타"}`}
        className={`inline-flex min-h-8 items-center gap-1 self-start rounded-full bg-empty px-3 text-[13px] font-bold text-primary ${pressable} ${focusRing}`}
      >
        {card.category?.name ?? "기타"}
        <span aria-hidden>▾</span>
      </button>
      <div className="-mt-2 flex items-baseline justify-between gap-3">
        <h1 {...sharedTitleProps(`card-title-${cardId}`)} className="min-w-0 text-[30px] font-bold leading-[1.28] tracking-[-0.9px] text-ink [word-break:keep-all]">
          {title}
        </h1>
        {price && <p className="shrink-0 text-[17px] font-bold text-ink">{price}</p>}
      </div>
      {statusLine && (
        <p className="-mt-2 flex items-center gap-1.5 text-[13px] text-ink-muted">
          <span aria-hidden className={`size-2 rounded-full ${statusLine.dot}`} />
          {statusLine.text}
        </p>
      )}
      {card.review_status === "NEEDS_REVIEW" && (
        <div className="rounded-[14px] border-l-4 border-warn-500 bg-warn-50 px-4 py-3">
          <p className="text-[15px] font-bold text-warn-700">확인해 주세요</p>
          <p className="mt-0.5 text-[15px] leading-[1.5] text-ink [word-break:keep-all]">{reviewReasonText(card.needs_review_reason)}</p>
        </div>
      )}
      {card.fact_card ? (
        <FactCardPanel editor={factEditor} card={card} />
      ) : (
        <Surface className="px-[18px] py-4">
          <NumberedContent content={content} />
        </Surface>
      )}
      {/* 레시피는 근무조와 상관없이 모두에게 보인다. 근무조 고르기는 할 일 카드에만(2026-11-08 사용자) */}
      {card.review_status === "APPROVED" && card.published && !factEditor.editing && !recipe && !isRecipeCategory(card.category?.name ?? "") && <CardAssignment cardId={cardId} />}
      {evidence.length > 0 && !factEditor.editing && <p className="pt-2 text-[11px] leading-[1.5] text-ink-muted [word-break:keep-all]">근거 자료 {evidence.join(", ")}</p>}
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
