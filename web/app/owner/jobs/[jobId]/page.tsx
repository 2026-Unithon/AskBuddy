"use client";

import { reviewReasonText } from "@/lib/review-reason";
import { sourceErrorText } from "@/lib/source-error";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useNavHistory } from "@/lib/nav-history";
import { useState } from "react";
import {
  BackButton,
  Banner,
  Button,
  ButtonLink,
  Caption,
  Chip,
  CountBadge,
  Empty,
  ErrorInline,
  Icon,
  PageHeader,
  RefreshingHint,
  Screen,
  SectionTitle,
  Skeleton,
  Stagger,
  TextButton,
  useFeedback,
} from "@/components/kit";
import {
  ApiError,
  apiErrorMessage,
  isIngestJobActive,
  moveProductCard,
  mutateProductCard,
  retryIngestJob,
  extractIngestSourceAnyway,
  INTAKE_NONE_CODE,
  type CardListItem,
  type IngestJobDetail,
} from "@/lib/api";
import { JobSteps } from "@/components/owner/job-steps";
import { ReviewCard } from "@/components/owner/review-card";
import { bootstrapQuery, cardsQuery, ingestJobQuery, productCategoriesQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";
import { CancelJobButton } from "@/components/owner/cancel-job-button";

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
        <BackButton parent="/owner" label="오늘 매장" />
        <Empty title="잘못된 작업 주소예요" action={<ButtonLink href="/owner">오늘 매장으로</ButtonLink>} />
      </Screen>
    );
  }

  if (job.isLoading) {
    return (
      <Screen>
        <BackButton parent="/owner" label="오늘 매장" />
        <Skeleton className="h-24" />
        <Skeleton className="h-28" />
      </Screen>
    );
  }

  if (job.error || !data) {
    const missing = job.error instanceof ApiError && [403, 404].includes(job.error.status);
    return (
      <Screen>
        <BackButton parent="/owner" label="오늘 매장" />
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
        <BackButton parent="/owner" label="오늘 매장" />
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
    />
  );
}

function Processing({ job }: { job: IngestJobDetail }) {
  return (
    <Screen
      footer={
        <ButtonLink href="/owner" variant="secondary">
          오늘 매장으로
        </ButtonLink>
      }
    >
      <BackButton parent="/owner" label="오늘 매장" />
      <PageHeader title="정리하고 있어요" description="다른 화면으로 가도 계속 정리해요" />
      <JobSteps status={job.status} />
      <SourceList job={job} />
    </Screen>
  );
}

const SOURCE_STATUS: Record<string, string> = {
  QUEUED: "기다리는 중",
  EXTRACTING: "읽는 중",
  CLASSIFYING: "카드 제작 중",
  SUCCEEDED: "완료",
  PARTIAL: "일부 완료",
  NO_RESULT: "내용 없음",
  FAILED: "실패",
};

type JobSource = IngestJobDetail["sources"][number];

const SOURCE_ACTIVE = new Set(["QUEUED", "EXTRACTING", "CLASSIFYING"]);

/** 자료 한 줄의 상태: 진행 중이면 작은 스피너, 끝나면 체크. 글이 바뀔 때 페이드(o03b). */
function SourceState({ status }: { status: string }) {
  const label = status === "DELETED" ? "지워짐" : SOURCE_STATUS[status] ?? status;
  const tone = status === "FAILED" ? "danger" : status === "PARTIAL" ? "warn" : "neutral";
  return (
    <span key={status} className="flex shrink-0 items-center gap-1.5 animate-[screen-fade_var(--dur-base)_var(--ease-out)]">
      {SOURCE_ACTIVE.has(status) && <span aria-hidden className="size-3.5 rounded-full border-2 border-primary border-r-transparent motion-safe:animate-spin" />}
      {status === "SUCCEEDED" && <Icon name="check" size={14} className="text-primary" />}
      <Chip size="sm" tone={tone}>{label}</Chip>
    </span>
  );
}

// 업무 자료가 아니라고 판단해 추출하지 않은 자료. 작업 전체 상태와 무관하게 자료별로 고른다
function judgedNone(source: JobSource) {
  return source.status === "NO_RESULT" && source.error?.code === INTAKE_NONE_CODE && source.source_availability !== "DELETED";
}

function SourceList({ job, sources = job.sources }: { job: IngestJobDetail; sources?: JobSource[] }) {
  const active = isIngestJobActive(job.status);
  return (
    <ul className="flex w-full flex-col gap-2">
      {sources.map((source) => {
        const deleted = source.source_availability === "DELETED";
        return (
          <li key={source.source_id} className="flex flex-col gap-1 rounded-[16px] bg-surface px-4 py-3 shadow-card">
            <div className="flex items-center gap-2">
              <span className={`min-w-0 flex-1 truncate text-[14px] font-medium text-ink ${deleted ? "line-through opacity-60" : ""}`}>
                {source.filename}
              </span>
              <SourceState status={deleted ? "DELETED" : source.status} />
              {/* 오래 걸리거나 잘못 올렸을 때 그 자료 옆에서 멈춘다(2026-11-08). 끝나면 실패 화면에서 '다시 시도' */}
              {active && !deleted && SOURCE_ACTIVE.has(source.status) && (
                <CancelJobButton jobId={job.job_id} sourceCount={job.sources.length} />
              )}
            </div>
            {source.error && !deleted && <p className="text-[12px] text-danger-700">{sourceErrorText(source.error)}</p>}
            {!active && judgedNone(source) && <ExtractAnyway jobId={job.job_id} sourceId={source.source_id} />}
          </li>
        );
      })}
    </ul>
  );
}

/** 이 자료만 그래도 추출한다. 서버가 그 자료만 다시 처리하고, 작업 상태는 폴링이 따라간다. */
function ExtractAnyway({ jobId, sourceId }: { jobId: number; sourceId: number }) {
  const { state } = useApp();
  const client = useQueryClient();
  const extract = useMutation({
    mutationFn: () => extractIngestSourceAnyway(jobId, sourceId, state.token!),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.ingestJob(state.storeId, jobId) }),
        client.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) }),
      ]),
  });
  return (
    <div className="mt-1 flex flex-col gap-2">
      {extract.error && (
        <ErrorInline message={apiErrorMessage(extract.error, "이 자료를 다시 처리하지 못했어요.")} onRetry={() => extract.mutate()} retrying={extract.isPending} />
      )}
      <Button variant="secondary" className="py-[11px] text-[14px]" loading={extract.isPending} onClick={() => extract.mutate()}>
        그래도 추출하기
      </Button>
    </div>
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
}: {
  job: IngestJobDetail;
  cards: CardListItem[] | undefined;
  cardsLoading: boolean;
  cardsError: unknown;
  onRetryCards: () => void;
  retryBlock: React.ReactNode;
  onRetryJob: () => void;
}) {
  const { state } = useApp();
  const client = useQueryClient();
  const router = useRouter();
  const { markReplace } = useNavHistory();
  const { toast, snackbar } = useFeedback();
  const [approve, setApprove] = useState<ApproveState>({});
  // 빼기는 누르는 즉시 숨기고(낙관적) 실패하면 되살린다
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  const [cardErrors, setCardErrors] = useState<Record<number, string>>({});
  // 서버 restore 는 공개 전 카드를 빼기 전 상태(검수 필요면 검수 필요)로 되돌린다.
  // 되돌린 응답을 다시 받기 전 사이에도 위 섹션에 두고 검수 완료로 공개하지 않도록 빼기 전 이유를 기억한다
  const [checkReasons, setCheckReasons] = useState<Record<number, string>>({});
  // 매장의 첫 카드 공개라면 O5 초대로, 아니면 오늘 매장으로 (Figma O4 → O5 → O6)
  const bootstrap = useQuery(bootstrapQuery(state.token, state.userId, state.storeId));
  const firstGuide = bootstrap.data?.store ? !bootstrap.data.store.guide_completed : false;
  const categories = useQuery(productCategoriesQuery(state.token, state.storeId));

  const refreshCards = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: queryKeys.cardLists(state.storeId) }),
      client.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
    ]);
  const setHiddenFor = (cardId: number, on: boolean) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (on) next.add(cardId);
      else next.delete(cardId);
      return next;
    });

  const restore = useMutation({
    mutationFn: (cardId: number) => mutateProductCard(cardId, "restore", state.token!),
    onSuccess: (_, cardId) => setHiddenFor(cardId, false),
    // 카드가 숨어 있어 카드 위 글로는 보이지 않으므로 스낵바로 알린다
    onError: (_error, cardId) => snackbar({ message: "되돌리지 못했어요", actionLabel: "다시", onAction: () => restore.mutate(cardId) }),
    onSettled: refreshCards,
  });
  const exclude = useMutation({
    mutationFn: (cardId: number) => mutateProductCard(cardId, "exclude", state.token!),
    onMutate: (cardId) => {
      const card = cards?.find((item) => item.card_id === cardId);
      if (card?.review_status === "NEEDS_REVIEW") {
        setCheckReasons((prev) => ({ ...prev, [cardId]: reviewReasonText(card.needs_review_reason) }));
      }
      setHiddenFor(cardId, true);
      setCardErrors((prev) => {
        const next = { ...prev };
        delete next[cardId];
        return next;
      });
    },
    onSuccess: (_, cardId) => snackbar({ message: "뺐어요", actionLabel: "되돌리기", onAction: () => restore.mutate(cardId) }),
    onError: (error, cardId) => {
      setHiddenFor(cardId, false);
      setCardErrors((prev) => ({ ...prev, [cardId]: apiErrorMessage(error, "빼지 못했어요.") }));
    },
    onSettled: refreshCards,
  });
  const move = useMutation({
    mutationFn: ({ card, categoryId }: { card: CardListItem; categoryId: number }) =>
      moveProductCard(card.card_id, categoryId, card.updated_at, state.token!),
    onError: (error, { card }) => setCardErrors((prev) => ({ ...prev, [card.card_id]: apiErrorMessage(error, "카테고리를 옮기지 못했어요.") })),
    onSettled: refreshCards,
  });

  const visible = (cards ?? []).filter((card) => card.review_status !== "EXCLUDED" && !hidden.has(card.card_id));
  const isCheck = (card: CardListItem) => card.review_status === "NEEDS_REVIEW" || card.card_id in checkReasons;
  const needsReview = visible.filter(isCheck);
  const good = visible.filter((card) => !isCheck(card));
  // 검수 완료는 잘 정리된 카드 중 아직 공개 전(PENDING)인 것만 공개한다. 확인이 필요한 카드는 남겨 카드 탭에서 본다
  const toApprove = good.filter((card) => card.review_status === "PENDING" && approve[card.card_id] !== "done");

  // published: 이번에 공개한 카드가 있는가. 없으면 "지식이 추가됐어요"도, 첫 매장 초대 화면도 맞지 않는다
  const finish = (published: boolean) => {
    if (published) toast("지식이 추가됐어요", { keepOnNavigate: true });
    // 검수가 끝난 결과 화면으로는 돌아오지 않게 replace
    markReplace();
    router.replace(published && firstGuide ? "/owner/invite" : "/owner");
  };
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
          setApprove((prev) => ({ ...prev, [card.card_id]: { error: apiErrorMessage(error, "공개하지 못했어요.") } }));
        }
      }
      return failed;
    },
    onSettled: () =>
      Promise.all([refreshCards(), client.invalidateQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) })]),
    onSuccess: (failed) => {
      if (failed === 0) finish(true);
    },
  });

  const approveFailed = Object.values(approve).filter((value) => typeof value === "object").length;
  const groups = new Map<string, CardListItem[]>();
  for (const card of good) {
    const name = card.category?.name ?? "기타";
    groups.set(name, [...(groups.get(name) ?? []), card]);
  }
  const failedSources = job.sources.filter((source) => source.status === "FAILED" && source.source_availability !== "DELETED");
  const noneSources = job.sources.filter(judgedNone);
  const categoryItems = categories.data?.items ?? [];
  const cardProps = (card: CardListItem) => {
    const approveState = approve[card.card_id];
    const approveError = typeof approveState === "object" ? `${approveState.error} 검수 완료를 다시 누르면 이 카드만 다시 해요.` : undefined;
    return {
      card,
      categories: categoryItems,
      error: cardErrors[card.card_id] ?? approveError,
      onExclude: () => exclude.mutate(card.card_id),
      onMove: (categoryId: number) => move.mutate({ card, categoryId }),
    };
  };

  return (
    <Screen
      footer={
        <>
          {retryBlock}
          {approveFailed > 0 && !approveAll.isPending && (
            <p role="alert" className="text-center text-[13px] font-semibold text-danger-700 [word-break:keep-all]">
              {approveFailed}장은 공개하지 못했어요. 다시 누르면 그 카드만 다시 해요.
            </p>
          )}
          <Button loading={approveAll.isPending} disabled={!cards} onClick={() => (toApprove.length ? approveAll.mutate() : finish(false))}>
            검수 완료
          </Button>
          <TextButton
            className="self-center"
            onClick={() => {
              markReplace();
              router.replace("/owner");
            }}
          >
            나중에 하기
          </TextButton>
        </>
      }
    >
      <BackButton parent="/owner" label="오늘 매장" />
      <PageHeader title="카드가 준비됐어요! 검수 부탁드려요!" />

      {failedSources.length > 0 && (
        <Banner tone="danger" action={{ label: "다시 시도", onClick: onRetryJob }}>
          <p>처리하지 못한 자료가 있어요.</p>
          {failedSources.map((source) => (
            <p key={source.source_id} className="mt-0.5 text-[13px] font-normal">
              {source.filename}: {sourceErrorText(source.error)}
            </p>
          ))}
        </Banner>
      )}
      {cardsLoading && (
        <>
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </>
      )}
      {Boolean(cardsError) && <ErrorInline message={apiErrorMessage(cardsError, "카드를 불러오지 못했어요.")} onRetry={onRetryCards} />}

      {needsReview.length > 0 && (
        <section aria-labelledby="review-check" className="flex flex-col gap-3">
          <SectionTitle>
            <span id="review-check">맞는지 확인해 주세요!</span>
            <CountBadge n={needsReview.length} />
          </SectionTitle>
          <Stagger>
            {needsReview.map((card) => (
              <ReviewCard key={card.card_id} tone="check" reason={card.needs_review_reason ? reviewReasonText(card.needs_review_reason) : checkReasons[card.card_id]} {...cardProps(card)} />
            ))}
          </Stagger>
        </section>
      )}

      {good.length > 0 && (
        <section aria-labelledby="review-good" className="flex flex-col gap-3">
          <div>
            <SectionTitle>
              <span id="review-good">잘 정리됐어요</span>
            </SectionTitle>
            <Caption>그대로 두셔도 돼요</Caption>
          </div>
          {[...groups.entries()].map(([name, list]) => (
            <div key={name} className="flex flex-col gap-2">
              <p className="text-[13px] font-bold text-ink-muted">{name}</p>
              <Stagger>
                {list.map((card) => (
                  <ReviewCard key={card.card_id} tone="good" {...cardProps(card)} />
                ))}
              </Stagger>
            </div>
          ))}
        </section>
      )}

      {noneSources.length > 0 && (
        <section className="flex flex-col gap-3">
          <SectionTitle>
            추출하지 않은 자료
            <CountBadge n={noneSources.length} />
          </SectionTitle>
          <SourceList job={job} sources={noneSources} />
        </section>
      )}

      <RefreshingHint active={approveAll.isPending} />
    </Screen>
  );
}
