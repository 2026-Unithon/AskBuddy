"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  BackButton,
  Caption,
  CardLink,
  ErrorInline,
  ListGroup,
  ListRow,
  PageHeader,
  RefreshingHint,
  Screen,
  SectionTitle,
  Skeleton,
  Surface,
} from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { formatMinutes, type ReportSummary } from "@/lib/owner-ops";
import { reportQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

/**
 * 사장 리포트. 알바생이 얼마나 묻고, AI가 얼마나 바로 답했고, 사장님께 몇 번 넘어왔는지 건수로 보인다.
 * 완성도·신뢰도 퍼센트는 쓰지 않는다(CLAUDE.md 하지 말 것).
 */
export default function OwnerReportPage() {
  const { state } = useApp();
  const [days, setDays] = useState<7 | 30>(7);
  const report = useQuery(reportQuery(state.token, state.storeId, days));

  return (
    <Screen>
      <BackButton href="/owner" />
      <PageHeader title="매장 리포트" description="알바생 질문이 사장님 손을 얼마나 덜 거쳤는지 보여줘요" />
      <div className="flex gap-2" aria-label="기간 선택">
        {([7, 30] as const).map((d) => (
          <button
            key={d}
            type="button"
            aria-pressed={days === d}
            onClick={() => setDays(d)}
            className={`min-h-11 rounded-full px-4 ${days === d ? "bg-primary text-white" : "bg-surface text-primary"}`}
          >
            최근 {d}일
          </button>
        ))}
      </div>
      {report.isLoading && (
        <>
          <Skeleton className="h-40" />
          <Skeleton className="h-32" />
        </>
      )}
      {report.error && (
        <ErrorInline
          message={apiErrorMessage(report.error, "리포트를 불러오지 못했어요.")}
          onRetry={() => void report.refetch()}
          retrying={report.isRefetching}
        />
      )}
      {report.data && <ReportBody data={report.data} />}
      <RefreshingHint active={report.isRefetching && !report.isLoading} />
    </Screen>
  );
}

function Stat({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-[16px] bg-background px-3.5 py-3">
      <span className="text-[12px] text-ink-muted">{label}</span>
      <span data-testid={testId} className="text-[22px] font-bold text-ink">
        {value}
      </span>
    </div>
  );
}

function ReportBody({ data }: { data: ReportSummary }) {
  const q = data.questions;
  return (
    <>
      <Caption>
        {data.first_date}부터 {data.last_date}까지 (영업일 기준)
      </Caption>
      <Surface className="p-[18px]">
        <p className="text-[15px] font-bold text-ink [word-break:keep-all]" data-testid="report-headline">
          알바생 질문 {q.questions}건 중 {q.ai_answered}건은 AI가 바로 답했어요
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Stat label="알바생 질문" value={`${q.questions}건`} testId="report-questions" />
          <Stat label="AI가 바로 답함" value={`${q.ai_answered}건`} testId="report-ai-answered" />
          <Stat label="사장님께 넘어옴" value={`${q.escalated}건`} testId="report-escalated" />
          <Stat label="사장님이 답함" value={`${q.owner_answered}건`} />
          <Stat label="답하기까지 (가운데값)" value={formatMinutes(q.answer_minutes_median)} />
          <Stat label="지금 기다리는 질문" value={`${q.waiting_now}건`} />
        </div>
        <Caption className="mt-3">사장님이 한 번 답한 질문은 매장 지식이 돼서, 다음부터는 AI가 답해요.</Caption>
      </Surface>

      <SectionTitle>자주 넘어온 질문</SectionTitle>
      {data.top_escalations.length === 0 ? (
        <Caption>이 기간에 사장님께 넘어온 질문이 없어요.</Caption>
      ) : (
        data.top_escalations.map((item) => (
          <CardLink
            key={item.question_id}
            href={`/owner/questions/${item.question_id}`}
            title={item.question_text}
            meta={`${item.asked}번 물어봄${item.status === "WAITING" ? ", 아직 답 안 함" : ""}`}
          />
        ))
      )}

      <SectionTitle>알바생별</SectionTitle>
      {data.per_staff === null ? (
        <Caption>알바생 기록 보기를 꺼 두셔서 사람별 숫자는 보이지 않아요.</Caption>
      ) : data.per_staff.length === 0 ? (
        <Caption>아직 연결된 알바생이 없어요.</Caption>
      ) : (
        <ListGroup>
          {data.per_staff.map((s) => (
            <ListRow key={s.member_id} title={s.name} subtitle={`질문 ${s.questions}건, 사장님께 넘어감 ${s.escalated}건`} />
          ))}
        </ListGroup>
      )}

      <SectionTitle>매장 운영</SectionTitle>
      <ListGroup>
        <ListRow
          title="체크리스트 제출"
          subtitle={`${data.checklist.submissions}번 제출, 다 한 날 ${data.checklist.complete}번`}
        />
        <ListRow
          title="오늘만 할 일"
          subtitle={`${data.today_tasks.tasks}건 보냄, ${data.today_tasks.assigned}명 중 ${data.today_tasks.done}명 완료`}
        />
      </ListGroup>
    </>
  );
}
