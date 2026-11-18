"use client";

// W3b 사실 카드 본문: 사실 목록 읽기(Query)·편집 초안(지역 reducer)·저장(mutation).
// 서버 값은 cardFactsQuery 가 정본이다. 편집 중 초안은 저장 성공 전까지 서버에 쓰지 않는다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Caption, ConfirmDialog, Empty, ErrorInline, RefreshingHint, Sheet, Skeleton, TextButton, useFeedback } from "@/components/kit";
import { ApiError, apiErrorMessage, parseCardFacts, revertFactEdit, saveCardFacts, type CardDetailDto, type CardFactsView, type ParsedFactProposal } from "@/lib/api";
import { cardFactsQuery, checklistKeys, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";
import { FactAddSheet } from "./fact-add-sheet";
import { CARD_EXCLUDED_TEXT, errorCode, isRetryable, saveErrorMessage } from "./fact-messages";
import { CardLinesView, PICK_TEXT, type LinesBlock } from "./card-lines-view";
import { priceOfFact, priceOfLine, splitPrice } from "@/lib/card-price";
import { LineEditSheet } from "./line-edit-sheet";
import { LineTilesEditor } from "./line-tiles-editor";
import { focusRing } from "@/components/kit/buttons";
import { useFactEditDraft } from "./use-fact-edit-draft";

const CONFLICT_CODES = ["CARD_VERSION_CONFLICT", "FACT_CHANGED_ELSEWHERE"];

const ENTITY_TEXT = "메뉴 정리가 바뀌어 이 카드에서 고칠 수 없어요.";
const RAW_TEXT = "이 카드에는 사실로 나뉘지 않은 내용이 섞여 있어 사실 단위로 고칠 수 없어요.";

/** 사실 카드 화면 상태. 페이지가 본문(FactCardPanel)과 하단(FactCardEditFooter)에 같이 넘긴다. */
export function useFactCardEditor(cardId: number, enabled: boolean) {
  const { state } = useApp();
  const client = useQueryClient();
  const { toast, snackbar } = useFeedback();
  const facts = useQuery(cardFactsQuery(state.token, state.storeId, cardId, enabled));
  const { draft, dirty, remaining, actions, parseNeeds, buildRequest } = useFactEditDraft();
  const [editKey, setEditKey] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [confirmLast, setConfirmLast] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [reloadError, setReloadError] = useState<unknown>(null);

  const invalidateCard = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: queryKeys.card(state.storeId, cardId) }),
      client.invalidateQueries({ queryKey: queryKeys.cardFacts(state.storeId, cardId) }),
      client.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
    ]);

  const refreshAll = () =>
    Promise.all([
      invalidateCard(),
      client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) }),
      client.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) }),
      client.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
      client.invalidateQueries({ queryKey: queryKeys.faqs(state.storeId) }),
    ]);
  const revert = useMutation({
    mutationFn: (editId: number) => revertFactEdit(cardId, editId, state.token!),
    onSuccess: async () => {
      await refreshAll();
      toast("되돌렸어요");
    },
    onError: (error) => toast(apiErrorMessage(error, "되돌리지 못했어요."), { durationMs: 5000 }),
  });
  // 저장: 고친 줄은 서버가 다시 분석해 사실 후보를 받고(MODIFY/ADD), 줄과 함께 한 번에 저장한다(계획 10)
  const save = useMutation({
    mutationFn: async () => {
      const parsed = new Map<string, ParsedFactProposal[]>();
      for (const need of parseNeeds()) {
        const result = await parseCardFacts(cardId, { text: need.text, mode: need.mode, base_fact_revision_id: need.base }, state.token!);
        parsed.set(need.key, result.proposals);
      }
      const request = buildRequest(parsed);
      if (!request) throw new Error("no draft");
      return saveCardFacts(cardId, request, state.token!);
    },
    onSuccess: async (result) => {
      await refreshAll();
      actions.clear();
      // 5초 안에 '되돌리기' 글자를 누르면 직전 판 내용으로 돌아간다(계획 7 Task 7)
      if (result.changed && result.edit_id) {
        const editId = result.edit_id;
        snackbar({ message: "수정했어요", actionLabel: "되돌리기", onAction: () => revert.mutate(editId) });
      } else toast("수정 완료");
    },
    onError: async (error) => {
      const code = errorCode(error);
      if (code === "CARD_EXCLUDED") {
        // 그사이 카드가 지워졌다: 오류가 아니라 지운 카드 상태로 보여 준다
        actions.clear();
        setNotice(CARD_EXCLUDED_TEXT);
        await invalidateCard();
      } else if (code === "CARD_ENTITY_MOVED") {
        // 입력은 그대로 두고, 읽기 화면이 바뀐 편집 가능 여부를 보이게 다시 읽는다
        await invalidateCard();
      }
    },
  });

  const start = () => {
    if (!facts.data) return;
    actions.reset(facts.data);
    save.reset();
    setNotice(null);
    setReloadError(null);
  };
  const cancel = () => {
    actions.clear();
    save.reset();
    setReloadError(null);
    setEditKey(null);
    setAdding(false);
    setConfirmLast(false);
  };
  const submit = () => {
    setReloadError(null);
    if (draft) save.mutate();
  };
  // 충돌 뒤 "최신 내용 불러오기": 고친 내용은 버리고 서버 최신 판으로 다시 시작한다
  // 다시 읽기가 실패하면 TanStack 은 옛 캐시를 돌려준다 → 초안·충돌 배너를 그대로 두고 오류만 보인다
  const reloadLatest = async () => {
    setReloadError(null);
    const result = await facts.refetch();
    if (result.isError || !result.data) {
      setReloadError(result.error ?? new Error("reload failed"));
      return;
    }
    save.reset();
    actions.reset(result.data);
    await client.invalidateQueries({ queryKey: queryKeys.card(state.storeId, cardId) });
  };
  const remove = (key: string) => {
    if (remaining <= 1) setConfirmLast(true);
    else actions.remove(key);
  };
  const applyEdit = (text: string) => {
    if (editKey) actions.edit(editKey, text);
    setEditKey(null);
  };
  const addProposals = (proposals: ParsedFactProposal[]) => {
    proposals.forEach((proposal) => actions.add(proposal));
    setAdding(false);
  };

  const view = facts.data;
  // 사실로 나뉘지 않은 RAW 블록이 섞이면 요청에 담을 수 없다(서버 집합 검사 실패) → 편집 막음
  const hasRaw = Boolean(view?.blocks.some((b) => b.kind === "RAW" && b.facts.length > 0));
  const canEdit = Boolean(view?.editable && !hasRaw);

  return {
    cardId,
    facts,
    draft,
    dirty,
    remaining,
    actions,
    save,
    editing: draft !== null,
    canEdit,
    hasRaw,
    reloadError,
    clearReloadError: () => setReloadError(null),
    editKey,
    setEditKey,
    adding,
    setAdding,
    confirmLast,
    setConfirmLast,
    notice,
    start,
    cancel,
    submit,
    reloadLatest,
    remove,
    applyEdit,
    addProposals,
  };
}

export type FactCardEditor = ReturnType<typeof useFactCardEditor>;

export function FactCardPanel({ editor, card }: { editor: FactCardEditor; card: CardDetailDto }) {
  const { facts, draft, save } = editor;
  if (facts.isLoading) {
    return (
      <div className="flex flex-col gap-3" data-testid="fact-panel-loading">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
    );
  }
  if (!facts.data) {
    if (facts.error instanceof ApiError && [403, 404].includes(facts.error.status)) {
      return <Empty title="이 카드를 볼 수 없어요" description="다른 매장의 카드이거나 없는 카드예요." />;
    }
    return (
      <ErrorInline
        message={apiErrorMessage(facts.error, "사실 목록을 불러오지 못했어요.")}
        onRetry={() => void facts.refetch()}
        retrying={facts.isRefetching}
      />
    );
  }
  const view = facts.data;
  const excluded = card.review_status === "EXCLUDED";
  const locked = save.isPending;

  return (
    <div className="flex flex-col gap-3" data-testid="fact-panel">
      <RefreshingHint active={facts.isFetching && !facts.isLoading} />
      {/* 다시 읽기만 실패했으면 보던 내용·고치던 초안은 그대로 두고 알린다 */}
      {facts.error && (
        <ErrorInline
          message={apiErrorMessage(facts.error, "최신 사실 목록을 불러오지 못했어요.")}
          onRetry={() => void facts.refetch()}
          retrying={facts.isRefetching}
        />
      )}
      {editor.notice && excluded && <Caption className="text-danger-700">{editor.notice}</Caption>}
      {/* '수정하기'가 없는 이유는 알려 준다(고칠 수 없는 카드) */}
      {!editor.editing && !view.editable && !excluded && (
        <Caption>{view.entity_problem ? ENTITY_TEXT : "지금은 이 카드를 사실 단위로 고칠 수 없어요."}</Caption>
      )}
      {!editor.editing && view.editable && editor.hasRaw && !excluded && <Caption>{RAW_TEXT}</Caption>}
      {draft
        ? (
          // 수정(계획 10): 보기와 같은 모양의 줄 타일을 끌어 옮기고, 누르면 그 줄을 고친다
          <LineTilesEditor blocks={draft.blocks} locked={locked} onMove={editor.actions.move} onEdit={editor.setEditKey} />
        )
        : (
          // 보기(계획 10): 모델·사장님이 쓴 구역·줄 그대로. 직원 레시피와 같은 부품이다
          <CardLinesView blocks={viewLines(view).blocks} />
        )}
      {draft && (
        <button
          type="button"
          disabled={locked}
          onClick={() => editor.setAdding(true)}
          className={`min-h-12 rounded-[16px] border-2 border-dashed border-empty text-[15px] font-bold text-primary disabled:opacity-50 ${focusRing}`}
        >
          + 사실 추가
        </button>
      )}
    </div>
  );
}

/**
 * 보기 줄. 아직 고르지 않은 충돌 값을 인용한 줄은 값 대신 '골라 주세요'(계획 7 Task 6) — 이어진 같은 자리는 한 줄로.
 * 금액 줄은 본문에서 빼고 제목 옆 금액으로 낸다(2026-11-18 사용자).
 */
export function viewLines(view: CardFactsView): { price: string[]; blocks: LinesBlock[] } {
  return splitPrice(linesForView(view));
}

function linesForView(view: CardFactsView): LinesBlock[] {
  const waiting = new Set((view.review_items ?? []).flatMap((item) => (item.kind === "CHOOSE" ? item.options.map((o) => o.fact_id) : [])));
  const pendingRevisions = new Set(view.blocks.flatMap((block) => block.facts.filter((f) => waiting.has(f.fact_id)).map((f) => f.fact_revision_id)));
  return view.blocks
    .filter((block) => block.lines.length > 0)
    .map((block) => {
      const lines: LinesBlock["lines"] = [];
      const factPrice = new Map(block.facts.map((f) => [f.fact_revision_id, priceOfFact(f)]));
      for (const line of block.lines) {
        const pick = line.fact_revision_ids.some((id) => pendingRevisions.has(id));
        if (pick && lines.at(-1)?.pick) continue;
        lines.push(
          pick
            ? { line_no: line.line_no, text: PICK_TEXT, pick: true }
            : { line_no: line.line_no, text: line.text, price: priceOfLine(line.fact_revision_ids.map((id) => factPrice.get(id) ?? null)) },
        );
      }
      return { key: block.block_id, kind: block.kind, heading: block.heading, lines };
    });
}

/**
 * 고치기·추가·마지막 줄 시트. 스크롤 영역(main) 밖, Screen 옆에 둔다 —
 * Sheet 는 가장 가까운 relative 부모를 덮으므로 main 안에 두면 스크롤했을 때 화면 밖에 뜬다.
 */
export function FactCardSheets({
  editor,
  onExcludeCard,
  excludePending,
  excludeError,
}: {
  editor: FactCardEditor;
  onExcludeCard: () => void;
  excludePending: boolean;
  excludeError: unknown;
}) {
  const { draft } = editor;
  const editLine = editor.editKey && draft ? draft.blocks.flatMap((b) => b.lines).find((l) => l.key === editor.editKey) : null;
  return (
    <>
      {editLine && (
        <LineEditSheet
          key={editLine.key}
          initial={editLine.text}
          onApply={editor.applyEdit}
          onRemove={() => {
            editor.setEditKey(null);
            editor.remove(editLine.key);
          }}
          onClose={() => editor.setEditKey(null)}
        />
      )}
      {editor.adding && <FactAddSheet cardId={editor.cardId} onAdd={editor.addProposals} onClose={() => editor.setAdding(false)} />}
      <Sheet
        open={editor.confirmLast}
        onClose={() => editor.setConfirmLast(false)}
        title="사실이 하나도 남지 않아요. 이 카드를 지울까요?"
        description="빈 카드는 만들 수 없어요. 지우면 직원에게 더는 보이지 않고, 나중에 다시 살릴 수 있어요."
      >
        {excludeError !== null && excludeError !== undefined && <ErrorInline message={apiErrorMessage(excludeError, "지우지 못했어요.")} />}
        <Button variant="danger" loading={excludePending} onClick={onExcludeCard}>
          카드 지우기
        </Button>
        <Button variant="secondary" onClick={() => editor.setConfirmLast(false)}>
          그대로 두기
        </Button>
      </Sheet>
    </>
  );
}

/** 편집 중 하단: 오류·충돌 배너, 사실 추가, 저장, 그만두기. */
export function FactCardEditFooter({ editor }: { editor: FactCardEditor }) {
  const { save } = editor;
  const [discard, setDiscard] = useState(false);
  const code = errorCode(save.error);
  const conflict = code !== null && CONFLICT_CODES.includes(code);
  return (
    <>
      {save.error &&
        (conflict ? (
          <div role="alert" className="flex flex-col gap-2 rounded-[16px] bg-danger-50 px-4 py-3" data-testid="fact-conflict">
            <p className="text-[13px] leading-[1.45] text-danger-800 [word-break:keep-all]">{saveErrorMessage(save.error)}</p>
            {editor.reloadError !== null && (
              <p className="text-[13px] font-bold leading-[1.45] text-danger-800 [word-break:keep-all]" data-testid="fact-reload-error">
                {apiErrorMessage(editor.reloadError, "최신 내용을 불러오지 못했어요.")} 고친 내용은 그대로 뒀어요. 다시 눌러 주세요.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void editor.reloadLatest()}
                disabled={editor.facts.isFetching}
                className="min-h-11 rounded-full bg-surface px-3.5 text-[13px] font-bold text-danger-700 disabled:opacity-50"
              >
                최신 내용 불러오기(고친 내용은 사라져요)
              </button>
              <button
                type="button"
                onClick={() => {
                  save.reset();
                  editor.clearReloadError();
                }}
                className="min-h-11 rounded-full px-3.5 text-[13px] font-bold text-ink-muted">
                그대로 두기
              </button>
            </div>
          </div>
        ) : code === "CARD_WOULD_BE_EMPTY" ? (
          <ErrorInline message={saveErrorMessage(save.error)} onRetry={() => editor.setConfirmLast(true)} retryLabel="카드 지우기" />
        ) : isRetryable(save.error) ? (
          <ErrorInline message={saveErrorMessage(save.error)} onRetry={editor.submit} retrying={save.isPending} />
        ) : (
          <ErrorInline message={saveErrorMessage(save.error)} />
        ))}
      {/* 주 행동은 큰 버튼 하나, 나가기는 그 아래 작은 글자(스펙 '주 행동은 버튼 하나', 2026-11-08 다시 판단).
          고친 게 없으면 수정 완료도 그냥 읽는 화면으로 — 눌러도 안 되는 버튼을 두지 않는다 */}
      <Button loading={save.isPending} onClick={() => (editor.dirty ? editor.submit() : editor.cancel())}>
        수정 완료
      </Button>
      <TextButton className="self-center! px-4" disabled={save.isPending} onClick={() => (editor.dirty ? setDiscard(true) : editor.cancel())}>
        돌아가기
      </TextButton>
      {/* 실수로 눌렀을 때 고친 걸 지키는 쪽(계속 고치기)이 기본 */}
      <ConfirmDialog
        open={discard}
        title="고친 내용을 버릴까요?"
        confirmLabel="버리고 나가기"
        cancelLabel="계속 고치기"
        tone="danger"
        onCancel={() => setDiscard(false)}
        onConfirm={() => {
          setDiscard(false);
          editor.cancel();
        }}
      />
    </>
  );
}
