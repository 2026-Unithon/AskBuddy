"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BackButton, CheckRow, Empty, ErrorInline, PageHeader, Screen, Skeleton, Surface, useFeedback } from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { checklistApi, type ChecklistMember, type Shift } from "@/lib/checklist-api";
import { checklistKeys, checklistMembersQuery, checklistShiftsQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

/** 직원 담당 근무조(o16a). 체크하면 바로 반영하고(낙관), 실패하면 되돌린다. */
export function MemberSettingsScreen() {
  const { state } = useApp();
  const members = useQuery(checklistMembersQuery(state.token, state.storeId));
  const shifts = useQuery(checklistShiftsQuery(state.token, state.storeId));
  const staff = members.data?.items.filter((m) => m.role === "STAFF") ?? [];
  return (
    <Screen>
      <BackButton parent="/owner/members" />
      <PageHeader title="직원 담당" />
      {(members.isLoading || shifts.isLoading) && <Skeleton className="h-64" />}
      {members.error && <ErrorInline message={apiErrorMessage(members.error, "직원을 불러오지 못했어요.")} onRetry={() => void members.refetch()} />}
      {shifts.error && <ErrorInline message={apiErrorMessage(shifts.error, "근무조를 불러오지 못했어요.")} onRetry={() => void shifts.refetch()} />}
      {members.data && shifts.data && (
        <>
          {staff.map((member) => (
            <MemberCard key={member.member_id} member={member} shifts={shifts.data.items} />
          ))}
          {staff.length === 0 && <Empty title="아직 알바생이 없어요" />}
          {staff.length > 0 && shifts.data.items.length === 0 && <Empty title="근무조가 없어요" />}
        </>
      )}
    </Screen>
  );
}

type Members = { items: ChecklistMember[] };

function MemberCard({ member, shifts }: { member: ChecklistMember; shifts: Shift[] }) {
  const { state } = useApp();
  const client = useQueryClient();
  const feedback = useFeedback();
  const key = checklistKeys.members(state.storeId);
  const save = useMutation({
    mutationFn: (ids: number[]) => checklistApi.memberShifts(state.token!, member.member_id, ids),
    // 낙관 반영: 화면을 먼저 바꾸고, 실패하면 누르기 전 값으로 되돌린다
    onMutate: (ids) => {
      // 진행 중 조회가 낙관 값을 덮지 않게 취소만 걸고, 화면은 기다리지 않고 바로 바꾼다
      void client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<Members>(key)?.items.find((m) => m.member_id === member.member_id)?.shift_ids;
      client.setQueryData<Members>(key, (data) =>
        data ? { ...data, items: data.items.map((m) => (m.member_id === member.member_id ? { ...m, shift_ids: ids } : m)) } : data,
      );
      return { before };
    },
    onError: (_error, _ids, context) => {
      if (!context?.before) return;
      client.setQueryData<Members>(key, (data) =>
        data ? { ...data, items: data.items.map((m) => (m.member_id === member.member_id ? { ...m, shift_ids: context.before! } : m)) } : data,
      );
    },
    onSuccess: () => feedback.toast("저장했어요"),
    onSettled: () => {
      // 저장이 겹쳐 있으면 마지막 것이 끝난 뒤에만 서버 값으로 맞춘다(중간 응답이 화면을 되돌리지 않게)
      if (client.isMutating({ mutationKey: ["member-shifts", member.member_id] }) <= 1) void client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) });
    },
    mutationKey: ["member-shifts", member.member_id],
    // 같은 직원 저장은 차례로 보낸다. 전체를 덮어쓰는 PUT 이라 겹치면 늦게 끝난 앞 요청이 뒤 선택을 지운다
    scope: { id: `member-shifts-${member.member_id}` },
  });
  // 다음 선택은 캐시의 최신 값에서 계산한다(연달아 누르면 앞 선택을 잃지 않는다)
  const toggle = (shiftId: number) => {
    const current = client.getQueryData<Members>(key)?.items.find((m) => m.member_id === member.member_id)?.shift_ids ?? member.shift_ids;
    save.mutate(current.includes(shiftId) ? current.filter((id) => id !== shiftId) : [...current, shiftId]);
  };
  return (
    <Surface className="px-[18px] pb-1 pt-4">
      <div data-member-shifts="">
        <h2 className="text-[18px] font-bold text-ink">{member.name}</h2>
        <ul className="mt-1 flex flex-col">
          {shifts.map((shift) => (
            <CheckRow key={shift.shift_id} label={shift.name} checked={member.shift_ids.includes(shift.shift_id)} onToggle={() => toggle(shift.shift_id)} />
          ))}
        </ul>
        {save.error && (
          <div className="pb-3">
            <ErrorInline message="이 변경은 저장되지 않았어요. 다시 눌러 주세요." />
          </div>
        )}
      </div>
    </Surface>
  );
}
