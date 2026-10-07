"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import {
  BackButton,
  BuddyImage,
  Button,
  ButtonLink,
  Caption,
  Chip,
  Empty,
  ErrorInline,
  PageHeader,
  RefreshingHint,
  Screen,
  SectionTitle,
  Skeleton,
  focusRing,
} from "@/components/kit";
import {
  ApiError,
  apiErrorMessage,
  isIngestJobActive,
  mutateProductCard,
  retryIngestJob,
  type CardListItem,
  type IngestJobDetail,
} from "@/lib/api";
import { bootstrapQuery, cardsQuery, ingestJobQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

// O4 알아서 정리됐어요 — 작업 하나의 처리 상태와 결과 카드 확인.
// 진행률은 만들지 않는다. 서버가 주는 상태·count 만 보여준다 (MVP §10-1).
export default function JobPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = /^\d+$/.test(params.jobId) ? Number(params.jobId) : 0;
  const { state } = useApp();
  const client = useQueryClient();
  const job = useQuery(ingestJobQuery(state.token, state.storeId, jobId));
  const data = job.data;
  const active = data ? isIngestJobActive(data.status) : false;
  const hasCards = Boolean(data && !active && data.counts.cards > 0);
  const cards = useQuery({ ...cardsQuery(state.token, state.storeId, { status: "all", jobId }), enabled: hasCards });

  const retry = useMutation({
    mutationFn: () => retryIngestJob(jobId, state.token!),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.ingestJob(state.storeId, jobId) }),
        client.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) }),
      ]),
  });

  if (!jobId) {
    return (
      <Screen>
        <BackButton href="/owner" label="오늘 매장" />
        <Empty title="잘못된 작업 주소예요" action={<ButtonLink href="/owner">오늘 매장으로</ButtonLink>} />
      </Screen>
    );
  }

  if (job.isLoading) {
    return (
      <Screen>
        <BackButton href="/owner" label="오늘 매장" />
        <Skeleton className="h-24" />
        <Skeleton className="h-28" />
      </Screen>
    );
  }

  if (job.error || !data) {
    const missing = job.error instanceof ApiError && [403, 404].includes(job.error.status);
    return (
      <Screen>
        <BackButton href="/owner" label="오늘 매장" />
        {missing ? (
          <Empty title="이 작업을 볼 수 없어요" description="다른 매장의 작업이거나 없는 작업이에요." action={<ButtonLink href="/owner">오늘 매장으로</ButtonLink>} />
        ) : (
          <ErrorInline message={apiErrorMessage(job.error, "작업 상태를 불러오지 못했어요.")} onRetry={() => void job.refetch()} retrying={job.isRefetching} />
        )}
      </Screen>
    );
  }

  if (active) return <Processing job={data} />;

  const retryBlock = retry.error ? (
    <ErrorInline message={apiErrorMessage(retry.error, "다시 시도하지 못했어요.")} onRetry={() => retry.mutate()} retrying={retry.isPending} />
  ) : null;

  if (data.status === "FAILED" || data.status === "NO_RESULT") {
    const failed = data.status === "FAILED";
    return (
      <Screen
        footer={
          <>
            {retryBlock}
            {failed && (
              <Button loading={retry.isPending} onClick={() => retry.mutate()}>
                다시 시도
              </Button>
            )}
            <ButtonLink href="/owner" variant="secondary">
              다른 자료 넣기
            </ButtonLink>
          </>
        }
      >
        <BackButton href="/owner" label="오늘 매장" />
        <PageHeader
          title={failed ? "처리하지 못했어요" : "찾은 내용이 없어요"}
          description={
            failed
              ? "올린 자료는 그대로 있어요. 다시 시도할 수 있어요."
              : "이 자료에서는 업무 내용을 찾지 못했어요. 원본을 확인하거나 다른 자료를 올려주세요."
          }
        />
        <SourceList job={data} />
      </Screen>
    );
  }

  return (
    <ResultReview
      job={data}
      cards={cards.data?.items}
      cardsLoading={cards.isLoading}
      cardsError={cards.error}
      onRetryCards={() => void cards.refetch()}
      retryBlock={retryBlock}
      onRetryJob={() => retry.mutate()}
      retrying={retry.isPending}
    />
  );
}

function Processing({ job }: { job: IngestJobDetail }) {
  return (
    <Screen footer={<ButtonLink href="/owner" variant="secondary">오늘 매장으로</ButtonLink>}>
      <BackButton href="/owner" label="오늘 매장" />
      <PageHeader title="정리하고 있어요" description="자료에서 업무 내용을 정리하고 있어요. 다른 화면으로 가도 계속 처리돼요." />
      <div className="flex justify-center py-4">
        <BuddyImage size={120} className="motion-safe:animate-pulse" />
      </div>
      <SourceList job={job} />
      <Caption>다 되면 알림으로 알려드려요</Caption>
    </Screen>
  );
}

const SOURCE_STATUS: Record<string, string> = {
  QUEUED: "기다리는 중",
  EXTRACTING: "읽는 중",
  CLASSIFYING: "나누는 중",
  SUCCEEDED: "완료",
  PARTIAL: "일부 완료",
  NO_RESULT: "내용 없음",
  FAILED: "실패",
};

function SourceList({ job }: { job: IngestJobDetail }) {
  return (
    <ul className="flex w-full flex-col gap-2">
      {job.sources.map((source) => {
        const deleted = source.source_availability === "DELETED";
        return (
          <li key={source.source_id} className="flex flex-col gap-1 rounded-[16px] bg-surface px-4 py-3 shadow-card">
            <div className="flex items-center gap-2">
              <span className={`min-w-0 flex-1 truncate text-[14px] font-medium text-ink ${deleted ? "line-through opacity-60" : ""}`}>
                {source.filename}
              </span>
              <Chip size="sm" tone={source.status === "FAILED" ? "danger" : source.status === "PARTIAL" ? "warn" : "neutral"}>
                {deleted ? "지워짐" : SOURCE_STATUS[source.status] ?? source.status}
              </Chip>
            </div>
            {source.error && !deleted && <p className="text-[12px] text-danger-700">{source.error.message}</p>}
          </li>
        );
      })}
    </ul>
  );
}

type ApproveState = Record<number, "saving" | "done" | { error: string }>;

function ResultReview({
  job,
  cards,
  cardsLoading,
  cardsError,
  onRetryCards,
  retryBlock,
  onRetryJob,
  retrying,
}: {
  job: IngestJobDetail;
  cards: CardListItem[] | undefined;
  cardsLoading: boolean;
  cardsError: unknown;
  onRetryCards: () => void;
  retryBlock: React.ReactNode;
  onRetryJob: () => void;
  retrying: boolean;
}) {
  const { state } = useApp();
  const client = useQueryClient();
  const router = useRouter();
  const [approve, setApprove] = useState<ApproveState>({});
  // 매장의 첫 카드 공개라면 O5 초대로, 아니면 오늘 매장으로 (Figma O4 → O5 → O6)
  const bootstrap = useQuery(bootstrapQuery(state.token, state.userId, state.storeId));
  const firstGuide = bootstrap.data?.store ? !bootstrap.data.store.guide_completed : false;

  const visible = (cards ?? []).filter((card) => card.review_status !== "EXCLUDED");
  const needsReview = visible.filter((card) => card.review_status === "NEEDS_REVIEW");
  const ready = visible.filter((card) => card.review_status !== "NEEDS_REVIEW");
  // "맞아요"는 확인 대기(PENDING) 카드만 공개한다. 확인이 필요한 카드는 하나씩 본다
  const toApprove = ready.filter((card) => card.review_status === "PENDING" && approve[card.card_id] !== "done");

  const approveAll = useMutation({
    mutationFn: async () => {
      let failed = 0;
      for (const card of toApprove) {
        setApprove((prev) => ({ ...prev, [card.card_id]: "saving" }));
        try {
          await mutateProductCard(card.card_id, "approve", state.token!);
          setApprove((prev) => ({ ...prev, [card.card_id]: "done" }));
        } catch (error) {
          failed += 1;
          setApprove((prev) => ({
            ...prev,
            [card.card_id]: { error: apiErrorMessage(error, "이 변경은 저장되지 않았어요.") },
          }));
        }
      }
      return failed;
    },
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
        client.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) }),
      ]),
    onSuccess: (failed) => {
      if (failed === 0 && needsReview.length === 0) router.push(firstGuide ? "/owner/invite" : "/owner");
    },
  });

  const groups = new Map<string, CardListItem[]>();
  for (const card of ready) {
    const name = card.category?.name ?? "기타";
    groups.set(name, [...(groups.get(name) ?? []), card]);
  }
  const sourceNames = job.sources.map((s) => s.filename).join(", ");
  const allDone = cards !== undefined && toApprove.length === 0;

  return (
    <Screen
      footer={
        <>
          {retryBlock}
          {allDone ? (
            <ButtonLink href="/owner">오늘 매장으로</ButtonLink>
          ) : (
            <Button loading={approveAll.isPending} disabled={!cards || toApprove.length === 0} onClick={() => approveAll.mutate()}>
              맞아요
            </Button>
          )}
          <ButtonLink href="/owner" variant="secondary">
            더 넣기
          </ButtonLink>
        </>
      }
    >
      <BackButton href="/owner" label="오늘 매장" />
      <PageHeader title="이렇게 나눴어요" description="다르면 눌러서 고치면 돼요" />

      {job.status === "PARTIAL" && (
        <ErrorInline message="준비된 카드와 처리하지 못한 자료가 있어요. 실패한 자료만 다시 시도할 수 있어요." onRetry={onRetryJob} retrying={retrying} />
      )}
      {cardsLoading && (
        <>
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </>
      )}
      {Boolean(cardsError) && (
        <ErrorInline message={apiErrorMessage(cardsError, "카드를 불러오지 못했어요.")} onRetry={onRetryCards} />
      )}

      {needsReview.length > 0 && (
        <>
          <SectionTitle>하나씩 봐 주세요 · {needsReview.length}</SectionTitle>
          {needsReview.map((card) => (
            <ResultCard key={card.card_id} card={card} label={card.needs_review_reason ?? "내용이 확실하지 않아요"} tone="warn" />
          ))}
        </>
      )}

      {[...groups.entries()].map(([name, list]) => (
        <section key={name} className="flex flex-col gap-3">
          {list.map((card, index) => (
            <ResultCard
              key={card.card_id}
              card={card}
              label={index === 0 ? `${name} · ${list.length}` : name}
              state={approve[card.card_id]}
            />
          ))}
        </section>
      ))}

      {sourceNames && <Caption>출처 · {sourceNames}</Caption>}
      <RefreshingHint active={approveAll.isPending} />
    </Screen>
  );
}

/** Figma O4 Group: 칩 + 제목 17 Bold + 요약 14. 누르면 카드 상세에서 고친다. */
function ResultCard({
  card,
  label,
  tone = "brand",
  state,
}: {
  card: CardListItem;
  label: string;
  tone?: "brand" | "warn";
  state?: ApproveState[number];
}) {
  const published = card.review_status === "APPROVED" || state === "done";
  const error = typeof state === "object" ? state.error : null;
  return (
    <Link
      href={`/owner/cards/${card.card_id}`}
      className={`flex w-full flex-col gap-1.5 rounded-[20px] bg-surface px-[18px] py-4 shadow-card ${focusRing}`}
    >
      <div className="flex items-center gap-2">
        <Chip tone={tone}>{label}</Chip>
        {published && <Chip size="sm" tone="neutral">공개됨</Chip>}
        {state === "saving" && <Chip size="sm" tone="neutral">공개하는 중</Chip>}
      </div>
      <p className="text-[17px] font-bold leading-[1.45] tracking-[-0.34px] text-ink [word-break:keep-all]">{card.title}</p>
      <p className="line-clamp-3 whitespace-pre-line text-[14px] leading-[1.45] tracking-[-0.14px] text-ink-muted">{card.content}</p>
      {error && <p className="text-[12px] text-danger-700">{error} &lsquo;맞아요&rsquo;를 다시 누르면 이 카드만 다시 시도해요.</p>}
    </Link>
  );
}
