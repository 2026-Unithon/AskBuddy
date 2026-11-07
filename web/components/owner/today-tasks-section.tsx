"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  Button,
  Caption,
  Chip,
  Empty,
  ErrorInline,
  SectionTitle,
  Sheet,
  Skeleton,
  Surface,
  TextButton,
} from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { ownerOpsKeys, targetState, todayTasksApi, type OwnerTodayTask } from "@/lib/owner-ops";
import { checklistMembersQuery, ownerTodayTasksQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

const STATE_LABEL = { done: "완료", seen: "확인함", unseen: "아직 안 봄" } as const;
const STATE_TONE = { done: "brand", seen: "neutral", unseen: "warn" } as const;

/**
 * O6 오늘 매장의 "오늘만 할 일". 전화 대신 보내는 지시라 영업일이 지나면 목록에서 빠진다.
 * 서버 목록이 정본이고, 이 컴포넌트는 보내기 입력만 화면 상태로 든다.
 */
export function TodayTasksSection() {
  const { state } = useApp();
  const tasks = useQuery(ownerTodayTasksQuery(state.token, state.storeId));
  const [open, setOpen] = useState(false);
  const items = tasks.data?.items ?? [];

  return (
    <>
      <div className="flex items-center justify-between">
        <SectionTitle>오늘만 할 일{items.length > 0 ? ` ${items.length}` : ""}</SectionTitle>
        <TextButton data-testid="today-task-open" onClick={() => setOpen(true)} className="text-primary">
          보내기
        </TextButton>
      </div>
      {tasks.isLoading && <Skeleton className="h-[76px]" />}
      {tasks.error && (
        <ErrorInline
          message={apiErrorMessage(tasks.error, "오늘만 할 일을 불러오지 못했어요.")}
          onRetry={() => void tasks.refetch()}
          retrying={tasks.isRefetching}
        />
      )}
      {tasks.data && items.length === 0 && (
        <Empty
          buddy={false}
          title="오늘 따로 시킬 일이 있나요?"
          description="전화 대신 여기서 보내면 알바생 폰에 바로 알림이 가고, 오늘이 지나면 사라져요"
        />
      )}
      {items.map((task) => (
        <TaskRow key={task.task_id} task={task} />
      ))}
      {/* 공통 Sheet 가 앱 틀(.app-mobile-frame)로 스스로 띄워 입력창·탭 위까지 덮는다(화면 개선 계획 2) */}
      {open && <SendSheet onClose={() => setOpen(false)} />}
    </>
  );
}

function TaskRow({ task }: { task: OwnerTodayTask }) {
  const { state } = useApp();
  const client = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const cancel = useMutation({
    mutationFn: () => todayTasksApi.cancel(state.token!, task.task_id),
    onSuccess: () => client.invalidateQueries({ queryKey: ownerOpsKeys.todayTasks(state.storeId) }),
  });
  const done = task.targets.filter((t) => t.done_at).length;
  return (
    <Surface as="section" className="flex flex-col gap-3 p-[18px]">
      <p data-testid="owner-today-task" className="whitespace-pre-line text-[15px] font-semibold text-ink [word-break:keep-all]">
        {task.body}
      </p>
      <ul className="flex flex-wrap gap-1.5" aria-label="받은 사람">
        {task.targets.map((target) => {
          const s = targetState(target);
          return (
            <li key={target.member_id}>
              <Chip tone={STATE_TONE[s]} size="sm">
                {target.name} {STATE_LABEL[s]}
              </Chip>
            </li>
          );
        })}
      </ul>
      <div className="flex items-center justify-between">
        <Caption>
          {task.targets.length}명 중 {done}명 완료
        </Caption>
        {confirm ? (
          <span className="flex gap-3">
            <TextButton onClick={() => setConfirm(false)} disabled={cancel.isPending}>
              그대로 두기
            </TextButton>
            <TextButton className="text-danger-700" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              거두기
            </TextButton>
          </span>
        ) : (
          <TextButton onClick={() => setConfirm(true)}>거두기</TextButton>
        )}
      </div>
      {cancel.error && <ErrorInline message={apiErrorMessage(cancel.error, "거두지 못했어요. 다시 눌러 주세요.")} />}
    </Surface>
  );
}

function SendSheet({ onClose }: { onClose: () => void }) {
  const { state } = useApp();
  const client = useQueryClient();
  const members = useQuery(checklistMembersQuery(state.token, state.storeId));
  const staff = (members.data?.items ?? []).filter((m) => m.role === "STAFF");
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<number[]>([]);
  // 다듬은 문장은 사장이 보고 고친 뒤 보낸다. 원문이 바뀌면 다시 다듬어야 한다
  const [polished, setPolished] = useState<string | null>(null);

  const polish = useMutation({
    mutationFn: (value: string) => todayTasksApi.polish(state.token!, value),
    onSuccess: (result) => setPolished(result.body),
  });
  const send = useMutation({
    mutationFn: (body: string | undefined) =>
      todayTasksApi.create(state.token!, { text: text.trim(), body, member_ids: picked }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ownerOpsKeys.todayTasks(state.storeId) });
      onClose();
    },
  });

  const busy = polish.isPending || send.isPending;
  const toggle = (id: number) => setPicked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  const allPicked = staff.length > 0 && staff.every((m) => picked.includes(m.member_id));
  const ready = text.trim().length > 0 && picked.length > 0 && !busy;

  return (
    <Sheet
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title="오늘만 할 일 보내기"
      description="고른 알바생에게 바로 알림이 가요. 오늘 영업이 끝나면 목록에서 사라져요."
    >
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-semibold text-ink">무엇을 시킬까요?</span>
        <textarea
          data-testid="today-task-text"
          value={text}
          maxLength={300}
          rows={3}
          disabled={busy}
          onChange={(e) => {
            setText(e.target.value);
            setPolished(null);
          }}
          placeholder="예) 마감하고 쓰레기통 가게 밖으로 내놔"
          className="w-full resize-none rounded-[14px] border-[1.5px] border-empty bg-surface px-3.5 py-3 text-[15px] text-ink"
        />
      </label>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1.5 text-[13px] font-semibold text-ink">누구에게 보낼까요?</legend>
        {members.isLoading && <Skeleton className="h-11" />}
        {members.error && (
          <ErrorInline
            message={apiErrorMessage(members.error, "직원 목록을 불러오지 못했어요.")}
            onRetry={() => void members.refetch()}
            retrying={members.isRefetching}
          />
        )}
        {members.data && staff.length === 0 && <Caption>아직 연결된 알바생이 없어요. 초대부터 해 주세요.</Caption>}
        {staff.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              aria-pressed={allPicked}
              disabled={busy}
              onClick={() => setPicked(allPicked ? [] : staff.map((m) => m.member_id))}
              className={`min-h-11 rounded-full px-4 ${allPicked ? "bg-primary text-white" : "bg-surface text-primary"}`}
            >
              모두
            </button>
            {staff.map((m) => (
              <button
                key={m.member_id}
                type="button"
                data-testid="today-task-member"
                aria-pressed={picked.includes(m.member_id)}
                disabled={busy}
                onClick={() => toggle(m.member_id)}
                className={`min-h-11 rounded-full px-4 ${picked.includes(m.member_id) ? "bg-primary text-white" : "bg-surface text-primary"}`}
              >
                {m.name}
              </button>
            ))}
          </div>
        )}
      </fieldset>

      {polished !== null && (
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-ink">이렇게 보내요 (고쳐도 돼요)</span>
          <textarea
            data-testid="today-task-polished"
            value={polished}
            maxLength={300}
            rows={3}
            disabled={busy}
            onChange={(e) => setPolished(e.target.value)}
            className="w-full resize-none rounded-[14px] bg-empty px-3.5 py-3 text-[15px] text-ink"
          />
        </label>
      )}
      {/* 다듬기는 선택 기능이다. 어떤 실패든 원문으로 보낼 수 있다는 것만 알린다(503 공통 문구로 덮지 않는다) */}
      {polish.error && <ErrorInline message="문장을 다듬지 못했어요. 적은 그대로 보낼 수 있어요." />}
      {send.error && (
        <ErrorInline
          message={apiErrorMessage(send.error, "보내지 못했어요.")}
          onRetry={() => send.mutate(send.variables)}
          retrying={send.isPending}
        />
      )}

      {polished === null ? (
        <>
          <Button data-testid="today-task-polish" variant="secondary" disabled={!ready} loading={polish.isPending}
            onClick={() => polish.mutate(text.trim())}>
            부드럽게 다듬기
          </Button>
          <Button data-testid="today-task-send" disabled={!ready} loading={send.isPending} onClick={() => send.mutate(undefined)}>
            적은 그대로 보내기
          </Button>
        </>
      ) : (
        <>
          <Button data-testid="today-task-send" disabled={!ready || polished.trim().length === 0} loading={send.isPending}
            onClick={() => send.mutate(polished.trim())}>
            이 문장으로 보내기
          </Button>
          <Button variant="secondary" disabled={busy} onClick={() => setPolished(null)}>
            적은 그대로 돌아가기
          </Button>
        </>
      )}
    </Sheet>
  );
}
