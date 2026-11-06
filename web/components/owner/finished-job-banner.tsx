"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Banner } from "@/components/kit";
import { cardsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

/** 오늘 매장 위 "정리 끝!" 배너(o03c). 검수를 기다리는 카드가 있는 가장 최근 작업으로 보낸다. 서버 카드 상태가 정본이다. */
export function FinishedJobBanner() {
  const { state } = useApp();
  const router = useRouter();
  const pending = useQuery(cardsQuery(state.token, state.storeId, { status: "pending" }));
  const jobIds = (pending.data?.items ?? []).map((card) => card.job_id).filter((id): id is number => id !== null);
  if (!jobIds.length) return null;
  const latest = Math.max(...jobIds);
  return (
    <Banner tone="info" action={{ label: "검수하기", onClick: () => router.push(`/owner/jobs/${latest}`) }}>
      정리 끝!
    </Banner>
  );
}
