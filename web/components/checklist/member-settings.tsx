"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BackButton,
  Caption,
  Empty,
  ErrorInline,
  PageHeader,
  Screen,
  Skeleton,
  Surface,
} from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import {
  checklistApi,
  type ChecklistMember,
  type Shift,
} from "@/lib/checklist-api";
import {
  checklistKeys,
  checklistMembersQuery,
  checklistShiftsQuery,
} from "@/lib/query";
import { useApp } from "@/lib/store";
export function MemberSettingsScreen() {
  const { state } = useApp();
  const members = useQuery(checklistMembersQuery(state.token, state.storeId));
  const shifts = useQuery(checklistShiftsQuery(state.token, state.storeId));
  return (
    <Screen>
      <BackButton href="/owner/settings" />
      <PageHeader
        title="직원 담당"
        description="여러 근무조를 고를 수 있어요. 비우면 전체 할 일을 봐요."
      />
      {(members.isLoading || shifts.isLoading) && <Skeleton className="h-64" />}
      {members.error && (
        <ErrorInline
          message={apiErrorMessage(members.error, "직원을 불러오지 못했어요.")}
          onRetry={() => void members.refetch()}
        />
      )}
      {shifts.error && (
        <ErrorInline
          message={apiErrorMessage(shifts.error, "근무조를 불러오지 못했어요.")}
          onRetry={() => void shifts.refetch()}
        />
      )}
      {members.data && shifts.data && (
        <>
          {members.data.items
            .filter((m) => m.role === "STAFF")
            .map((member) => (
              <MemberRow
                key={member.member_id}
                member={member}
                shifts={shifts.data.items}
              />
            ))}
          {members.data.items.filter((m) => m.role === "STAFF").length ===
            0 && (
            <Empty
              title="아직 알바생이 없어요"
              description="직원이 매장에 합류하면 담당 근무조를 정할 수 있어요"
            />
          )}
        </>
      )}
    </Screen>
  );
}
function MemberRow({
  member,
  shifts,
}: {
  member: ChecklistMember;
  shifts: Shift[];
}) {
  const { state } = useApp();
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: (ids: number[]) =>
      checklistApi.memberShifts(state.token!, member.member_id, ids),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) }),
  });
  return (
    <Surface className="p-4">
      <h2 className="text-[18px] font-bold">{member.name}</h2>
      <Caption>
        {member.shift_ids.length
          ? "공통 + 담당 근무조 할 일을 봐요"
          : "전체 할 일을 봐요"}
      </Caption>
      <div className="mt-3 flex flex-wrap gap-2">
        {shifts.map((shift) => {
          const chosen = member.shift_ids.includes(shift.shift_id);
          return (
            <button
              type="button"
              key={shift.shift_id}
              aria-pressed={chosen}
              disabled={save.isPending}
              onClick={() =>
                save.mutate(
                  chosen
                    ? member.shift_ids.filter((id) => id !== shift.shift_id)
                    : [...member.shift_ids, shift.shift_id],
                )
              }
              className={`min-h-11 rounded-full px-4 ${chosen ? "bg-primary text-white" : "bg-empty text-primary"}`}
            >
              {shift.name}
            </button>
          );
        })}
      </div>
      {shifts.length === 0 && (
        <Caption>근무조가 없어 전체 할 일을 봐요</Caption>
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
