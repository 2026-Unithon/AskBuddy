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
import { proposalsQuery, queryKeys } from "@/lib/query";
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
      <PageHeader title="다른 답이 왔어요" description="기존 카드와 다른 부분이 있어요. 공개하기 전에 확인해주세요." />
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
      ]),
  });
  const conflict = proposal.relation_type === "CONFLICT";
  return (
    <Surface className="flex flex-col gap-3 px-[18px] py-4">
      <div className="flex items-center gap-2">
        <Chip tone={conflict ? "warn" : "brand"}>{conflict ? "다른 내용" : "더 자세한 내용"}</Chip>
      </div>
      <p className="text-[13px] leading-[1.45] text-ink-muted">직원 질문 · {proposal.question_text}</p>
      <div className="flex flex-col gap-1 rounded-[14px] bg-background px-3.5 py-2.5">
        <p className="text-[12px] font-bold text-ink-muted">지금 카드</p>
        <p className="text-[15px] font-bold text-ink">{proposal.current_title ?? "—"}</p>
        <p className="whitespace-pre-wrap text-[14px] leading-[1.5] text-ink">{proposal.current_content ?? ""}</p>
      </div>
      <div className="flex flex-col gap-1 rounded-[14px] bg-empty px-3.5 py-2.5">
        <p className="text-[12px] font-bold text-primary">바꿀 내용</p>
        <p className="text-[15px] font-bold text-ink">{proposal.proposed_title ?? proposal.current_title ?? "—"}</p>
        <p className="whitespace-pre-wrap text-[14px] leading-[1.5] text-ink">{proposal.proposed_content ?? proposal.answer_text}</p>
      </div>
      {proposal.reason && <Caption>{proposal.reason}</Caption>}
      {resolve.error && (
        <ErrorInline message={apiErrorMessage(resolve.error, "이 변경은 저장되지 않았어요.")} onRetry={() => resolve.variables && resolve.mutate(resolve.variables)} retrying={resolve.isPending} />
      )}
      <Button loading={resolve.isPending && resolve.variables === "approve"} disabled={resolve.isPending} onClick={() => resolve.mutate("approve")}>
        바꿀 내용으로 공개
      </Button>
      <Button variant="secondary" disabled={resolve.isPending} onClick={() => resolve.mutate("dismiss")}>
        지금 카드 그대로 두기
      </Button>
    </Surface>
  );
}
