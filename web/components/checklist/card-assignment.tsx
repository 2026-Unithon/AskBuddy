"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Caption, ErrorInline, Skeleton, Surface } from "@/components/kit";
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
        <>
          <button
            type="button"
            role="switch"
            aria-checked={data.checklist}
            disabled={save.isPending}
            onClick={() =>
              save.mutate({
                checklist: !data.checklist,
                shift_ids: data.checklist ? [] : data.shift_ids,
              })
            }
            className="my-2 flex min-h-11 w-full items-center justify-between"
          >
            <span>오늘 할 일에 넣기</span>
            <span className="font-bold text-primary">
              {data.checklist ? "켜짐" : "꺼짐"}
            </span>
          </button>
          {data.checklist && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                aria-pressed={data.shift_ids.length === 0}
                disabled={save.isPending}
                onClick={() => save.mutate({ checklist: true, shift_ids: [] })}
                className={`min-h-11 rounded-full px-4 ${data.shift_ids.length === 0 ? "bg-primary text-white" : "bg-empty text-primary"}`}
              >
                공통
              </button>
              {shifts.data.items.map((s) => {
                const selected = data.shift_ids.includes(s.shift_id);
                return (
                  <button
                    type="button"
                    key={s.shift_id}
                    disabled={save.isPending}
                    aria-pressed={selected}
                    onClick={() => {
                      const ids = selected
                        ? data.shift_ids.filter((id) => id !== s.shift_id)
                        : [...data.shift_ids, s.shift_id];
                      save.mutate({
                        checklist: ids.length > 0,
                        shift_ids: ids,
                      });
                    }}
                    className={`min-h-11 rounded-full px-4 ${selected ? "bg-primary text-white" : "bg-empty text-primary"}`}
                  >
                    {s.name}
                  </button>
                );
              })}
            </div>
          )}
          <Caption>
            공통은 모두에게 보여요. 근무조를 여러 개 고를 수 있어요. 마지막
            근무조를 빼면 오늘 할 일에서도 빠져요.
          </Caption>
        </>
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
