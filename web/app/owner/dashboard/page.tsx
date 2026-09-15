"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Buddy } from "@/components/ui";
import { pendingQuery, proposalsQuery, staffQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

function relativeTime(value: string) {
  const minutes = Math.max(1, Math.floor((Date.now() - new Date(value).getTime()) / 60_000));
  return minutes < 60 ? `${minutes}분 전` : `${Math.floor(minutes / 60)}시간 전`;
}

function progressTone(progress: number) {
  if (progress >= 80) return { text: "text-brand-500", bar: "bg-brand-500" };
  if (progress >= 50) return { text: "text-[#e5b94a]", bar: "bg-[#e5b94a]" };
  return { text: "text-[#e57373]", bar: "bg-[#e57373]" };
}

export default function DashboardPage() {
  const { state } = useApp();
  const staff = useQuery(staffQuery(state.token, state.storeId));
  const pending = useQuery(pendingQuery(state.token, state.storeId));
  const proposals = useQuery(proposalsQuery(state.token, state.storeId));
  const staffItems = staff.data?.items ?? [];
  const pendingItems = pending.data?.items ?? [];
  const proposalItems = proposals.data?.items ?? [];
  const firstError = staff.error ?? pending.error ?? proposals.error;
  const isRefreshing = (staff.isFetching || pending.isFetching || proposals.isFetching)
    && !staff.isLoading && !pending.isLoading && !proposals.isLoading;
  const average = staffItems.length
    ? Math.round(staffItems.reduce((sum, item) => sum + item.progress_rate, 0) / staffItems.length)
    : 0;

  return (
    <main className="min-h-dvh w-full bg-background pb-10">
      <header className="rounded-b-[32px] bg-brand-700 px-5 pb-6 pt-8 text-white">
        <Link href="/owner/intent" className="inline-flex items-center gap-1.5 text-xs font-semibold text-white/70"><span aria-hidden="true">‹</span> 이전으로</Link>
        <div className="mt-4 flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-white/55">사장님 대시보드</p>
            <h1 className="text-2xl font-bold">{state.storeName ?? "카페 아무개"}</h1>
          </div>
          <div className="flex items-center gap-2">
            {isRefreshing && <span className="rounded-full bg-white/12 px-2 py-1 text-[10px] font-semibold text-white/75">갱신 중</span>}
            <Buddy size={54} />
          </div>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2.5">
          {[[`${staffItems.length}명`, "등록 직원"], [`${average}%`, "평균 이해도"], [`${pendingItems.length}건`, "대기 질문"]].map(([value, label]) => (
            <div key={label} className="rounded-2xl bg-white/12 py-3 text-center">
              <p className="text-xl font-bold">{value}</p><p className="text-[11px] font-medium text-white/55">{label}</p>
            </div>
          ))}
        </div>
      </header>

      <div className="space-y-6 px-5 pt-5">
        {firstError && (
          <div data-testid="dashboard-error" role="alert" className="rounded-2xl border border-danger-200 bg-danger-50 p-4 text-center">
            <p className="text-sm font-semibold text-danger-700">대시보드 정보를 불러오지 못했어요.</p>
            <button
              type="button"
              onClick={() => void Promise.all([staff.refetch(), pending.refetch(), proposals.refetch()])}
              className="mt-3 min-h-11 rounded-xl bg-danger-500 px-4 text-sm font-bold text-white"
            >
              다시 시도
            </button>
          </div>
        )}
        <section aria-labelledby="staff-progress-heading">
          <h2 id="staff-progress-heading" className="text-base font-bold text-brand-700">직원 이해도</h2>
          <div className="mt-3 space-y-3">
            {staff.isLoading && <div className="h-24 animate-pulse rounded-2xl bg-surface-muted" />}
            {!staff.isLoading && !staff.error && staffItems.length === 0 && (
              <p data-testid="dashboard-staff-empty" className="rounded-2xl bg-white p-4 text-center text-sm text-muted shadow-sm">등록된 직원이 아직 없어요.</p>
            )}
            {staffItems.map((member) => {
              const tone = progressTone(member.progress_rate);
              return (
                <div key={member.member_id} className="rounded-2xl bg-white p-4 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="grid h-10 w-10 place-items-center rounded-full bg-brand-700 text-sm font-bold text-white">{member.name.slice(0, 1)}</span>
                      <span><strong className="block text-sm">{member.name}</strong><small className="block text-xs text-muted">알바생 ({member.day_count}일차)</small></span>
                    </div>
                    <span className={`text-right text-lg font-bold ${tone.text}`}>{member.progress_rate}%{member.is_deployable && <small className="block text-xs">투입 가능 ✓</small>}</span>
                  </div>
                  <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-surface-muted"><div className={`h-full rounded-full ${tone.bar}`} style={{ width: `${member.progress_rate}%` }} /></div>
                </div>
              );
            })}
          </div>
        </section>

        <section aria-labelledby="pending-heading">
          <div className="flex items-center gap-2"><h2 id="pending-heading" className="text-base font-bold text-brand-700">답변 대기 중</h2><span className="rounded-full bg-accent-100 px-2 py-0.5 text-xs font-bold text-brand-700">{pendingItems.length}건</span></div>
          <div className="mt-3 flex items-end gap-2"><Buddy size={34} /><p className="rounded-2xl rounded-bl-sm bg-accent-100 px-4 py-2.5 text-sm shadow-sm">이 부분은 아직 아무도 안 알려줬어요! 답변하면 Buddy 지식에 자동 반영돼요</p></div>
          <div className="mt-3 space-y-3">
            {pending.isLoading && <div className="h-28 animate-pulse rounded-2xl bg-surface-muted" />}
            {!pending.isLoading && !pending.error && pendingItems.length === 0 && (
              <p data-testid="dashboard-pending-empty" className="rounded-2xl bg-white p-4 text-center text-sm text-muted shadow-sm">지금은 답변을 기다리는 질문이 없어요.</p>
            )}
            {pendingItems.map((item) => (
              <article key={item.question_id} className="rounded-2xl bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between text-xs"><strong className="flex items-center gap-1.5 text-brand-700"><span className="h-2 w-2 rounded-full bg-accent-500" />{item.asked_by}</strong><span className="text-muted">{relativeTime(item.created_at)}</span></div>
                <p className="py-2 text-sm">{item.question_text}</p>
                <Link href={`/owner/questions?question_id=${item.question_id}`} className="flex h-9 items-center justify-center rounded-xl bg-accent-500 text-xs font-bold text-white">답변하기</Link>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="knowledge-gap-heading">
          <h2 id="knowledge-gap-heading" className="text-base font-bold text-brand-700">빈 지식 알림</h2>
          <div className="mt-3 rounded-2xl border border-accent-200 bg-accent-100 p-4">
            <div className="flex items-end gap-2"><Buddy size={32} /><p className="rounded-2xl rounded-bl-sm bg-accent-100 px-4 py-2 text-sm shadow-sm">이 부분은 아직 아무도 안 알려줬어요!</p></div>
            <div className="mt-3 space-y-2">
              {proposalItems.slice(0, 3).map((item) => (
                <div key={item.proposal_id} className="flex items-center justify-between rounded-xl bg-white px-3 py-2.5 text-xs"><strong>❓ {item.question_text}</strong><Link href="/owner/cards" className="font-bold text-brand-500">추가하기</Link></div>
              ))}
              {!proposals.isLoading && !proposals.error && proposalItems.length === 0 && (
                <p data-testid="dashboard-knowledge-empty" className="rounded-xl bg-white px-3 py-3 text-center text-sm text-muted">새로 보완할 지식이 없어요.</p>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
