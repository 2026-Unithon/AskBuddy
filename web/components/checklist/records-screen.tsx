"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  BackButton,
  Button,
  Caption,
  Empty,
  ErrorInline,
  PageHeader,
  RefreshingHint,
  Screen,
  Skeleton,
  Surface,
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
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
  }).format(new Date());
}
function nextMonth(month: string, amount: number) {
  const [y, m] = month.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1 + amount, 1));
  return date.toISOString().slice(0, 7);
}
export function RecordsScreen({ role }: { role: "OWNER" | "STAFF" }) {
  const { state } = useApp();
  const client = useQueryClient();
  const [month, setMonth] = useState(monthToday);
  const [user, setUser] = useState<number | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const members = useQuery({
    ...checklistMembersQuery(state.token, state.storeId),
    enabled: role === "OWNER" && Boolean(state.token && state.storeId),
  });
  const settings = useQuery({
    ...checklistSettingsQuery(state.token, state.storeId),
    enabled: role === "OWNER" && Boolean(state.token && state.storeId),
  });
  const me = useQuery(
    checklistMeQuery(state.token, state.storeId, state.userId),
  );
  const viewUser =
    role === "OWNER" && settings.data?.staff_records_visible ? user : null;
  const records = useQuery(
    checklistRecordsQuery(
      state.token,
      state.storeId,
      state.userId,
      viewUser,
      month,
    ),
  );
  const detail = useQuery(
    checklistDayQuery(state.token, state.storeId, state.userId, viewUser, day),
  );
  const recording = useMutation({
    mutationFn: (enabled: boolean) => checklistApi.setMe(state.token!, enabled),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: checklistKeys.root(state.storeId) }),
  });
  const [year, monthNo] = month.split("-").map(Number);
  const offset = new Date(Date.UTC(year, monthNo - 1, 1)).getUTCDay();
  const days = new Date(Date.UTC(year, monthNo, 0)).getUTCDate();
  return (
    <Screen>
      <BackButton href={`/${role.toLowerCase()}/settings`} />
      <PageHeader
        title="내 기록"
        description="내가 체크한 일과 제출 기록을 볼 수 있어요"
      />
      {role === "OWNER" && (
        <>
          {settings.isLoading && <Skeleton className="h-12" />}
          {settings.error && (
            <ErrorInline
              message={apiErrorMessage(
                settings.error,
                "기록 설정을 불러오지 못했어요.",
              )}
              onRetry={() => void settings.refetch()}
            />
          )}
          {members.error && (
            <ErrorInline
              message={apiErrorMessage(
                members.error,
                "직원 목록을 불러오지 못했어요.",
              )}
              onRetry={() => void members.refetch()}
            />
          )}
          {members.isLoading && <Skeleton className="h-12" />}
          {settings.data?.staff_records_visible && members.data && (
            <label className="flex flex-col gap-2 text-[16px]">
              누구의 기록을 볼까요?
              <select
                aria-label="기록 구성원"
                value={user ?? ""}
                onChange={(event) => {
                  setUser(
                    event.target.value ? Number(event.target.value) : null,
                  );
                  setDay(null);
                }}
                className="min-h-12 rounded-xl bg-surface px-3"
              >
                <option value="">나</option>
                {members.data.items
                  .filter((m) => m.role === "STAFF")
                  .map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.name}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {settings.data && !settings.data.staff_records_visible && (
            <Caption>
              알바생 기록을 꺼 두었어요 ·{" "}
              <a href="/owner/shifts" className="text-primary underline">
                설정에서 켜기
              </a>
            </Caption>
          )}
        </>
      )}
      {records.data?.visible && !records.data.recording && (
        <p className="rounded-xl bg-empty p-3 text-[16px]">
          {viewUser
            ? "이 구성원은 기록을 남기지 않는 중이에요"
            : "기록을 남기지 않는 중이에요. 이 기간은 달력에 남지 않아요"}
        </p>
      )}
      <div className="flex items-center justify-between">
        <Button
          className="w-12! shrink-0 px-0"
          variant="secondary"
          aria-label="지난달"
          onClick={() => {
            setMonth(nextMonth(month, -1));
            setDay(null);
          }}
        >
          ‹
        </Button>
        <h2 className="whitespace-nowrap text-xl font-bold">
          {year}년 {monthNo}월
        </h2>
        <Button
          className="w-12! shrink-0 px-0"
          variant="secondary"
          aria-label="다음 달"
          onClick={() => {
            setMonth(nextMonth(month, 1));
            setDay(null);
          }}
        >
          ›
        </Button>
      </div>
      {records.isLoading && <Skeleton className="h-80" />}
      {records.error && (
        <ErrorInline
          message={apiErrorMessage(records.error, "기록을 불러오지 못했어요.")}
          onRetry={() => void records.refetch()}
          retrying={records.isRefetching}
        />
      )}
      {records.data && !records.data.visible && (
        <Empty
          title="알바생 기록을 꺼 두었어요"
          description="근무조 설정에서 알바생 기록을 켜면 다시 볼 수 있어요"
        />
      )}
      {records.data?.visible && (
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
              const label = record
                ? record.percent !== null
                  ? `${record.percent}%`
                  : `체크 ${record.checked_lines}개`
                : "";
              return (
                <button
                  key={date}
                  aria-label={`${date}${label ? ` ${label}` : " 기록 없음"}`}
                  aria-pressed={day === date}
                  onClick={() => setDay(date)}
                  className={`flex min-h-[64px] min-w-0 flex-col items-center justify-center rounded-xl ${day === date ? "bg-primary text-white" : record ? "bg-empty text-primary" : "text-ink"}`}
                >
                  <span className="text-[16px]">{i + 1}</span>
                  <span className="text-[10px] leading-tight">
                    {label || " "}
                  </span>
                </button>
              );
            })}
          </div>
        </Surface>
      )}
      {records.data?.visible && records.data.days.length === 0 && (
        <Caption>이번 달에 남긴 기록이 없어요</Caption>
      )}
      {detail.isLoading && <Skeleton className="h-32" />}
      {detail.error && (
        <ErrorInline
          message={apiErrorMessage(
            detail.error,
            "그날 기록을 불러오지 못했어요.",
          )}
          onRetry={() => void detail.refetch()}
        />
      )}
      {detail.data?.visible && (
        <Surface className="p-4">
          <h2 className="text-[16px] font-bold">{day} · 한 일</h2>
          <p className="my-2">
            {detail.data.submission
              ? `제출했어요 · ${detail.data.submission.done_lines}/${detail.data.submission.total_lines}개${detail.data.submission.late ? " · 다음 날 저장" : ""}`
              : "제출하지 않았어요"}
          </p>
          {detail.data.lines.length ? (
            <ul className="flex flex-col gap-3">
              {detail.data.lines.map((line, i) => (
                <li key={`${line.checked_at}-${i}`}>
                  <p className="text-[16px]">✓ {line.text}</p>
                  <Caption>{line.title}</Caption>
                </li>
              ))}
            </ul>
          ) : (
            <Caption>내가 체크한 일이 없어요</Caption>
          )}
        </Surface>
      )}
      <RefreshingHint active={records.isRefetching && !records.isLoading} />
      {me.isLoading && <Skeleton className="h-14" />}
      {me.error && (
        <ErrorInline
          message={apiErrorMessage(
            me.error,
            "내 기록 설정을 불러오지 못했어요.",
          )}
          onRetry={() => void me.refetch()}
        />
      )}
      {me.data && (
        <Surface className="p-4">
          <button
            role="switch"
            aria-checked={me.data.personal_records_enabled}
            disabled={recording.isPending}
            onClick={() => recording.mutate(!me.data.personal_records_enabled)}
            className="flex min-h-11 w-full items-center justify-between text-[16px]"
          >
            <span>내 기록 남기기</span>
            <span className="font-bold text-primary">
              {me.data.personal_records_enabled ? "켜짐" : "꺼짐"}
            </span>
          </button>
          <Caption>
            꺼도 매장 체크 상태는 바뀌어요. 꺼 둔 기간의 개인 기록은 남지
            않아요.
          </Caption>
        </Surface>
      )}
      {recording.error && (
        <ErrorInline
          message={apiErrorMessage(
            recording.error,
            "이 변경은 저장되지 않았어요.",
          )}
          onRetry={() =>
            recording.variables !== undefined &&
            recording.mutate(recording.variables)
          }
          retrying={recording.isPending}
        />
      )}
    </Screen>
  );
}
