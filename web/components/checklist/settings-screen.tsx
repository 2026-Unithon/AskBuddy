"use client";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";
import {
  BackButton,
  Button,
  ButtonLink,
  Caption,
  CheckRow,
  Empty,
  ErrorInline,
  PageHeader,
  Screen,
  Sheet,
  Skeleton,
  Surface,
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
  const shifts = useQuery(checklistShiftsQuery(state.token, state.storeId));
  const settings = useQuery(checklistSettingsQuery(state.token, state.storeId));
  const [edit, setEdit] = useState<number | "new" | null>(null);
  const [remove, setRemove] = useState<number | null>(null);
  const [cards, setCards] = useState<number | null>(null);
  const editedShift = shifts.data?.items.find((s) => s.shift_id === edit);
  const cardsShift = shifts.data?.items.find((s) => s.shift_id === cards);
  const removedShift = shifts.data?.items.find((s) => s.shift_id === remove);
  const refresh = () =>
    client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) });
  const preset = useMutation({
    mutationFn: () => checklistApi.preset(state.token!),
    onSuccess: refresh,
  });
  const order = useMutation({
    mutationFn: (ids: number[]) => checklistApi.order(state.token!, ids),
    onSuccess: refresh,
  });
  const deletion = useMutation({
    mutationFn: (id: number) => checklistApi.deleteShift(state.token!, id),
    onSuccess: async () => {
      setRemove(null);
      await refresh();
    },
  });
  const setting = useMutation({
    mutationFn: (body: {
      business_day_starts_at?: string;
      staff_records_visible?: boolean;
    }) => checklistApi.setSettings(state.token!, body),
    onSuccess: refresh,
  });
  const move = (index: number, by: number) => {
    const ids = shifts.data!.items.map((s) => s.shift_id);
    [ids[index], ids[index + by]] = [ids[index + by], ids[index]];
    order.mutate(ids);
  };
  return (
    <Screen>
      <BackButton href="/owner/settings" />
      <PageHeader
        title="근무조 설정"
        description="매장에 맞게 이름과 시간을 정하고, 할 일을 담아요"
      />
      {shifts.isLoading && <Skeleton className="h-64" />}
      {shifts.error && (
        <ErrorInline
          message={apiErrorMessage(shifts.error, "근무조를 불러오지 못했어요.")}
          onRetry={() => void shifts.refetch()}
        />
      )}
      {shifts.data?.items.length === 0 && (
        <>
          <Empty
            title="아직 근무조가 없어요"
            description="나누지 않으면 전체 할 일을 함께 봐요. 카드 상세에서 공통 할 일을 담을 수 있어요."
          />
          <Button loading={preset.isPending} onClick={() => preset.mutate()}>
            오픈·미들·마감으로 시작하기
          </Button>
        </>
      )}
      {shifts.data?.items.map((shift, index, list) => (
        <Surface key={shift.shift_id} className="p-4">
          <h2 className="text-[20px] font-bold">{shift.name}</h2>
          <Caption>
            {shift.starts_at
              ? `${shift.starts_at} ~ ${shift.ends_at}${shift.ends_at! <= shift.starts_at ? " · 다음 날 끝" : ""}`
              : "시간을 정하지 않았어요"}
          </Caption>
          <div className="mt-3 flex gap-2">
            <Button variant="secondary" onClick={() => setEdit(shift.shift_id)}>
              고치기
            </Button>
            <Button
              variant="secondary"
              onClick={() => setCards(shift.shift_id)}
            >
              할 일 담기
            </Button>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              className="w-auto! px-3"
              variant="secondary"
              aria-label={`${shift.name} 위로`}
              disabled={index === 0 || order.isPending}
              onClick={() => move(index, -1)}
            >
              ↑
            </Button>
            <Button
              className="w-auto! px-3"
              variant="secondary"
              aria-label={`${shift.name} 아래로`}
              disabled={index === list.length - 1 || order.isPending}
              onClick={() => move(index, 1)}
            >
              ↓
            </Button>
            <Button
              className="w-auto! px-3"
              variant="danger"
              onClick={() => {
                deletion.reset();
                setRemove(shift.shift_id);
              }}
            >
              지우기
            </Button>
          </div>
        </Surface>
      ))}
      {shifts.data && (
        <Button onClick={() => setEdit("new")}>근무조 추가</Button>
      )}
      {preset.error && (
        <ErrorInline
          message={apiErrorMessage(preset.error, "근무조를 만들지 못했어요.")}
          onRetry={() => preset.mutate()}
        />
      )}
      {order.error && (
        <ErrorInline
          message={apiErrorMessage(order.error, "순서를 저장하지 못했어요.")}
          onRetry={() => order.variables && order.mutate(order.variables)}
        />
      )}
      <ButtonLink href="/owner/members" variant="secondary">
        직원 담당 근무조
      </ButtonLink>
      <ButtonLink href="/owner/cards" variant="secondary">
        카드에서 공통 할 일 담기
      </ButtonLink>
      {settings.isLoading && <Skeleton className="h-40" />}
      {settings.error && (
        <ErrorInline
          message={apiErrorMessage(
            settings.error,
            "매장 설정을 불러오지 못했어요.",
          )}
          onRetry={() => void settings.refetch()}
        />
      )}
      {settings.data && (
        <Surface className="p-4">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const input = new FormData(event.currentTarget).get(
                "dayStart",
              ) as string;
              setting.mutate({ business_day_starts_at: input });
            }}
          >
            <label className="flex flex-col gap-2 text-[16px]">
              영업일 시작 시각
              <input
                key={settings.data.business_day_starts_at}
                name="dayStart"
                type="time"
                required
                defaultValue={settings.data.business_day_starts_at.slice(0, 5)}
                className="min-h-12 rounded-xl bg-background p-3"
              />
            </label>
            <Caption>
              매장 시간대 · {settings.data.timezone}. 이 시각에 오늘 할 일이
              새로 시작돼요.
            </Caption>
            <Button className="mt-3" type="submit" loading={setting.isPending}>
              시각 저장
            </Button>
          </form>
          <button
            role="switch"
            aria-checked={settings.data.staff_records_visible}
            disabled={setting.isPending}
            onClick={() =>
              setting.mutate({
                staff_records_visible: !settings.data.staff_records_visible,
              })
            }
            className="mt-5 flex min-h-11 w-full items-center justify-between text-[16px]"
          >
            <span>알바생 기록</span>
            <span className="font-bold text-primary">
              {settings.data.staff_records_visible ? "켜짐" : "꺼짐"}
            </span>
          </button>
          <Caption>
            점주가 알바생 달력을 볼지 정해요. 꺼도 기록은 저장되고 다시 켜면 볼
            수 있어요.
          </Caption>
        </Surface>
      )}
      {setting.error && (
        <ErrorInline
          message={apiErrorMessage(
            setting.error,
            "이 변경은 저장되지 않았어요.",
          )}
          onRetry={() => setting.variables && setting.mutate(setting.variables)}
          retrying={setting.isPending}
        />
      )}
      {(edit === "new" || editedShift) && (
        <ShiftEditor
          shift={editedShift ?? null}
          onClose={() => setEdit(null)}
        />
      )}
      {cardsShift && (
        <ShiftCards shift={cardsShift} onClose={() => setCards(null)} />
      )}
      <Sheet
        open={Boolean(remove)}
        onClose={() => {
          if (!deletion.isPending) setRemove(null);
        }}
        title={`${removedShift?.name ?? "근무조"}를 지울까요?`}
        description="과거 기록은 남아요. 이 근무조에만 담긴 카드는 오늘 할 일에서 빠져요."
      >
        {deletion.error && (
          <ErrorInline
            message={apiErrorMessage(deletion.error, "지우지 못했어요.")}
          />
        )}
        <Button
          variant="danger"
          loading={deletion.isPending}
          onClick={() => remove && deletion.mutate(remove)}
        >
          지우기
        </Button>
        <Button
          variant="secondary"
          disabled={deletion.isPending}
          onClick={() => setRemove(null)}
        >
          그대로 두기
        </Button>
      </Sheet>
    </Screen>
  );
}
function ShiftEditor({
  shift,
  onClose,
}: {
  shift: Shift | null;
  onClose: () => void;
}) {
  const { state } = useApp();
  const client = useQueryClient();
  const [validation, setValidation] = useState("");
  const save = useMutation({
    mutationFn: (body: ShiftInput) =>
      shift
        ? checklistApi.updateShift(state.token!, shift.shift_id, body)
        : checklistApi.createShift(state.token!, body),
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: checklistKeys.root(state.storeId),
      });
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
      description="시간은 정하지 않아도 돼요. 시작과 끝은 함께 적어 주세요."
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const name = (form.get("name") as string).trim(),
            start = form.get("start") as string,
            end = form.get("end") as string;
          if (Boolean(start) !== Boolean(end) || (start && start === end)) {
            setValidation("시작과 끝을 함께, 서로 다르게 적어 주세요.");
            return;
          }
          setValidation("");
          save.mutate({
            name,
            starts_at: start || null,
            ends_at: end || null,
            ...(shift && !start ? { clear_time: true } : {}),
          });
        }}
      >
        <label className="flex flex-col gap-1">
          이름
          <input
            name="name"
            required
            maxLength={30}
            defaultValue={shift?.name ?? ""}
            className="min-h-12 rounded-xl bg-surface p-3 text-[16px]"
          />
        </label>
        <div className="flex gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-1">
            시작
            <input
              name="start"
              type="time"
              defaultValue={shift?.starts_at ?? ""}
              className="min-h-12 min-w-0 rounded-xl bg-surface p-2"
            />
          </label>
          <label className="flex min-w-0 flex-1 flex-col gap-1">
            끝
            <input
              name="end"
              type="time"
              defaultValue={shift?.ends_at ?? ""}
              className="min-h-12 min-w-0 rounded-xl bg-surface p-2"
            />
          </label>
        </div>
        {validation && (
          <p role="alert" className="text-danger-700">
            {validation}
          </p>
        )}
        {save.error && (
          <ErrorInline
            message={apiErrorMessage(
              save.error,
              "저장하지 못했어요. 입력은 그대로 있어요.",
            )}
          />
        )}
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
      title={`${shift.name} · 할 일 담기`}
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
