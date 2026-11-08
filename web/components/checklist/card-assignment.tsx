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
      <div role="group" aria-labelledby={`card-shifts-${cardId}`}>
      <h2 id={`card-shifts-${cardId}`} className="text-[16px] font-bold">어느 근무조 할 일인가요?</h2>
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
        // 근무조마다 스위치 하나. 공통(모든 근무조)은 모두 켜진 것으로 보이고, 다 켜면 다시 공통으로 저장한다.
        // 처음 공개한 할 일 카드는 서버가 공통으로 켠다(2026-11-08 사용자: 기본은 모두 켜짐). 모두 끄면 할 일에서 빠진다
        <div className="mt-1 flex flex-col">
          {shifts.data.items.map((s) => {
            const all = shifts.data.items.map((x) => x.shift_id);
            const current = data.checklist ? (data.shift_ids.length === 0 ? all : data.shift_ids) : [];
            return (
              <Switch
                key={s.shift_id}
                label={s.name}
                checked={current.includes(s.shift_id)}
                disabled={save.isPending}
                onChange={(on) => {
                  const ids = on ? [...current, s.shift_id] : current.filter((id) => id !== s.shift_id);
                  const everyShift = all.every((id) => ids.includes(id));
                  save.mutate({ checklist: ids.length > 0, shift_ids: everyShift ? [] : all.filter((id) => ids.includes(id)) });
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
      </div>
    </Surface>
  );
}
