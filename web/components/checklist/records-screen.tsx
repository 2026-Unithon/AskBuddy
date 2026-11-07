"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type PointerEvent } from "react";
import {
  BackButton,
  Button,
  ButtonLink,
  Caption,
  Empty,
  ErrorInline,
  Icon,
  PageHeader,
  RefreshingHint,
  Screen,
  Sheet,
  Skeleton,
  Surface,
  Switch,
} from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { checklistApi } from "@/lib/checklist-api";
import {
  checklistDayQuery,
  checklistKeys,
  checklistMeQuery,
  checklistMembersQuery,
  checklistRecordsQuery,
  checklistSettingsQuery,
} from "@/lib/query";
import { useApp } from "@/lib/store";

function monthToday() {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit" }).format(new Date());
}
function nextMonth(month: string, amount: number) {
  const [y, m] = month.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1 + amount, 1));
  return date.toISOString().slice(0, 7);
}
const SWIPE = 60;

/**
 * 기록 달력. 사장님은 '알바생 기록'(o13a): 알바생만 시트로 골라 본다(자기 기록은 보지 않는다).
 * 직원은 '내 기록': 자기 달력과 기록 남기기 스위치(o13c 는 사장님 화면만 스위치를 뺀다).
 */
export function RecordsScreen({ role }: { role: "OWNER" | "STAFF" }) {
  const { state } = useApp();
  const owner = role === "OWNER";
  const client = useQueryClient();
  const [month, setMonth] = useState(monthToday);
  const [picked, setPicked] = useState<number | null>(null);
  const [picking, setPicking] = useState(false);
  const [day, setDay] = useState<string | null>(null);
  const members = useQuery({ ...checklistMembersQuery(state.token, state.storeId), enabled: owner && Boolean(state.token && state.storeId) });
  const settings = useQuery({ ...checklistSettingsQuery(state.token, state.storeId), enabled: owner && Boolean(state.token && state.storeId) });
  const me = useQuery({ ...checklistMeQuery(state.token, state.storeId, state.userId), enabled: !owner && Boolean(state.token && state.storeId) });
  const staff = members.data?.items.filter((m) => m.role === "STAFF") ?? [];
  // 고른 사람이 없으면 첫 알바생. 사장님 자기 기록으로 대신 보여 주지 않는다
  const target = owner ? (staff.find((m) => m.user_id === picked) ?? staff[0] ?? null) : null;
  const hidden = owner && settings.data?.staff_records_visible === false;
  const canView = owner ? Boolean(target && settings.data?.staff_records_visible) : true;
  const viewUser = owner ? (target?.user_id ?? null) : null;
  const recordsQuery = checklistRecordsQuery(state.token, state.storeId, state.userId, viewUser, month);
  const records = useQuery({ ...recordsQuery, enabled: recordsQuery.enabled !== false && canView });
  const dayQuery = checklistDayQuery(state.token, state.storeId, state.userId, viewUser, day);
  const detail = useQuery({ ...dayQuery, enabled: dayQuery.enabled !== false && canView });
  const recording = useMutation({
    mutationFn: (enabled: boolean) => checklistApi.setMe(state.token!, enabled),
    onSuccess: () => client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) }),
  });
  const changeMonth = (amount: number) => {
    setMonth((m) => nextMonth(m, amount));
    setDay(null);
  };

  // 달력을 가로로 밀면 달을 바꾼다. 세로 스크롤은 그대로, 밀다 놓은 것은 날짜 누르기가 아니다
  const swipe = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const swiped = useRef(false);
  const onDown = (event: PointerEvent) => {
    // 터치로 민 뒤에는 click 이 오지 않아 표시가 남는다. 새로 누르기 시작하면 푼다
    swiped.current = false;
    swipe.current = { x: event.clientX, y: event.clientY, moved: false };
  };
  const onUp = (event: PointerEvent) => {
    const s = swipe.current;
    swipe.current = null;
    if (!s) return;
    const dx = event.clientX - s.x, dy = event.clientY - s.y;
    if (Math.abs(dx) > SWIPE && Math.abs(dx) > Math.abs(dy)) {
      swiped.current = true;
      changeMonth(dx < 0 ? 1 : -1);
    }
  };

  const [year, monthNo] = month.split("-").map(Number);
  const offset = new Date(Date.UTC(year, monthNo - 1, 1)).getUTCDay();
  const days = new Date(Date.UTC(year, monthNo, 0)).getUTCDate();
  const [, dayMonth, dayNo] = day?.split("-").map(Number) ?? [];

  return (
    <Screen>
      <BackButton parent={`/${role.toLowerCase()}/settings`} />
      <PageHeader title={owner ? "알바생 기록" : "내 기록"} />
      {owner && (
        <>
          {(settings.isLoading || members.isLoading) && <Skeleton className="h-12" />}
          {settings.error && <ErrorInline message={apiErrorMessage(settings.error, "기록 설정을 불러오지 못했어요.")} onRetry={() => void settings.refetch()} />}
          {members.error && <ErrorInline message={apiErrorMessage(members.error, "직원 목록을 불러오지 못했어요.")} onRetry={() => void members.refetch()} />}
          {hidden && (
            <>
              <Empty title="알바생 기록을 꺼 두었어요" />
              <ButtonLink href="/owner/shifts" variant="secondary">
                근무조에서 켜기
              </ButtonLink>
            </>
          )}
          {!hidden && settings.data && members.data && staff.length === 0 && <Empty title="아직 알바생이 없어요" />}
          {canView && target && (
            <button
              type="button"
              aria-label={`기록 볼 알바생, 지금 ${target.name}`}
              onClick={() => setPicking(true)}
              className="flex min-h-12 items-center gap-1 self-start rounded-full bg-surface px-4 text-[16px] font-bold text-ink shadow-card"
            >
              {target.name}
              <span aria-hidden className="text-ink-muted">▾</span>
            </button>
          )}
          <Sheet open={picking} onClose={() => setPicking(false)} title="누구 기록을 볼까요?">
            <ul className="flex flex-col">
              {staff.map((m) => (
                <li key={m.user_id}>
                  <button
                    type="button"
                    data-member-option=""
                    aria-pressed={m.user_id === target?.user_id}
                    onClick={() => {
                      setPicked(m.user_id);
                      setDay(null);
                      setPicking(false);
                    }}
                    className="flex min-h-12 w-full items-center justify-between text-left text-[16px] text-ink"
                  >
                    {m.name}
                    {m.user_id === target?.user_id && <Icon name="check" size={18} className="text-primary" />}
                  </button>
                </li>
              ))}
            </ul>
          </Sheet>
        </>
      )}
      {canView && (
        <>
          {records.data?.visible && !records.data.recording && (
            <p className="rounded-xl bg-empty p-3 text-[16px]">
              {owner ? "이 알바생은 기록을 남기지 않는 중이에요" : "기록을 남기지 않는 중이에요"}
            </p>
          )}
          <div className="flex items-center justify-between">
            <Button className="w-12! shrink-0 px-0" variant="secondary" aria-label="지난달" onClick={() => changeMonth(-1)}>
              ‹
            </Button>
            <h2 className="whitespace-nowrap text-xl font-bold">
              {year}년 {monthNo}월
            </h2>
            <Button className="w-12! shrink-0 px-0" variant="secondary" aria-label="다음 달" onClick={() => changeMonth(1)}>
              ›
            </Button>
          </div>
          {records.isLoading && <Skeleton className="h-80" />}
          {records.error && (
            <ErrorInline message={apiErrorMessage(records.error, "기록을 불러오지 못했어요.")} onRetry={() => void records.refetch()} retrying={records.isRefetching} />
          )}
          {records.data && !records.data.visible && <Empty title="알바생 기록을 꺼 두었어요" />}
          {records.data?.visible && (
            <div
              data-calendar=""
              onPointerDown={onDown}
              onPointerUp={onUp}
              onPointerCancel={() => {
                swipe.current = null;
              }}
              onClickCapture={(event) => {
                if (swiped.current) {
                  event.preventDefault();
                  event.stopPropagation();
                  swiped.current = false;
                }
              }}
              className="touch-pan-y select-none"
            >
              <Surface className="p-1">
                <div className="grid grid-cols-7 text-center">
                  {"일월화수목금토".split("").map((label) => (
                    <span key={label} className="py-2 text-sm text-ink-muted">
                      {label}
                    </span>
                  ))}
                  {Array.from({ length: offset }, (_, i) => (
                    <span key={`blank-${i}`} />
                  ))}
                  {Array.from({ length: days }, (_, i) => {
                    const date = `${month}-${String(i + 1).padStart(2, "0")}`;
                    const record = records.data.days.find((d) => d.date === date);
                    const label = record ? (record.percent !== null ? `${record.percent}%` : `체크 ${record.checked_lines}개`) : "";
                    return (
                      <button
                        key={date}
                        type="button"
                        aria-label={`${date}${label ? ` ${label}` : " 기록 없음"}`}
                        aria-pressed={day === date}
                        onClick={() => setDay(date)}
                        className={`flex min-h-[64px] min-w-0 flex-col items-center justify-center rounded-xl ${
                          day === date ? "bg-primary text-white" : record ? "bg-empty text-primary" : "text-ink"
                        }`}
                      >
                        <span className="text-[16px]">{i + 1}</span>
                        <span className="text-[10px] leading-tight">{label || " "}</span>
                      </button>
                    );
                  })}
                </div>
              </Surface>
            </div>
          )}
          {records.data?.visible && records.data.days.length === 0 && <Caption>이번 달에 남긴 기록이 없어요</Caption>}
          <RefreshingHint active={records.isRefetching && !records.isLoading} />
          <Sheet open={day !== null} onClose={() => setDay(null)} title={day ? `${dayMonth}월 ${dayNo}일` : ""}>
            {detail.isLoading && <Skeleton className="h-32" />}
            {detail.error && <ErrorInline message={apiErrorMessage(detail.error, "그날 기록을 불러오지 못했어요.")} onRetry={() => void detail.refetch()} />}
            {detail.data?.visible && (
              <div className="flex flex-col gap-3">
                <p className="text-[16px]">
                  {detail.data.submission
                    ? `제출했어요 ${detail.data.submission.done_lines}/${detail.data.submission.total_lines}개${detail.data.submission.late ? ", 다음 날 저장" : ""}`
                    : "제출하지 않았어요"}
                </p>
                {detail.data.lines.length ? (
                  <ul className="flex flex-col gap-3">
                    {detail.data.lines.map((line, i) => (
                      <li key={`${line.checked_at}-${i}`}>
                        <p className="text-[16px]">✓ {line.text}</p>
                        {line.title !== line.text && <Caption>{line.title}</Caption>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Caption>체크한 일이 없어요</Caption>
                )}
              </div>
            )}
          </Sheet>
        </>
      )}
      {!owner && (
        <>
          {me.isLoading && <Skeleton className="h-14" />}
          {me.error && <ErrorInline message={apiErrorMessage(me.error, "내 기록 설정을 불러오지 못했어요.")} onRetry={() => void me.refetch()} />}
          {me.data && (
            <Surface className="px-[18px] py-1">
              <Switch
                label="내 기록 남기기"
                checked={me.data.personal_records_enabled}
                disabled={recording.isPending}
                onChange={(next) => recording.mutate(next)}
              />
            </Surface>
          )}
          {recording.error && (
            <ErrorInline
              message={apiErrorMessage(recording.error, "이 변경은 저장되지 않았어요.")}
              onRetry={() => recording.variables !== undefined && recording.mutate(recording.variables)}
              retrying={recording.isPending}
            />
          )}
        </>
      )}
    </Screen>
  );
}
