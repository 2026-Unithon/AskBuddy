import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import {
  getNotificationSupport,
  getPreflight,
  getLearnItem,
  getIngestJob,
  getProductCard,
  getRoadmap,
  getReclassificationJob,
  isIngestJobActive,
  listCategories,
  listChat,
  listFaqs,
  listIngestJobs,
  listKnowledgeProposals,
  listNotifications,
  listPending,
  listQuestions,
  listProductCards,
  listProductCategories,
  listStaff,
  type CardFilters,
} from "@/lib/api";

export function preflightQuery() {
  return queryOptions({
    queryKey: ["preflight", false] as const,
    queryFn: ({ signal }) => getPreflight(false, signal),
    staleTime: 10_000,
  });
}

export const queryKeys = {
  categories: (storeId: number | null) => ["categories", storeId] as const,
  ingestJobs: (storeId: number | null) => ["ingest-jobs", storeId] as const,
  ingestJob: (storeId: number | null, jobId: number) => ["ingest-job", storeId, jobId] as const,
  cardLists: (storeId: number | null) => ["cards", storeId] as const,
  cards: (storeId: number | null, filters: CardFilters) => [...queryKeys.cardLists(storeId), filters] as const,
  card: (storeId: number | null, cardId: number) => ["card", storeId, cardId] as const,
  productCategories: (storeId: number | null) => ["product-categories", storeId] as const,
  reclassification: (storeId: number | null, jobId: number) => ["reclassification", storeId, jobId] as const,
  proposals: (storeId: number | null) => ["knowledge-proposals", storeId] as const,
  faqs: (storeId: number | null) => ["faqs", storeId] as const,
  learnItem: (storeId: number | null, userId: number | null, itemId: number) =>
    ["learn-item", storeId, userId, itemId] as const,
  roadmapRoot: (storeId: number | null) => ["roadmap", storeId] as const,
  roadmap: (storeId: number | null, userId: number | null) =>
    [...queryKeys.roadmapRoot(storeId), userId] as const,
  chat: (storeId: number | null, userId: number | null) => ["chat", storeId, userId] as const,
  pending: (storeId: number | null) => ["pending-questions", storeId] as const,
  questions: (storeId: number | null) => ["questions", storeId] as const,
  staff: (storeId: number | null) => ["staff", storeId] as const,
  notificationsRoot: (storeId: number | null) => ["notifications", storeId] as const,
  notifications: (storeId: number | null) => [...queryKeys.notificationsRoot(storeId), "latest"] as const,
  notificationPages: (storeId: number | null) => [...queryKeys.notificationsRoot(storeId), "pages"] as const,
  notificationSupport: (storeId: number | null) => ["notification-support", storeId] as const,
};

export function ingestJobsQuery(token: string | null, storeId: number | null) {
  return queryOptions({
    queryKey: queryKeys.ingestJobs(storeId),
    queryFn: ({ signal }) => listIngestJobs(token!, signal),
    enabled: Boolean(token && storeId),
    refetchInterval: (query) =>
      query.state.data?.items.some((job) => isIngestJobActive(job.status)) ? 2_000 : false,
    staleTime: 2_000,
  });
}

export function ingestJobQuery(token: string | null, storeId: number | null, jobId: number) {
  return queryOptions({
    queryKey: queryKeys.ingestJob(storeId, jobId),
    queryFn: ({ signal }) => getIngestJob(jobId, token!, signal),
    enabled: Boolean(token && storeId && jobId > 0),
    refetchInterval: (query) => query.state.data && isIngestJobActive(query.state.data.status) ? 2_000 : false,
  });
}

export function categoriesQuery(token: string | null, storeId: number | null) {
  return queryOptions({
    queryKey: queryKeys.categories(storeId),
    queryFn: ({ signal }) => listCategories(token!, signal),
    enabled: Boolean(token && storeId),
  });
}

export function cardsQuery(token: string | null, storeId: number | null, filters: CardFilters) {
  return queryOptions({
    queryKey: queryKeys.cards(storeId, filters),
    queryFn: ({ signal }) => listProductCards(token!, filters, signal),
    enabled: Boolean(token && storeId),
  });
}

export function cardsInfiniteQuery(token: string | null, storeId: number | null, filters: CardFilters) {
  return infiniteQueryOptions({
    queryKey: queryKeys.cards(storeId, filters),
    queryFn: ({ signal, pageParam }) => listProductCards(token!, { ...filters, cursor: pageParam, limit: 30 }, signal),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: Boolean(token && storeId),
  });
}

export function cardQuery(token: string | null, storeId: number | null, cardId: number) {
  return queryOptions({
    queryKey: queryKeys.card(storeId, cardId),
    queryFn: ({ signal }) => getProductCard(cardId, token!, signal),
    enabled: Boolean(token && storeId && cardId > 0),
  });
}

export function productCategoriesQuery(token: string | null, storeId: number | null) {
  return queryOptions({
    queryKey: queryKeys.productCategories(storeId),
    queryFn: ({ signal }) => listProductCategories(token!, signal),
    enabled: Boolean(token && storeId),
    refetchInterval: (query) => {
      const status = query.state.data?.reclassification?.status;
      return status === "QUEUED" || status === "RUNNING" ? 2_000 : false;
    },
    staleTime: 2_000,
  });
}

export function reclassificationQuery(token: string | null, storeId: number | null, jobId: number) {
  return queryOptions({
    queryKey: queryKeys.reclassification(storeId, jobId),
    queryFn: ({ signal }) => getReclassificationJob(jobId, token!, signal),
    enabled: Boolean(token && storeId && jobId > 0),
    refetchInterval: (query) => query.state.data?.status === "QUEUED" || query.state.data?.status === "RUNNING" ? 2_000 : false,
  });
}

export function proposalsQuery(token: string | null, storeId: number | null) {
  return queryOptions({
    queryKey: queryKeys.proposals(storeId),
    queryFn: ({ signal }) => listKnowledgeProposals(token!, signal),
    enabled: Boolean(token && storeId),
  });
}

export function faqsQuery(token: string | null, storeId: number | null) {
  return queryOptions({
    queryKey: queryKeys.faqs(storeId),
    queryFn: ({ signal }) => listFaqs(token!, signal),
    enabled: Boolean(token && storeId),
  });
}

export function learnItemQuery(token: string | null, storeId: number | null, userId: number | null, itemId: number) {
  return queryOptions({
    queryKey: queryKeys.learnItem(storeId, userId, itemId),
    queryFn: ({ signal }) => getLearnItem(itemId, token!, signal),
    enabled: Boolean(token && storeId && userId && itemId > 0),
  });
}

export function questionsQuery(token: string | null, storeId: number | null) {
  return queryOptions({
    queryKey: queryKeys.questions(storeId),
    queryFn: ({ signal }) => listQuestions(token!, signal),
    enabled: Boolean(token && storeId),
    refetchInterval: 5_000,
  });
}

export function pendingQuery(token: string | null, storeId: number | null) {
  return queryOptions({
    queryKey: queryKeys.pending(storeId),
    queryFn: ({ signal }) => listPending(token!, "WAITING", signal),
    enabled: Boolean(token && storeId),
    refetchInterval: 5_000,
  });
}

export function staffQuery(token: string | null, storeId: number | null) {
  return queryOptions({
    queryKey: queryKeys.staff(storeId),
    queryFn: ({ signal }) => listStaff(token!, signal),
    enabled: Boolean(token && storeId),
    staleTime: 10_000,
  });
}

export function notificationsQuery(token: string | null, storeId: number | null) {
  return queryOptions({
    queryKey: queryKeys.notifications(storeId),
    queryFn: ({ signal }) => listNotifications(token!, { limit: 50 }, signal),
    enabled: Boolean(token && storeId),
    refetchInterval: 5_000,
  });
}

export function notificationPagesQuery(token: string | null, storeId: number | null) {
  return infiniteQueryOptions({
    queryKey: queryKeys.notificationPages(storeId),
    queryFn: ({ pageParam, signal }) => listNotifications(token!, { cursor: pageParam, limit: 30 }, signal),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: Boolean(token && storeId),
    refetchInterval: 5_000,
  });
}

export function notificationSupportQuery(token: string | null, storeId: number | null) {
  return queryOptions({
    queryKey: queryKeys.notificationSupport(storeId),
    queryFn: ({ signal }) => getNotificationSupport(token!, signal),
    enabled: Boolean(token && storeId),
    staleTime: 60_000,
  });
}

export function chatQuery(token: string | null, storeId: number | null, userId: number | null) {
  return queryOptions({
    queryKey: queryKeys.chat(storeId, userId),
    queryFn: ({ signal }) => listChat(token!, signal),
    enabled: Boolean(token && storeId && userId),
    refetchInterval: 5_000,
  });
}

export function roadmapQuery(token: string | null, storeId: number | null, userId: number | null) {
  return queryOptions({
    queryKey: queryKeys.roadmap(storeId, userId),
    queryFn: ({ signal }) => getRoadmap(token!, signal),
    enabled: Boolean(token && storeId && userId),
  });
}
