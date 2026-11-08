"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { BuddyImage, Button, ErrorInline } from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { PUSH_MESSAGE, enablePersonalPush } from "@/lib/push";
import { approvedSessionQuery, joinStatusQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

const COPY = {
  NONE: { title: "아직 합류한 매장이 없어요", body: "사장님께 받은 초대 링크를 열면 합류 요청이 바로 가요." },
  PENDING: { title: "사장님 승인을 기다리고 있어요", body: "승인되면 바로 알려 드리고 시작할 수 있어요." },
  REJECTED: { title: "합류가 승인되지 않았어요", body: "사장님께 확인한 뒤 초대 링크로 다시 요청해 주세요." },
  REMOVED: { title: "매장에서 나가게 되었어요", body: "다시 합류하려면 사장님께 초대 링크를 받아 주세요." },
} as const;

const PUSH_COPY = {
  enabled: "승인되면 알림으로 알려 드릴게요.",
  denied: "알림이 꺼져 있어요. 앱을 다시 열면 승인 여부를 확인할 수 있어요.",
  unsupported: "이 브라우저는 알림을 받을 수 없어요. 홈 화면에 추가한 앱에서 열어 주세요.",
  failed: "알림 설정에 실패했어요. 다시 시도해 주세요.",
  not_configured: "지금은 알림을 보낼 수 없어요. 앱을 다시 열면 확인할 수 있어요.",
} as const;

export default function StaffPendingPage() {
  const router = useRouter();
  const { state } = useApp();
  const status = useQuery(joinStatusQuery(state.token, state.userId));
  const [push, setPush] = useState<keyof typeof PUSH_COPY | "busy" | null>(null);
  const { refetch } = status;

  // 서비스 워커가 Push 를 받으면 바로 다시 조회한다(폴링 없음)
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const onMessage = (event: MessageEvent<unknown>) => {
      if (event.data && typeof event.data === "object" && "type" in event.data && event.data.type === PUSH_MESSAGE) void refetch();
    };
    navigator.serviceWorker.addEventListener("message", onMessage);
    return () => navigator.serviceWorker.removeEventListener("message", onMessage);
  }, [refetch]);

  const approved = useQuery(approvedSessionQuery(state.userId, status.data?.status === "APPROVED" && !state.storeId));
  useEffect(() => {
    if (approved.data || state.storeId) router.replace("/staff");
  }, [approved.data, state.storeId, router]);

  async function turnOnPush() {
    if (!state.token) return;
    setPush("busy");
    try {
      setPush(await enablePersonalPush(state.token));
    } catch {
      setPush("failed");
    }
  }

  const kind = status.data && status.data.status !== "APPROVED" ? status.data.status : null;
  return (
    <>
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
        <BuddyImage size={110} />
        {status.isPending && <p className="text-[15px] leading-[1.5] text-ink-muted [word-break:keep-all]" role="status">확인하고 있어요…</p>}
        {status.isError && (
          <ErrorInline message={apiErrorMessage(status.error, "상태를 불러오지 못했어요.")} onRetry={() => void status.refetch()} retrying={status.isRefetching} />
        )}
        {kind && (
          <>
            {status.data?.store_name && <p className="text-[14px] font-bold text-primary">{status.data.store_name}</p>}
            <h1 className="text-[26px] font-bold leading-[1.35] tracking-[-0.52px] text-ink [word-break:keep-all]">{COPY[kind].title}</h1>
            <p className="text-[15px] leading-[1.5] text-ink-muted [word-break:keep-all]">{COPY[kind].body}</p>
          </>
        )}
        {kind === "PENDING" && push !== "enabled" && (
          <Button loading={push === "busy"} onClick={() => void turnOnPush()}>
            승인되면 알림 받기
          </Button>
        )}
        {push && push !== "busy" && <p className="text-[15px] leading-[1.5] text-ink-muted [word-break:keep-all]" role="status">{PUSH_COPY[push]}</p>}
        {approved.isError && <ErrorInline message="승인은 완료됐지만 연결에 실패했어요." onRetry={() => void approved.refetch()} retrying={approved.isRefetching} />}
        {status.data?.status === "APPROVED" && <p className="text-[15px] leading-[1.5] text-ink-muted [word-break:keep-all]" role="status">승인됐어요. 시작하는 중…</p>}
      </div>
    </>
  );
}
