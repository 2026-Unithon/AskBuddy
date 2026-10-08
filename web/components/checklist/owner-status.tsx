"use client";
import { useQuery } from "@tanstack/react-query";
import {
  ButtonLink,
  Caption,
  ErrorInline,
  HeroCard,
  HeroClock,
  HeroProgress,
  RefreshingHint,
  Skeleton,
} from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { checklistStatusQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

export function OwnerChecklistStatus() {
  const { state } = useApp();
  const status = useQuery(checklistStatusQuery(state.token, state.storeId));
  const data = status.data;
  const current = data?.shifts.find(
    (s) => s.shift_id === data.current_shift_id,
  );
  const last = data?.last_submission;
  return (
    <>
      {status.isLoading && <Skeleton className="h-44" />}
      {status.error && (
        <ErrorInline
          message={apiErrorMessage(
            status.error,
            "매장 진행을 불러오지 못했어요.",
          )}
          onRetry={() => void status.refetch()}
          retrying={status.isRefetching}
        />
      )}
      {data &&
        (data.scope_counts.total ? (
          <HeroCard>
            <HeroClock>
              {current ? `지금 · ${current.name}` : "오늘 매장 진행"}
            </HeroClock>
            <p className="my-4 pr-14 text-[24px] font-bold">
              체크 {data.scope_counts.done}/{data.scope_counts.total}개
            </p>
            <HeroProgress {...data.scope_counts} label="매장 체크리스트 진행" />
            <ul className="mt-4 flex flex-col gap-2">
              {data.shifts.map((s) => (
                <li key={s.shift_id} className="flex justify-between">
                  <span>{s.name}</span>
                  <span>
                    {s.done}/{s.total}
                    {s.submitted ? " ✓" : ""}
                  </span>
                </li>
              ))}
            </ul>
            {last && (
              <p className="mt-4 text-sm" data-testid="last-submission">
                {last.shift_names.join(" · ") || "오늘 할 일"} 끝났어요 ·
                체크리스트 {last.total_lines}개 ·{" "}
                {last.business_date === data.business_date ? "오늘" : "어제"}{" "}
                {new Date(last.submitted_at).toLocaleTimeString("ko-KR", {
                  timeZone: "Asia/Seoul",
                  hour: "2-digit",
                  minute: "2-digit",
                  hour12: false,
                })}
                에 끝
              </p>
            )}
          </HeroCard>
        ) : (
          <Caption>
            오늘 할 일이 아직 없어요 ·{" "}
            <a href="/owner/shifts" className="text-primary underline">
              근무조에서 할 일 담기
            </a>
          </Caption>
        ))}
      <RefreshingHint active={status.isRefetching && !status.isLoading} />
      <ButtonLink href="/owner/me" variant="secondary">
        내 기록 · 알바생 기록 보기
      </ButtonLink>
    </>
  );
}
