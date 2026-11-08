"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Banner } from "@/components/kit";
import { isIngestJobActive } from "@/lib/api";
import { cardsQuery, ingestJobsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

// 작업이 끝나고 이보다 오래 지나면 "정리 끝!" 대신 할 일 문구로
const FRESH_MS = 24 * 60 * 60 * 1000;

/**
 * 오늘 매장 위 "정리 끝!" 배너(o03c). 검수를 기다리는 카드(공개 전, 검수 필요)가 있는 가장 최근 작업으로 보낸다.
 * 상태마다 한 장만 받는다(목록이 아니라 '있는가'와 작업 id 만 필요하다). 서버 카드 상태가 정본이다.
 * 정리 중인 작업이 있으면 그 줄(ActiveJobBanner)만 보인다.
 */
export function FinishedJobBanner() {
  const { state } = useApp();
  const router = useRouter();
  const pending = useQuery(cardsQuery(state.token, state.storeId, { status: "pending", limit: 1 }));
  const review = useQuery(cardsQuery(state.token, state.storeId, { status: "needs_review", limit: 1 }));
  const jobs = useQuery(ingestJobsQuery(state.token, state.storeId));
  if ((jobs.data?.items ?? []).some((job) => isIngestJobActive(job.status))) return null;
  const jobIds = [...(pending.data?.items ?? []), ...(review.data?.items ?? [])]
    .map((card) => card.job_id)
    .filter((id): id is number => id !== null);
  if (!jobIds.length) return null;
  const latest = Math.max(...jobIds);
  const completedAt = jobs.data?.items.find((job) => job.job_id === latest)?.completed_at;
  // 지금 대신 작업 목록을 받은 시각과 비교한다(그리는 동안 값이 흔들리지 않는다)
  const fresh = completedAt ? jobs.dataUpdatedAt - new Date(completedAt).getTime() < FRESH_MS : false;
  return (
    <Banner tone="info" action={{ label: "검수하기", onClick: () => router.push(`/owner/jobs/${latest}`) }}>
      {fresh ? "정리 끝!" : "검수할 카드가 있어요"}
    </Banner>
  );
}
