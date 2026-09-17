"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApp } from "@/lib/store";
import { rKeys, rNotificationsQuery } from "@/lib/query";
import { rReadNotification, type RNotification } from "@/lib/r-v2-api";
import { RError, RLoading } from "./r-v2-chat";

const button = "min-h-11 rounded-xl border px-4 py-2 disabled:opacity-50";
// 알림 본문의 임의 주소를 실행하지 않는다. 서버가 발행하는 직원 대화 경로만 연다.
function chatDestination(destination: string) {
  return /^\/staff\/chat\/v2\?session_id=[1-9]\d*$/.test(destination) ? destination : null;
}

export default function RV2Notifications() {
  const { state } = useApp();
  const router = useRouter();
  const client = useQueryClient();
  const query = useInfiniteQuery(rNotificationsQuery(state.token, state.storeId, state.userId));
  const read = useMutation({
    mutationFn: (notice: RNotification) => rReadNotification(state.token!, notice.notification_id),
    onSuccess: async (_data, notice) => {
      await client.invalidateQueries({ queryKey: rKeys.notifications(state.storeId, state.userId) });
      const destination = chatDestination(notice.destination);
      if (destination) {
        await client.invalidateQueries({ queryKey: rKeys.history(state.storeId, state.userId, destination.split("=")[1]) });
        router.push(destination);
      }
    },
  });
  const notices = query.data?.pages.flatMap((page) => page.notifications) ?? [];
  return <main className="w-full space-y-4 p-4 text-base" data-testid="r-notifications">
    <h1 className="text-xl font-bold">답변 알림</h1>
    <Link className="inline-block min-h-11 py-2 underline" href="/staff/chat/v2">대화로 돌아가기</Link>
    {query.isLoading && <RLoading />}
    {query.error && <RError error={query.error} retry={() => void query.refetch()} />}
    {query.isFetching && !query.isLoading && <p role="status">알림 갱신 중…</p>}
    {query.data && notices.length === 0 && <p>아직 도착한 답변 알림이 없습니다. 사장님이 답변하면 여기에서 확인할 수 있어요.</p>}
    <ul className="space-y-3">{notices.map((notice) => <li key={notice.notification_id} className="space-y-2 rounded-2xl border bg-white p-4 break-words">
      <p className="font-semibold">{notice.title} · {notice.read ? "읽음" : "읽지 않음"}</p>
      <p className="whitespace-pre-wrap">{notice.body}</p>
      <button className={button} disabled={read.isPending || (!chatDestination(notice.destination) && notice.read)} onClick={() => read.mutate(notice)}>{chatDestination(notice.destination) ? "답변 확인" : "읽음으로 표시"}</button>
    </li>)}</ul>
    {read.error && <RError error={read.error} retry={() => read.variables && read.mutate(read.variables)} />}
    {query.hasNextPage && <button className={button} disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>다음 알림 보기</button>}
    <button className={button} disabled={query.isFetching} onClick={() => void query.refetch()}>새 알림 확인</button>
  </main>;
}
