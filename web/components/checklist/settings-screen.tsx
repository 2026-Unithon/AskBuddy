"use client";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  BackButton,
  Button,
  ButtonLink,
  Caption,
  CheckRow,
  Empty,
  ErrorInline,
  Icon,
  PageHeader,
  Screen,
  Sheet,
  Skeleton,
  SortableList,
  Surface,
  Switch,
  TextButton,
  TimeWheel,
  useFeedback,
} from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { checklistApi, type Shift, type ShiftInput } from "@/lib/checklist-api";
import {
  cardsInfiniteQuery,
  checklistKeys,
  checklistSettingsQuery,
  checklistShiftsQuery,
} from "@/lib/query";
import { useApp } from "@/lib/store";

export function ShiftSettingsScreen() {
  const { state } = useApp();
  const client = useQueryClient();
  const feedback = useFeedback();
  const shifts = useQuery(checklistShiftsQuery(state.token, state.storeId));
  const settings = useQuery(checklistSettingsQuery(state.token, state.storeId));
  const [edit, setEdit] = useState<number | "new" | null>(null);
  const [remove, setRemove] = useState<number | null>(null);
  const [cards, setCards] = useState<number | null>(null);
  const [dayStart, setDayStart] = useState<string | null>(null);
  const editedShift = shifts.data?.items.find((s) => s.shift_id === edit);
  const cardsShift = shifts.data?.items.find((s) => s.shift_id === cards);
  const removedShift = shifts.data?.items.find((s) => s.shift_id === remove);
  const refresh = () => client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) });
  const preset = useMutation({
    mutationFn: () => checklistApi.preset(state.token!),
    onSuccess: refresh,
  });
  // 순서 저장은 줄 세워 하나씩 보낸다(scope). 저장 중에도 계속 옮길 수 있고, 마지막 저장이 끝나야 서버 순서로 맞춘다
  const orderKey = ["shift-order", state.storeId] as const;
  const order = useMutation({
    mutationKey: orderKey,
    scope: { id: `shift-order-${state.storeId}` },
    mutationFn: (ids: number[]) => checklistApi.order(state.token!, ids),
    // 실패하면 서버 순서로 되돌린다(낙관 순서 버림). 뒤에 기다리는 저장이 있으면 그 순서를 덮지 않게 기다린다
    onSettled: () => (client.isMutating({ mutationKey: orderKey }) <= 1 ? refresh() : undefined),
  });
  // 끄는 동안의 순서는 캐시에 바로 반영하고(낙관), 놓을 때 한 번만 저장한다. 끌기 전 순서를 기억해 바뀌었을 때만 보낸다
  const dragStart = useRef<number[] | null>(null);
  const deletion = useMutation({
    mutationFn: (id: number) => checklistApi.deleteShift(state.token!, id),
    onSuccess: async () => {
      setRemove(null);
      feedback.toast("지웠어요");
      await refresh();
    },
  });
  const setting = useMutation({
    mutationFn: (body: { business_day_starts_at?: string; staff_records_visible?: boolean }) => checklistApi.setSettings(state.token!, body),
    onSuccess: refresh,
  });
  const items = shifts.data?.items ?? [];
  const shiftsKey = checklistKeys.shifts(state.storeId);
  const moveShift = (key: string, dir: -1 | 1) => {
    const current = client.getQueryData<{ items: Shift[] }>(shiftsKey)?.items ?? items;
    dragStart.current ??= current.map((s) => s.shift_id);
    const next = [...current];
    const index = next.findIndex((s) => s.shift_id === Number(key));
    [next[index], next[index + dir]] = [next[index + dir], next[index]];
    void client.cancelQueries({ queryKey: shiftsKey });
    client.setQueryData<{ items: Shift[] }>(shiftsKey, (data) => (data ? { ...data, items: next } : data));
  };
  const saveOrder = () => {
    const before = dragStart.current;
    dragStart.current = null;
    const ids = (client.getQueryData<{ items: Shift[] }>(shiftsKey)?.items ?? items).map((s) => s.shift_id);
    if (before && before.join() !== ids.join()) order.mutate(ids);
  };
  return (
    <Screen>
      <BackButton parent="/owner/settings" />
      <PageHeader
        title="근무조"
        action={
          shifts.data ? (
            <Button className="min-h-10 w-auto! px-4 py-2!" onClick={() => setEdit("new")}>
              추가
            </Button>
          ) : undefined
        }
      />
      {shifts.isLoading && <Skeleton className="h-64" />}
      {shifts.error && <ErrorInline message={apiErrorMessage(shifts.error, "근무조를 불러오지 못했어요.")} onRetry={() => void shifts.refetch()} />}
      {shifts.data?.items.length === 0 && (
        <>
          <Empty title="아직 근무조가 없어요" description="나누지 않으면 전체 할 일을 함께 봐요." />
          <Button loading={preset.isPending} onClick={() => preset.mutate()}>
            오픈, 미들, 마감으로 시작하기
          </Button>
        </>
      )}
      {items.length > 0 && (
        <SortableList
          items={items.map((s) => ({ ...s, key: String(s.shift_id), label: s.name }))}
          canMove={() => true}
          onMove={moveShift}
          onEnd={saveOrder}
          renderItem={(shift) => (
            <div className="py-3">
              <h2 className="text-[20px] font-bold text-ink">{shift.name}</h2>
              <Caption>
                {shift.starts_at ? `${shift.starts_at} ~ ${shift.ends_at}${shift.ends_at! <= shift.starts_at ? ", 다음 날 끝" : ""}` : "시간 없음"}
              </Caption>
              <div className="mt-3 flex items-center gap-2">
                <Button className="min-h-11 flex-1 py-2.5!" onClick={() => setCards(shift.shift_id)}>
                  할 일 담기
                </Button>
                <Button variant="secondary" className="min-h-11 flex-1 py-2.5!" onClick={() => setEdit(shift.shift_id)}>
                  고치기
                </Button>
                <TextButton
                  className="text-danger-700!"
                  onClick={() => {
                    deletion.reset();
                    setRemove(shift.shift_id);
                  }}
                >
                  지우기
                </TextButton>
              </div>
            </div>
          )}
        />
      )}
      {preset.error && <ErrorInline message={apiErrorMessage(preset.error, "근무조를 만들지 못했어요.")} onRetry={() => preset.mutate()} />}
      {order.error && <ErrorInline message={apiErrorMessage(order.error, "순서를 저장하지 못했어요.")} onRetry={() => order.variables && order.mutate(order.variables)} />}
      <ButtonLink href="/owner/member-shifts" variant="secondary">
        직원 담당 근무조
      </ButtonLink>
      <ButtonLink href="/owner/cards" variant="secondary">
        카드에서 공통 할 일 담기
      </ButtonLink>
      {settings.isLoading && <Skeleton className="h-28" />}
      {settings.error && <ErrorInline message={apiErrorMessage(settings.error, "매장 설정을 불러오지 못했어요.")} onRetry={() => void settings.refetch()} />}
      {settings.data && (
        <Surface className="flex flex-col px-[18px] py-1">
          <button
            type="button"
            onClick={() => setDayStart(settings.data.business_day_starts_at.slice(0, 5))}
            className="flex min-h-12 w-full items-center justify-between gap-3 text-left text-[16px] text-ink"
          >
            <span>영업일 시작</span>
            <span className="flex items-center gap-1 font-bold text-primary">
              {settings.data.business_day_starts_at.slice(0, 5)}
              <Icon name="right" size={16} className="text-ink-muted" />
            </span>
          </button>
          <Switch
            label="알바생 기록"
            checked={settings.data.staff_records_visible}
            disabled={setting.isPending}
            onChange={(next) => setting.mutate({ staff_records_visible: next })}
          />
        </Surface>
      )}
      {setting.error && (
        <ErrorInline
          message={apiErrorMessage(setting.error, "이 변경은 저장되지 않았어요.")}
          onRetry={() => setting.variables && setting.mutate(setting.variables)}
          retrying={setting.isPending}
        />
      )}
      <Sheet open={dayStart !== null} onClose={() => !setting.isPending && setDayStart(null)} title="영업일 시작 시각">
        {dayStart !== null && <TimeWheel label="영업일 시작" value={dayStart} onChange={setDayStart} />}
        <Button
          loading={setting.isPending}
          onClick={() =>
            dayStart &&
            setting.mutate(
              { business_day_starts_at: dayStart },
              {
                onSuccess: () => {
                  setDayStart(null);
                  feedback.toast("저장했어요");
                },
              },
            )
          }
        >
          저장
        </Button>
      </Sheet>
      {(edit === "new" || editedShift) && <ShiftEditor shift={editedShift ?? null} onClose={() => setEdit(null)} />}
      {cardsShift && <ShiftCards shift={cardsShift} onClose={() => setCards(null)} />}
      <Sheet
        open={Boolean(remove)}
        onClose={() => {
          if (!deletion.isPending) setRemove(null);
        }}
        title={`${removedShift?.name ?? "근무조"}를 지울까요?`}
        description="과거 기록은 남아요."
      >
        {deletion.error && <ErrorInline message={apiErrorMessage(deletion.error, "지우지 못했어요.")} />}
        <Button variant="danger" loading={deletion.isPending} onClick={() => remove && deletion.mutate(remove)}>
          지우기
        </Button>
        <Button variant="secondary" disabled={deletion.isPending} onClick={() => setRemove(null)}>
          그대로 두기
        </Button>
      </Sheet>
    </Screen>
  );
}
function ShiftEditor({ shift, onClose }: { shift: Shift | null; onClose: () => void }) {
  const { state } = useApp();
  const client = useQueryClient();
  const feedback = useFeedback();
  // 입력 초안(서버 값 아님): 시트를 닫으면 버린다
  const [name, setName] = useState(shift?.name ?? "");
  const [timed, setTimed] = useState(Boolean(shift?.starts_at));
  const [start, setStart] = useState(shift?.starts_at?.slice(0, 5) ?? "09:00");
  const [end, setEnd] = useState(shift?.ends_at?.slice(0, 5) ?? "18:00");
  const [validation, setValidation] = useState("");
  const save = useMutation({
    mutationFn: (body: ShiftInput) => (shift ? checklistApi.updateShift(state.token!, shift.shift_id, body) : checklistApi.createShift(state.token!, body)),
    onSuccess: async () => {
      feedback.toast("저장했어요");
      await client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) });
      onClose();
    },
  });
  return (
    <Sheet
      open
      onClose={() => {
        if (!save.isPending) onClose();
      }}
      title={shift ? "근무조 고치기" : "근무조 추가"}
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (timed && start === end) {
            setValidation("시작과 끝을 다르게 골라 주세요.");
            return;
          }
          setValidation("");
          save.mutate({
            name: name.trim(),
            starts_at: timed ? start : null,
            ends_at: timed ? end : null,
            ...(shift && !timed ? { clear_time: true } : {}),
          });
        }}
      >
        <label className="flex flex-col gap-1">
          이름
          <input
            name="name"
            required
            maxLength={30}
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="min-h-12 rounded-xl bg-surface p-3 text-[16px]"
          />
        </label>
        <Switch label="시간 정하기" checked={timed} onChange={setTimed} />
        {timed && (
          <div className="flex flex-col gap-2">
            <p className="text-[14px] font-bold text-ink-muted">시작</p>
            <TimeWheel label="시작" value={start} onChange={setStart} />
            <p className="text-[14px] font-bold text-ink-muted">끝</p>
            <TimeWheel label="끝" value={end} onChange={setEnd} />
          </div>
        )}
        {/* 시간을 바꿔 같지 않게 되면 오류는 바로 사라진다 */}
        {validation && timed && start === end && (
          <p role="alert" className="text-danger-700">
            {validation}
          </p>
        )}
        {save.error && <ErrorInline message={apiErrorMessage(save.error, "저장하지 못했어요. 입력은 그대로 있어요.")} />}
        <Button type="submit" loading={save.isPending}>
          저장
        </Button>
      </form>
    </Sheet>
  );
}
function ShiftCards({ shift, onClose }: { shift: Shift; onClose: () => void }) {
  const { state } = useApp();
  const client = useQueryClient();
  const shifts = useQuery(checklistShiftsQuery(state.token, state.storeId));
  const cards = useInfiniteQuery(
    cardsInfiniteQuery(state.token, state.storeId, { status: "approved" }),
  );
  // 선택을 바꾼 카드만 입력 초안으로 보관한다. 다른 페이지·미승인 카드의 기존 연결을 지우지 않는다.
  const [edits, setEdits] = useState<Record<number, boolean>>({});
  const linked =
    shifts.data?.items.find((s) => s.shift_id === shift.shift_id)?.card_ids ??
    shift.card_ids;
  const selected = (id: number) => edits[id] ?? linked.includes(id);
  const save = useMutation({
    mutationFn: () => {
      const ids = new Set(linked);
      Object.entries(edits).forEach(([id, on]) => {
        if (on) ids.add(Number(id));
        else ids.delete(Number(id));
      });
      return checklistApi.shiftCards(state.token!, shift.shift_id, [...ids]);
    },
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: checklistKeys.root(state.storeId),
      });
      onClose();
    },
  });
  const items = cards.data?.pages.flatMap((p) => p.items) ?? [];
  const categories = [...new Set(items.map((c) => c.category?.name ?? "기타"))];
  return (
    <Sheet
      open
      onClose={() => {
        if (!save.isPending) onClose();
      }}
      title={`${shift.name} 할 일 담기`}
      description="공개된 카드만 고를 수 있어요. 마지막 근무조에서 빼면 공통으로 바뀌지 않고 오늘 할 일에서 빠져요."
    >
      {cards.isLoading && <Skeleton className="h-48" />}
      {cards.error && (
        <ErrorInline
          message={apiErrorMessage(cards.error, "카드를 불러오지 못했어요.")}
          onRetry={() => void cards.refetch()}
        />
      )}
      {cards.data && items.length === 0 && (
        <Caption>
          공개된 카드가 없어요. 카드 목록에서 먼저 공개해 주세요.
        </Caption>
      )}
      <div className="max-h-[45dvh] overflow-y-auto">
        {categories.map((category) => (
          <section key={category}>
            <h3 className="mt-3 font-bold">{category}</h3>
            <ul>
              {items
                .filter((c) => (c.category?.name ?? "기타") === category)
                .map((card) => (
                  <CheckRow
                    key={card.card_id}
                    label={card.title}
                    checked={selected(card.card_id)}
                    saving={save.isPending}
                    onToggle={() =>
                      setEdits((prev) => ({
                        ...prev,
                        [card.card_id]: !selected(card.card_id),
                      }))
                    }
                  />
                ))}
            </ul>
          </section>
        ))}
        {cards.hasNextPage && (
          <Button
            variant="secondary"
            loading={cards.isFetchingNextPage}
            onClick={() => void cards.fetchNextPage()}
          >
            카드 더 보기
          </Button>
        )}
      </div>
      {save.error && (
        <ErrorInline
          message={apiErrorMessage(
            save.error,
            "저장하지 못했어요. 선택은 그대로 있어요.",
          )}
        />
      )}
      <Button
        loading={save.isPending}
        disabled={!cards.data || Boolean(cards.error)}
        onClick={() => save.mutate()}
      >
        저장
      </Button>
    </Sheet>
  );
}
