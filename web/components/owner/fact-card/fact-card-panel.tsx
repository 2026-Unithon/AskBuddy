"use client";

// W3b 사실 카드 본문: 사실 목록 읽기(Query)·편집 초안(지역 reducer)·저장(mutation).
// 서버 값은 cardFactsQuery 가 정본이다. 편집 중 초안은 저장 성공 전까지 서버에 쓰지 않는다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Caption, Chip, Empty, ErrorInline, RefreshingHint, Sheet, Skeleton, Surface } from "@/components/kit";
import { ApiError, apiErrorMessage, saveCardFacts, type CardDetailDto, type FactEditRequest, type FactFields, type ParsedFactProposal } from "@/lib/api";
import { cardFactsQuery, checklistKeys, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";
import { FactAddSheet } from "./fact-add-sheet";
import { FactEditSheet } from "./fact-edit-sheet";
import { CARD_EXCLUDED_TEXT, errorCode, isRetryable, saveErrorMessage } from "./fact-messages";
import { FactRowItem, blockLabel } from "./fact-row";
import { disturbsLocked, fieldsOf, isModified, moveStepRows, useFactEditDraft, type DraftBlock } from "./use-fact-edit-draft";

const CONFLICT_CODES = ["CARD_VERSION_CONFLICT", "FACT_CHANGED_ELSEWHERE"];
const ENTITY_TEXT = "메뉴 정리가 바뀌어 이 카드에서 고칠 수 없어요.";

/** 사실 카드 화면 상태. 페이지가 본문(FactCardPanel)과 하단(FactCardEditFooter)에 같이 넘긴다. */
export function useFactCardEditor(cardId: number, enabled: boolean) {
  const { state } = useApp();
  const client = useQueryClient();
  const facts = useQuery(cardFactsQuery(state.token, state.storeId, cardId, enabled));
  const { draft, dirty, remaining, actions, buildRequest } = useFactEditDraft();
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

  const save = useMutation({
    mutationFn: (request: FactEditRequest) => saveCardFacts(cardId, request, state.token!),
    onSuccess: async () => {
      await Promise.all([
        invalidateCard(),
        client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.faqs(state.storeId) }),
      ]);
      actions.clear();
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
    const request = buildRequest();
    setReloadError(null);
    if (request) save.mutate(request);
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
  const applyEdit = (fields: FactFields) => {
    if (editKey) actions.modify(editKey, fields);
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

const RAW_TEXT = "이 카드에는 사실로 나뉘지 않은 내용이 섞여 있어 사실 단위로 고칠 수 없어요.";

/** 두 줄 사이에 같은 블록 선행 관계가 있나(어느 쪽이든). */
function dependsOn(a: DraftBlock["rows"][number], b: DraftBlock["rows"][number]): boolean {
  const req = (x: typeof a, y: typeof a) => Boolean(x.base && y.base && x.base.requires.some((r) => r.fact_id === y.base!.fact_id));
  return req(a, b) || req(b, a);
}

/**
 * 이웃(j)과 자리를 바꿀 수 있나.
 * 순서 블록: 다른 곳에서 바뀐 줄·선행 관계가 걸린 두 줄·번호가 같거나 없는 두 줄은 막는다
 * (서버가 거절하거나, 맞바꿔도 저장할 변화가 없다). 새로 넣은 줄은 자리만 옮기고 번호를 다시 매기므로
 * 기존 절차 중간에 끼울 수 있다 — 단 다시 매긴 번호가 다른 곳에서 바뀐 줄을 건드리면 막는다.
 * 수치·목록은 표시 자리만 바뀐다.
 */
function canSwap(block: DraftBlock, i: number, j: number): boolean {
  const a = block.rows[i];
  const b = block.rows[j];
  if (!a || !b) return false;
  if (block.kind !== "STEPS") return true;
  if (a.base?.edit_block || b.base?.edit_block) return false;
  if (!a.base || !b.base) {
    const moved = moveStepRows(block.rows, i, j);
    return moved !== null && !disturbsLocked(moved);
  }
  if (a.fields.step_order === null || b.fields.step_order === null || a.fields.step_order === b.fields.step_order) return false;
  return !dependsOn(a, b);
}

/** 같은 블록 선행은 지금 초안의 단계 번호로, 블록 밖 선행은 서버 라벨 그대로. */
function draftRequireLabels(block: DraftBlock, i: number): string[] | undefined {
  const base = block.rows[i]?.base;
  if (!base) return undefined;
  return base.requires.map((r) => {
    const target = block.rows.find((row) => row.base?.fact_id === r.fact_id);
    return target && target.fields.step_order !== null ? `${target.fields.step_order}번` : r.label;
  });
}

/** 저장 실패 줄 표시: details 의 ref·fact_revision_id 가 가리키는 줄. */
function flaggedKey(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const ref = error.details.ref ?? error.details.fact_revision_id;
  if (typeof ref === "number") return `r${ref}`;
  if (typeof ref === "string") return /^\d+$/.test(ref) ? `r${ref}` : ref;
  return null;
}

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
  const flagged = save.error ? flaggedKey(save.error) : null;
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
      {!editor.editing && !view.editable && !excluded && (
        <Caption>{view.entity_problem ? ENTITY_TEXT : "지금은 이 카드를 사실 단위로 고칠 수 없어요."}</Caption>
      )}
      {!editor.editing && view.editable && editor.hasRaw && !excluded && <Caption>{RAW_TEXT}</Caption>}
      {draft
        ? draft.blocks.map((block) => (
            <Surface key={block.key} as="section" className="flex flex-col px-[18px] pb-1 pt-3">
              <div className="flex">
                <Chip>{blockLabel(block.kind, block.variant)}</Chip>
              </div>
              {block.kind === "STEPS" && <Caption className="pt-1.5">위·아래로 옮기면 일하는 순서가 바뀌어요.</Caption>}
              <ul className="flex flex-col">
                {block.rows.map((row, i) => {
                  const steps = block.kind === "STEPS";
                  return (
                    <FactRowItem
                      key={row.key}
                      fields={row.fields}
                      base={row.base}
                      state={!row.base ? "ADDED" : isModified(row) ? "MODIFIED" : null}
                      flagged={flagged === row.key}
                      requireLabels={steps ? draftRequireLabels(block, i) : undefined}
                      edit={{
                        locked,
                        isSteps: steps,
                        canUp: canSwap(block, i, i - 1),
                        canDown: canSwap(block, i, i + 1),
                        onEdit: () => editor.setEditKey(row.key),
                        onRemove: () => editor.remove(row.key),
                        onMove: (dir) => (steps ? editor.actions.moveStep(row.key, dir) : editor.actions.moveDisplay(row.key, dir)),
                      }}
                    />
                  );
                })}
              </ul>
            </Surface>
          ))
        : view.blocks.map((block) => (
            <Surface key={block.block_id} as="section" className="flex flex-col px-[18px] pb-1 pt-3">
              <div className="flex">
                <Chip>{blockLabel(block.kind, block.variant)}</Chip>
              </div>
              <ul className="flex flex-col">
                {block.facts.map((row) => (
                  <FactRowItem key={row.fact_revision_id} fields={fieldsOf(row)} base={row} />
                ))}
              </ul>
            </Surface>
          ))}
    </div>
  );
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
  const editRow = editor.editKey && draft ? draft.blocks.flatMap((b) => b.rows).find((r) => r.key === editor.editKey) : null;
  return (
    <>
      {editRow && (
        <FactEditSheet
          key={editRow.key}
          cardId={editor.cardId}
          baseRevisionId={editRow.base?.fact_revision_id ?? null}
          initial={editRow.fields}
          hadValue={editRow.base ? editRow.base.value !== null : editRow.fields.value !== null}
          onApply={editor.applyEdit}
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
      <Button loading={save.isPending} disabled={!editor.dirty} onClick={editor.submit}>
        고친 내용 저장
      </Button>
      <div className="flex gap-2">
        <Button variant="secondary" disabled={save.isPending} onClick={() => editor.setAdding(true)}>
          사실 추가
        </Button>
        <Button variant="secondary" disabled={save.isPending} onClick={editor.cancel}>
          그만두기
        </Button>
      </div>
    </>
  );
}
