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
} from "@/components/kit";
import { apiErrorMessage, resolveKnowledgeProposal, type KnowledgeProposal } from "@/lib/api";
import { proposalsQuery, queryKeys, rKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

// O10 지식 제안 검토: 점주 답이 기존 카드를 보완(SUPPLEMENT)하거나 충돌(CONFLICT)할 때.
// 공개본은 점주가 고를 때까지 그대로다 (MVP §13-2).
export default function ProposalsPage() {
  const { state } = useApp();
  const proposals = useQuery(proposalsQuery(state.token, state.storeId));
  const items = proposals.data?.items ?? [];

  return (
    <Screen>
      <BackButton href="/owner/cards" label="카드" />
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

function ProposalCard({ proposal }: { proposal: KnowledgeProposal }) {
  const { state } = useApp();
  const client = useQueryClient();
  const resolve = useMutation({
    mutationFn: (action: "approve" | "dismiss") => resolveKnowledgeProposal(proposal.proposal_id, action, state.token!),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.proposals(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.faqs(state.storeId) }),
        client.invalidateQueries({ queryKey: rKeys.pending(state.storeId, state.userId) }),
        client.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) }),
      ]),
  });
  const conflict = proposal.relation_type === "CONFLICT";
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
      <p className="text-[13px] leading-[1.45] text-ink-muted">직원 질문 · {proposal.question_text}</p>
      <div className="flex flex-col gap-1 rounded-[14px] bg-background px-3.5 py-2.5">
        <p className="text-[12px] font-bold text-ink-muted">지금 카드</p>
        <p className="text-[15px] font-bold text-ink">{proposal.current_title ?? "—"}</p>
        <p className="whitespace-pre-wrap text-[14px] leading-[1.5] text-ink">{proposal.current_content ?? ""}</p>
      </div>
      <div className="flex flex-col gap-1 rounded-[14px] bg-empty px-3.5 py-2.5">
        <p className="text-[12px] font-bold text-primary">제안 내용</p>
        <p className="text-[15px] font-bold text-ink">{proposal.proposed_title ?? proposal.current_title ?? "—"}</p>
        <p className="whitespace-pre-wrap text-[14px] leading-[1.5] text-ink">{proposal.proposed_content ?? proposal.answer_text}</p>
      </div>
      {proposal.approval_block_reason && <Caption>{blocked[proposal.approval_block_reason] ?? blocked.NO_DRAFT}</Caption>}
      {(proposal.affected_cards ?? []).map((card) => <ButtonLink key={card.card_id} href={`/owner/cards/${card.card_id}`} variant="secondary">{card.title} 확인</ButtonLink>)}
      {proposal.can_approve && <Caption>승인하면 위에 연결된 카드의 현재 초안을 함께 공개해요. 각 카드 내용을 먼저 확인해 주세요.</Caption>}
      {resolve.error && (
        <ErrorInline message={apiErrorMessage(resolve.error, "이 변경은 저장되지 않았어요.")} onRetry={() => resolve.variables && resolve.mutate(resolve.variables)} retrying={resolve.isPending} />
      )}
      {proposal.can_approve && <Button loading={resolve.isPending && resolve.variables === "approve"} disabled={resolve.isPending} onClick={() => resolve.mutate("approve")}>
        확인한 카드 공개
      </Button>}
      <Button variant="secondary" disabled={resolve.isPending} onClick={() => resolve.mutate("dismiss")}>
        공개하지 않고 제안 닫기
      </Button>
    </Surface>
  );
}
