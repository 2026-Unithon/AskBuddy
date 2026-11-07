"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ErrorInline, Skeleton, Surface, Switch } from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { checklistApi, type CardLinks } from "@/lib/checklist-api";
import {
  checklistCardQuery,
  checklistKeys,
  checklistShiftsQuery,
} from "@/lib/query";
import { useApp } from "@/lib/store";
export function CardAssignment({ cardId }: { cardId: number }) {
  const { state } = useApp();
  const client = useQueryClient();
  const links = useQuery(
    checklistCardQuery(state.token, state.storeId, cardId),
  );
  const shifts = useQuery(checklistShiftsQuery(state.token, state.storeId));
  const save = useMutation({
    mutationFn: (body: CardLinks) =>
      checklistApi.setCard(state.token!, cardId, body),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) }),
  });
  const data = links.data;
  return (
    <Surface className="p-4">
      <h2 className="text-[16px] font-bold">어느 근무조 할 일인가요?</h2>
      {(links.isLoading || shifts.isLoading) && (
        <Skeleton className="mt-3 h-16" />
      )}
      {links.error && (
        <ErrorInline
          message={apiErrorMessage(links.error, "연결을 불러오지 못했어요.")}
          onRetry={() => void links.refetch()}
        />
      )}
      {shifts.error && (
        <ErrorInline
          message={apiErrorMessage(shifts.error, "근무조를 불러오지 못했어요.")}
          onRetry={() => void shifts.refetch()}
        />
      )}
      {data && shifts.data && (
        // o06e: 공통과 근무조마다 스위치. 공통을 켜면 근무조는 꺼지고, 근무조를 켜면 공통은 꺼진다. 모두 끄면 할 일에서 빠진다
        <div className="mt-1 flex flex-col">
          <Switch
            label="공통"
            checked={data.checklist && data.shift_ids.length === 0}
            disabled={save.isPending}
            onChange={(on) => save.mutate({ checklist: on, shift_ids: [] })}
          />
          {shifts.data.items.map((s) => {
            const selected = data.checklist && data.shift_ids.includes(s.shift_id);
            return (
              <Switch
                key={s.shift_id}
                label={s.name}
                checked={selected}
                disabled={save.isPending}
                onChange={(on) => {
                  const ids = on ? [...data.shift_ids, s.shift_id] : data.shift_ids.filter((id) => id !== s.shift_id);
                  save.mutate({ checklist: ids.length > 0, shift_ids: ids });
                }}
              />
            );
          })}
        </div>
      )}
      {save.error && (
        <ErrorInline
          message={apiErrorMessage(save.error, "이 변경은 저장되지 않았어요.")}
          onRetry={() => save.variables && save.mutate(save.variables)}
          retrying={save.isPending}
        />
      )}
    </Surface>
  );
}
