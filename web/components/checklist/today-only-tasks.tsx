"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { CheckRow, ErrorInline, ListGroup } from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { ownerOpsKeys, todayTasksApi, type MyTodayTask } from "@/lib/owner-ops";
import { myTodayTasksQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

type Mine = { business_date: string; items: MyTodayTask[] };

/**
 * 알바 오늘 할 일 맨 위 "사장님이 보낸 오늘만 할 일". 매일 하는 체크리스트와 따로 보인다.
 * 화면에 보였으면 확인으로 남긴다(사장 화면의 '확인함'). 없으면 아무것도 그리지 않는다.
 */
export function TodayOnlyTasks() {
  const { state } = useApp();
  const key = ownerOpsKeys.myTodayTasks(state.storeId, state.userId);
  const mine = useQuery(myTodayTasksQuery(state.token, state.storeId, state.userId));
  // 이미 확인을 보낸 지시. 폴링마다 같은 요청을 다시 보내지 않는다
  const reported = useRef(new Set<number>());

  const { mutate: markSeen } = useMutation({
    mutationFn: (ids: number[]) => todayTasksApi.seen(state.token!, ids),
    // 실패하면 다음 조회 때 다시 알린다
    onError: (_error, ids) => ids.forEach((id) => reported.current.delete(id)),
  });
  const unseenKey = (mine.data?.items ?? []).filter((t) => !t.seen).map((t) => t.task_id).join(",");
  useEffect(() => {
    if (!unseenKey) return;
    const ids = unseenKey.split(",").map(Number).filter((id) => !reported.current.has(id));
    if (ids.length === 0) return;
    ids.forEach((id) => reported.current.add(id));
    markSeen(ids);
  }, [unseenKey, markSeen]);

  if (mine.error) {
    return (
      <ErrorInline
        message={apiErrorMessage(mine.error, "사장님이 보낸 할 일을 불러오지 못했어요.")}
        onRetry={() => void mine.refetch()}
        retrying={mine.isRefetching}
      />
    );
  }
  const items = mine.data?.items ?? [];
  if (items.length === 0) return null;
  return (
    <div data-testid="today-only-tasks" className="w-full">
      <ListGroup label="사장님이 보낸 오늘만 할 일">
        {items.map((task) => (
          <TaskLine key={task.task_id} task={task} queryKey={key} />
        ))}
      </ListGroup>
    </div>
  );
}

function TaskLine({ task, queryKey }: { task: MyTodayTask; queryKey: readonly unknown[] }) {
  const { state } = useApp();
  const client = useQueryClient();
  const patch = (done: boolean) =>
    client.setQueryData<Mine>(queryKey, (data) =>
      data && { ...data, items: data.items.map((t) => (t.task_id === task.task_id ? { ...t, done, seen: true } : t)) });
  const change = useMutation({
    mutationFn: (done: boolean) => todayTasksApi.done(state.token!, task.task_id, done),
    onMutate: async (done) => {
      await client.cancelQueries({ queryKey });
      patch(done);
    },
    onError: (_error, done) => patch(!done),
    onSettled: () => client.invalidateQueries({ queryKey }),
  });
  return (
    <CheckRow
      label={task.body}
      checked={task.done}
      saving={change.isPending}
      error={change.error ? apiErrorMessage(change.error, "저장되지 않았어요. 다시 눌러 주세요.") : undefined}
      onToggle={() => {
        if (!change.isPending) change.mutate(!task.done);
      }}
    />
  );
}
