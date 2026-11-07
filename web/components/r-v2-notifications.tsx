"use client";

import { useRouter } from "next/navigation";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BackButton,
  Button,
  CountBadge,
  Empty,
  ErrorInline,
  PageHeader,
  Screen,
  Skeleton,
  TextButton,
  focusRing,
} from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { useApp } from "@/lib/store";
import { rKeys, rNotificationsQuery } from "@/lib/query";
import { rReadNotification, type RNotification } from "@/lib/r-v2-api";

// 알림 본문의 임의 주소를 실행하지 않는다. 서버가 발행하는 직원 대화 경로(옛 /staff/chat/v2, 새 /staff/ask)만 연다.
function chatSession(destination: string): string | null {
  const match = destination.match(/^\/staff\/(?:chat\/v2|ask)\?session_id=([1-9]\d*)$/);
  return match ? match[1] : null;
}

/** 답변 알림(s09a). 당겨서 새로고침, 머리 뱃지, 누르면 읽음 저장 뒤 그 대화로. */
export default function RV2Notifications() {
  const { state } = useApp();
  const router = useRouter();
  const client = useQueryClient();
  const query = useInfiniteQuery(rNotificationsQuery(state.token, state.storeId, state.userId));
  const read = useMutation({
    mutationFn: (notice: RNotification) => rReadNotification(state.token!, notice.notification_id),
    onSuccess: async (_data, notice) => {
      await client.invalidateQueries({ queryKey: rKeys.notifications(state.storeId, state.userId) });
      const session = chatSession(notice.destination);
      if (session) {
        await client.invalidateQueries({ queryKey: rKeys.history(state.storeId, state.userId, session) });
        router.push(`/staff/ask?session_id=${session}`);
      }
    },
  });
  const notices = query.data?.pages.flatMap((page) => page.notifications) ?? [];
  const unread = notices.filter((n) => !n.read).length;

  return (
    <Screen onRefresh={() => query.refetch()}>
      <BackButton parent="/staff" />
      <PageHeader
        title={
          <>
            답변 알림
            {unread > 0 && <CountBadge n={unread} tone="danger" />}
          </>
        }
        action={
          <TextButton disabled={query.isFetching} onClick={() => void query.refetch()}>
            새로고침
          </TextButton>
        }
      />
      {query.isLoading && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      )}
      {query.error && (
        <ErrorInline message={apiErrorMessage(query.error, "알림을 불러오지 못했어요.")} onRetry={() => void query.refetch()} retrying={query.isRefetching} />
      )}
      {query.data && notices.length === 0 && <Empty title="아직 도착한 답이 없어요" />}
      {read.error && <ErrorInline message={apiErrorMessage(read.error, "읽음으로 바꾸지 못했어요.")} />}
      <ul className="flex flex-col gap-2">
        {notices.map((notice) => {
          const opening = read.isPending && read.variables?.notification_id === notice.notification_id;
          return (
            <li key={notice.notification_id}>
              <button
                type="button"
                data-notice=""
                data-opening={opening || undefined}
                disabled={read.isPending}
                onClick={() => read.mutate(notice)}
                className={`flex w-full items-start gap-3 rounded-[20px] bg-surface p-4 text-left shadow-card transition-transform duration-[var(--dur-base)] ease-[var(--ease-out)] ${
                  opening ? "scale-[1.02]" : ""
                } ${notice.read ? "opacity-60" : ""} ${focusRing}`}
              >
                {!notice.read && <span className="mt-2 size-2 shrink-0 rounded-full bg-primary" aria-label="읽지 않음" />}
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className={`text-[15px] text-ink ${notice.read ? "" : "font-bold"}`}>{notice.title}</span>
                  <span className="line-clamp-2 whitespace-pre-wrap break-words text-[14px] text-ink-muted">{notice.body}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {query.hasNextPage && (
        <Button variant="secondary" loading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
          이전 알림 더 보기
        </Button>
      )}
    </Screen>
  );
}
