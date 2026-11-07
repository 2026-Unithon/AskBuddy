"use client";

import {
  useInfiniteQuery,
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AskBar,
  Button,
  ButtonLink,
  Caption,
  CheckRow,
  ConfirmDialog,
  Empty,
  Icon,
  NumberedContent,
  ErrorInline,
  HeroCard,
  HeroClock,
  HeroProgress,
  ListGroup,
  PageHeader,
  RefreshingHint,
  Screen,
  HeaderActions,
  Sheet,
  Skeleton,
  STAFF_TABS,
  TabBar,
} from "@/components/kit";
import { TodayOnlyTasks } from "@/components/checklist/today-only-tasks";
import { SuggestedQuestions } from "@/components/staff/suggested-questions";
import { ApiError, apiErrorMessage } from "@/lib/api";
import {
  checklistApi,
  type CheckItem,
  type CheckRequest,
  type ChecklistGroup,
  type ChecklistToday,
} from "@/lib/checklist-api";
import {
  bootstrapQuery,
  checklistKeys,
  checklistTodayQuery,
  learnItemQuery,
  myTodayTasksQuery,
  rNotificationsQuery,
} from "@/lib/query";
import { useApp } from "@/lib/store";

function lineKey(item: CheckItem) {
  return `${item.card_version_id}:${item.line_no}`;
}
// 한 줄만 되돌린다. 다른 줄에서 동시에 저장한 변경은 보존한다.
function patchLine(
  data: ChecklistToday | undefined,
  item: CheckRequest,
): ChecklistToday | undefined {
  if (!data || data.business_date !== item.business_date) return data;
  const line = data.groups
    .flatMap((g) => g.cards)
    .find((c) => c.card_version_id === item.card_version_id)
    ?.lines.find((l) => l.line_no === item.line_no);
  if (!line || line.checked === item.checked) return data;
  const delta = item.checked ? 1 : -1;
  return {
    ...data,
    view: { ...data.view, done: data.view.done + delta },
    scope_counts: {
      ...data.scope_counts,
      done: data.scope_counts.done + delta,
    },
    groups: data.groups.map((g) => ({
      ...g,
      cards: g.cards.map((c) =>
        c.card_version_id !== item.card_version_id
          ? c
          : {
              ...c,
              lines: c.lines.map((l) =>
                l.line_no === item.line_no
                  ? { ...l, checked: item.checked }
                  : l,
              ),
            },
      ),
    })),
  };
}

export function TodayScreen() {
  const { state } = useApp();
  const router = useRouter();
  const client = useQueryClient();
  const [shift, setShift] = useState<number | null>(null);
  const [displayDate, setDisplayDate] = useState<string | null>(null);
  const [yesterday, setYesterday] = useState<string | null>(null);
  const [failedCheck, setFailedCheck] = useState<CheckRequest | null>(null);
  const [dayChanged, setDayChanged] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [question, setQuestion] = useState("");
  // 줄 이름을 누르면 여는 레시피 시트(s01d)
  const [preview, setPreview] = useState<{ itemId: number; title: string } | null>(null);
  // 버디에 아직 안 본 새 답이 있으면 입력창에 점(NAV-8)
  const notices = useInfiniteQuery(rNotificationsQuery(state.token, state.storeId, state.userId));
  const newAnswer = Boolean(notices.data?.pages[0]?.notifications.some((n) => !n.read));
  const ask = (text: string) => router.push(`/staff/ask?q=${encodeURIComponent(text.trim())}`);
  const saving =
    useIsMutating({
      mutationKey: [...checklistKeys.root(state.storeId), "check"],
    }) > 0;
  const today = useQuery(
    checklistTodayQuery(
      state.token,
      state.storeId,
      state.userId,
      shift,
      null,
      saving || yesterday ? false : 15_000,
    ),
  );
  const bootstrap = useQuery(
    bootstrapQuery(state.token, state.userId, state.storeId),
  );
  // 같은 캐시를 TodayOnlyTasks 와 나눠 쓴다. 사장 지시가 있으면 '할 일 없음' 안내를 띄우지 않는다
  const todayOnly = useQuery(myTodayTasksQuery(state.token, state.storeId, state.userId));
  const hasTodayOnly = (todayOnly.data?.items.length ?? 0) > 0;
  const data = today.data;
  // 날짜만 화면 상태로 보관한다. 서버 응답과 체크 상태는 Query 캐시가 정본이다.
  if (data && displayDate !== data.business_date) {
    if (displayDate) setConfirm(false);
    if (
      displayDate &&
      !data.previous_submitted &&
      displayDate === data.previous_business_date
    )
      setYesterday(displayDate);
    else if (displayDate) setDayChanged(true);
    setDisplayDate(data.business_date);
  }
  const refresh = () =>
    client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) });
  const dateError = (error: unknown, attempted?: CheckRequest) => {
    if (error instanceof ApiError && error.code === "BUSINESS_DATE_CHANGED") {
      setConfirm(false);
      if (error.details.previous_unsubmitted === true && displayDate) {
        setYesterday(displayDate);
        if (attempted) setFailedCheck(attempted);
      } else setDayChanged(true);
      void refresh();
    }
  };
  const submit = useMutation({
    mutationFn: (date: string) => checklistApi.submit(state.token!, date),
    onSuccess: async () => {
      setConfirm(false);
      await refresh();
    },
    onError: (error) => dateError(error),
  });
  const remaining = data ? data.scope_counts.total - data.scope_counts.done : 0;
  const current = data?.shifts.find(
    (s) => s.shift_id === data.current_shift_id,
  );
  return (
    <Screen
      tabBar={<TabBar tabs={STAFF_TABS} />}
      footer={
        <div className="flex flex-col gap-2">
          <SuggestedQuestions onPick={ask} />
          <AskBar value={question} onChange={setQuestion} onSubmit={() => ask(question)} newAnswer={newAnswer} />
        </div>
      }
    >
      <PageHeader
        eyebrow={bootstrap.data?.store?.store_name}
        title="오늘 할 일"
        action={<HeaderActions role="STAFF" />}
      />
      {dayChanged && <p role="status">하루가 바뀌었어요</p>}
      <TodayOnlyTasks />
      {today.isLoading && (
        <>
          <Skeleton className="h-40" />
          <Skeleton className="h-64" />
        </>
      )}
      {today.error && (
        <ErrorInline
          message={apiErrorMessage(
            today.error,
            "오늘 할 일을 불러오지 못했어요.",
          )}
          onRetry={() => void today.refetch()}
          retrying={today.isRefetching}
        />
      )}
      {data && (
        <>
          {data.my_submission ? (
            <HeroCard>
              {/* 끝의 기억을 좋게(피크엔드, s01e): 체크가 통통 튄다 */}
              <span
                data-celebrate=""
                aria-hidden
                className="mb-3 flex size-12 items-center justify-center rounded-full bg-primary text-white animate-[check-pop_400ms_var(--ease-spring)]"
              >
                <Icon name="check" size={26} />
              </span>
              <p
                className="pr-16 text-[22px] font-bold"
                data-testid="checklist-complete"
              >
                오늘 할 일 끝났어요
              </p>
              <p className="mt-3">
                체크 {data.my_submission.done_lines}/
                {data.my_submission.total_lines}개 제출했어요
              </p>
              <ButtonLink href="/staff/me" variant="secondary" className="mt-4">
                내 기록 보기
              </ButtonLink>
            </HeroCard>
          ) : data.scope_counts.total > 0 ? (
            <HeroCard>
              {current && (
                <HeroClock pill>
                  {data.upcoming ? "다음" : "지금"} {current.name}
                </HeroClock>
              )}
              <p className="my-3 pr-14 text-[22px] font-bold">
                {remaining}개 남았어요
              </p>
              <HeroProgress {...data.scope_counts} label="내 범위 진행" />
              <p className="mt-2 text-sm">
                {data.scope_counts.done}/{data.scope_counts.total}개
              </p>
            </HeroCard>
          ) : hasTodayOnly ? null : (
            <Empty
              title="아직 오늘 할 일이 없어요"
              description="사장님이 정해 주면 여기에 생겨요"
            />
          )}
          {/* s01c: 직원은 자기 근무조만 본다(근무조 칩 없음) */}
          <Groups
            groups={
              data.shifts.length
                ? data.groups
                : data.groups.map((group) => ({ ...group, name: "전체" }))
            }
            renderLine={(item, text, itemId) => (
              <LiveLine
                key={lineKey(item)}
                item={{ ...item, business_date: data.business_date }}
                text={text}
                onOpen={itemId ? () => setPreview({ itemId, title: text }) : undefined}
                disabled={submit.isPending || Boolean(yesterday)}
                onDateError={dateError}
              />
            )}
          />
          {data.scope_counts.total > 0 && data.view.total === 0 && (
            <Caption>
              이 근무조에는 담긴 할 일이 없어요. 다른 근무조를 선택해 주세요.
            </Caption>
          )}
          {!data.my_submission && data.scope_counts.total > 0 && (
            <Button
              data-testid="checklist-submit"
              loading={submit.isPending}
              disabled={saving || Boolean(yesterday)}
              onClick={() =>
                remaining > 0
                  ? setConfirm(true)
                  : submit.mutate(data.business_date)
              }
            >
              다 했어요
            </Button>
          )}
          {submit.error && (
            <ErrorInline
              message={apiErrorMessage(submit.error, "제출하지 못했어요.")}
              onRetry={() =>
                submit.variables && submit.mutate(submit.variables)
              }
              retrying={submit.isPending}
            />
          )}
        </>
      )}
      <RefreshingHint active={today.isRefetching && !today.isLoading} />
      <ConfirmDialog
        open={confirm}
        title={`${remaining}개가 남았어요. 그래도 끝낼까요?`}
        confirmLabel="그래도 끝내기"
        cancelLabel="더 체크하기"
        loading={submit.isPending}
        error={submit.error ? apiErrorMessage(submit.error, "제출하지 못했어요.") : null}
        onConfirm={() => data && submit.mutate(data.business_date)}
        onCancel={() => setConfirm(false)}
      />
      <RecipeSheet preview={preview} onClose={() => setPreview(null)} />
      {yesterday && (
        <YesterdaySheet
          date={yesterday}
          attempted={failedCheck}
          onSaved={() => {
            setYesterday(null);
            setFailedCheck(null);
            setShift(null);
            setDayChanged(true);
          }}
        />
      )}
    </Screen>
  );
}

function Groups({
  groups,
  renderLine,
}: {
  groups: ChecklistGroup[];
  renderLine: (
    item: CheckItem,
    text: string,
    itemId?: number | null,
  ) => React.ReactNode;
}) {
  return (
    <>
      {groups.map((group) => (
        <ListGroup key={group.shift_id ?? "common"} label={group.name}>
          {group.cards.map((card) => {
            // 항목 = 카드 하나. 줄은 늘 하나(line_no 1)이고 제목이 곧 항목 이름이다.
            const line = card.lines[0];
            if (!line) return null;
            return renderLine(
              {
                card_version_id: card.card_version_id,
                line_no: line.line_no,
                checked: line.checked,
              },
              card.title,
              card.item_id,
            );
          })}
        </ListGroup>
      ))}
    </>
  );
}
function LiveLine({
  item,
  text,
  onOpen,
  disabled,
  onDateError,
}: {
  item: CheckRequest;
  text: string;
  onOpen?: () => void;
  disabled: boolean;
  onDateError: (error: unknown, item: CheckRequest) => void;
}) {
  const { state } = useApp();
  const client = useQueryClient();
  const root = checklistKeys.todayRoot(state.storeId, state.userId);
  const inFlight = useRef(false);
  const change = useMutation({
    mutationKey: [...checklistKeys.root(state.storeId), "check"],
    mutationFn: (next: CheckRequest) => checklistApi.check(state.token!, next),
    onMutate: async (next) => {
      await client.cancelQueries({ queryKey: root });
      client.setQueriesData<ChecklistToday>({ queryKey: root }, (data) =>
        patchLine(data, next),
      );
      return { previous: item.checked };
    },
    onError: (error, next, context) => {
      client.setQueriesData<ChecklistToday>({ queryKey: root }, (data) =>
        patchLine(data, {
          ...next,
          checked: context?.previous ?? !next.checked,
        }),
      );
      onDateError(error, next);
    },
    onSettled: async () => {
      try {
        if (
          client.isMutating({
            mutationKey: [...checklistKeys.root(state.storeId), "check"],
          }) === 1
        )
          await client.invalidateQueries({
            queryKey: checklistKeys.root(state.storeId),
          });
      } finally {
        inFlight.current = false;
      }
    },
  });
  return (
    <CheckRow
      label={text}
      onOpen={onOpen}
      checked={item.checked}
      saving={change.isPending || disabled}
      error={
        change.error
          ? "이 변경은 저장되지 않았어요. 다시 눌러 주세요."
          : undefined
      }
      onToggle={() => {
        if (inFlight.current || disabled) return;
        inFlight.current = true;
        change.mutate({ ...item, checked: !item.checked });
      }}
    />
  );
}

function YesterdaySheet({
  date,
  attempted,
  onSaved,
}: {
  date: string;
  attempted: CheckRequest | null;
  onSaved: () => void;
}) {
  const { state } = useApp();
  const client = useQueryClient();
  const yesterday = useQuery(
    checklistTodayQuery(
      state.token,
      state.storeId,
      state.userId,
      null,
      date,
      false,
    ),
  );
  // 서버 데이터의 복사 대신 사용자가 바꾼 줄만 입력 초안으로 보관한다.
  const [edits, setEdits] = useState<Record<string, boolean>>(() =>
    attempted ? { [lineKey(attempted)]: attempted.checked } : {},
  );
  const save = useMutation({
    mutationFn: () => {
      const checks = new Map<string, CheckItem>();
      for (const group of yesterday.data?.groups ?? [])
        for (const card of group.cards)
          for (const line of card.lines) {
            const item = {
              card_version_id: card.card_version_id,
              line_no: line.line_no,
              checked: line.checked,
            };
            checks.set(lineKey(item), {
              ...item,
              checked: edits[lineKey(item)] ?? line.checked,
            });
          }
      return checklistApi.submit(state.token!, date, [...checks.values()]);
    },
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: checklistKeys.root(state.storeId),
      });
      onSaved();
    },
  });
  return (
    <Sheet
      open
      onClose={() => {}}
      dismissible={false}
      title="어제 체크리스트"
      description={`${date}. 체크를 고친 뒤 저장해 주세요. 저장하면 어제 기록을 제출해요.`}
    >
      {yesterday.isLoading && <Skeleton className="h-64" />}
      {yesterday.error && (
        <ErrorInline
          message={apiErrorMessage(
            yesterday.error,
            "어제 할 일을 불러오지 못했어요.",
          )}
          onRetry={() => void yesterday.refetch()}
        />
      )}
      <div className="max-h-[50dvh] overflow-y-auto">
        <Groups
          groups={yesterday.data?.groups ?? []}
          renderLine={(item, text) => (
            <CheckRow
              key={lineKey(item)}
              label={text}
              checked={edits[lineKey(item)] ?? item.checked}
              saving={save.isPending}
              onToggle={() =>
                setEdits((prev) => ({
                  ...prev,
                  [lineKey(item)]: !(prev[lineKey(item)] ?? item.checked),
                }))
              }
            />
          )}
        />
      </div>
      {save.error && (
        <ErrorInline
          message={apiErrorMessage(
            save.error,
            "저장하지 못했어요. 체크는 그대로 있어요.",
          )}
        />
      )}
      <Button
        data-testid="yesterday-save"
        loading={save.isPending}
        disabled={!yesterday.data || Boolean(yesterday.error)}
        onClick={() => save.mutate()}
      >
        저장
      </Button>
    </Sheet>
  );
}

/** 할 일 이름을 누르면 올라오는 레시피 미리 보기(s01d). 전체는 레시피 화면에서. */
function RecipeSheet({ preview, onClose }: { preview: { itemId: number; title: string } | null; onClose: () => void }) {
  const { state } = useApp();
  const item = useQuery(learnItemQuery(state.token, state.storeId, state.userId, preview?.itemId ?? 0));
  const missing = item.error instanceof ApiError && [403, 404].includes(item.error.status);
  return (
    <Sheet open={preview !== null} onClose={onClose} title={preview?.title ?? ""}>
      {item.isLoading && <Skeleton className="h-32" />}
      {missing && <p className="text-[15px] text-ink-muted">이 레시피를 볼 수 없어요</p>}
      {item.error && !missing && (
        <ErrorInline message={apiErrorMessage(item.error, "레시피를 불러오지 못했어요.")} onRetry={() => void item.refetch()} />
      )}
      {item.data && (
        <div className="max-h-[50dvh] overflow-y-auto rounded-[16px] bg-surface px-4 py-3">
          <NumberedContent content={item.data.content} />
        </div>
      )}
      {preview && !missing && (
        <ButtonLink href={`/staff/recipes/${preview.itemId}`} variant="secondary">
          레시피 전체 보기
        </ButtonLink>
      )}
    </Sheet>
  );
}
