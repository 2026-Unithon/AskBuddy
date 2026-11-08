"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BackButton,
  Button,
  ButtonLink,
  Caption,
  Chip,
  Empty,
  ErrorInline,
  PageHeader,
  RefreshingHint,
  Screen,
  Skeleton,
  Surface,
  TextButton,
  useFeedback,
} from "@/components/kit";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { diffWords } from "@/lib/diff-words";
import { apiErrorMessage, resolveKnowledgeProposal, type KnowledgeProposal } from "@/lib/api";
import { proposalsQuery, queryKeys, rKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

// O10 지식 제안 검토: 점주 답이 기존 카드를 보완(SUPPLEMENT)하거나 충돌(CONFLICT)할 때.
// 공개본은 점주가 고를 때까지 그대로다 (MVP §13-2).
function ProposalsScreen() {
  const { state } = useApp();
  const params = useSearchParams();
  const proposals = useQuery(proposalsQuery(state.token, state.storeId));
  // ?card_id= 로 오면 그 카드에 걸린 제안만(목록의 '다른 답이 있어요' 카드에서 들어올 때)
  const rawCardId = params.get("card_id");
  const cardId = rawCardId && /^\d+$/.test(rawCardId) ? Number(rawCardId) : null;
  const items = (proposals.data?.items ?? []).filter((item) => cardId === null || item.target_card_id === cardId);

  return (
    <Screen>
      <BackButton parent="/owner/cards" label="카드" />
      <PageHeader title="답변의 카드 반영 확인" description="직원에게 전달한 답변에서 카드로 정리한 내용을 확인해 주세요." />
      {proposals.isLoading && (
        <>
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </>
      )}
      {proposals.error && (
        <ErrorInline message={apiErrorMessage(proposals.error, "제안을 불러오지 못했어요.")} onRetry={() => void proposals.refetch()} retrying={proposals.isRefetching} />
      )}
      {proposals.data && items.length === 0 && (
        <Empty title="확인할 제안이 없어요" description="모두 정리됐어요." action={<ButtonLink href="/owner/cards">카드로</ButtonLink>} />
      )}
      {items.map((item) => (
        <ProposalCard key={item.proposal_id} proposal={item} />
      ))}
      <RefreshingHint active={proposals.isRefetching && !proposals.isLoading} />
    </Screen>
  );
}

export default function ProposalsPage() {
  return (
    <Suspense>
      <ProposalsScreen />
    </Suspense>
  );
}

function ProposalCard({ proposal }: { proposal: KnowledgeProposal }) {
  const { state } = useApp();
  const client = useQueryClient();
  const { toast } = useFeedback();
  const router = useRouter();
  const resolve = useMutation({
    mutationFn: (action: "approve" | "dismiss") => resolveKnowledgeProposal(proposal.proposal_id, action, state.token!),
    onSuccess: (_result, action) => {
      toast(action === "approve" ? "카드에 반영했어요" : "그대로 뒀어요", { keepOnNavigate: true });
      // 제안을 정리했으면 검수 필요 목록으로 돌아간다(이 화면에 남을 일이 없다)
      router.replace("/owner/cards?status=needs_review");
      return Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.proposals(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.faqs(state.storeId) }),
        client.invalidateQueries({ queryKey: rKeys.pending(state.storeId, state.userId) }),
        client.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) }),
      ]);
    },
  });
  const conflict = proposal.relation_type === "CONFLICT";
  const others = (proposal.affected_cards ?? []).filter((card) => card.card_id !== proposal.target_card_id).map((card) => card.title);
  const labels: Record<string, string> = { NEW: "새 대상의 카드", SUPPLEMENT: "기존 카드 변경", IDENTICAL: "이미 반영된 내용", CONFLICT: "다른 내용" };
  const blocked: Record<string, string> = {
    LEGACY: "예전 방식의 제안이라 공개할 사실 초안이 없어요. 카드에서 직접 고친 뒤 이 제안을 닫아 주세요.",
    NO_FACTS: "답변은 직원에게 전달했지만 카드에 넣을 사실을 찾지 못했어요. 답변을 보완하거나 제안을 닫아 주세요.",
    FACTS_PENDING: "내용이 카드 초안 때문에 보류됐어요. 카드에서 검수를 마친 뒤 다시 확인해 주세요.",
    NO_DRAFT: "공개할 카드 초안이 없어요. 카드 상태를 확인해 주세요.",
  };
  const blockedLabels: Record<string, string> = { LEGACY: "이전 제안", NO_FACTS: "카드로 정리할 사실 없음", FACTS_PENDING: "카드 반영 보류", NO_DRAFT: "카드 초안 없음" };
  return (
    <Surface className="flex flex-col gap-3 px-[18px] py-4">
      <div className="flex items-center gap-2">
        <Chip tone={conflict || !proposal.can_approve ? "warn" : "brand"}>{blockedLabels[proposal.approval_block_reason ?? ""] ?? labels[proposal.relation_type] ?? "확인이 필요한 내용"}</Chip>
      </div>
      <p className="text-[13px] leading-[1.45] text-ink-muted">직원 질문: {proposal.question_text}</p>
      {/* o08a: 지금 카드와 제안을 따로 보이지 않고, 바뀐 낱말만 강조한 한 덩어리로 */}
      <div className="flex flex-col gap-1">
        <p className="text-[16px] font-bold text-ink">{proposal.proposed_title ?? proposal.current_title ?? "카드"}</p>
        <p className="whitespace-pre-wrap text-[15px] leading-[1.6] text-ink">
          {diffWords(proposal.current_content ?? "", proposal.proposed_content ?? proposal.answer_text).map((part, i) =>
            part.kind === "same" ? (
              <span key={i} data-diff="same">{part.text}</span>
            ) : part.kind === "del" ? (
              <del key={i} data-diff="del" className="text-ink-muted">{part.text}</del>
            ) : (
              <ins key={i} data-diff="add" className="rounded-[4px] bg-brand-100 px-0.5 font-bold no-underline">{part.text}</ins>
            ),
          )}
        </p>
      </div>
      {proposal.approval_block_reason && <Caption>{blocked[proposal.approval_block_reason] ?? blocked.NO_DRAFT}</Caption>}
      {/* 승인하면 연결된 다른 카드의 지금 초안도 같이 공개된다. 사장님이 모르고 공개하지 않게 이름을 알린다 */}
      {proposal.can_approve && others.length > 0 && <Caption>승인하면 {others.join(", ")}도 함께 공개돼요</Caption>}
      {resolve.error && (
        <ErrorInline message={apiErrorMessage(resolve.error, "이 변경은 저장되지 않았어요.")} onRetry={() => resolve.variables && resolve.mutate(resolve.variables)} retrying={resolve.isPending} />
      )}
      {/* o08b: 주 버튼은 '수정 완료' 하나, 그대로 두기는 작은 글자 */}
      {proposal.can_approve && (
        <Button loading={resolve.isPending && resolve.variables === "approve"} disabled={resolve.isPending} onClick={() => resolve.mutate("approve")}>
          수정 완료
        </Button>
      )}
      <TextButton className="self-center" disabled={resolve.isPending} onClick={() => resolve.mutate("dismiss")}>
        이 답은 쓰지 않기
      </TextButton>
    </Surface>
  );
}
