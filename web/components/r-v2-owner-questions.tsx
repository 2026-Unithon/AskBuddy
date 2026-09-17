"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApp } from "@/lib/store";
import { rOwnerAnswer, type ROwnerInput } from "@/lib/r-v2-api";
import { rDetailQuery, rKeys, rPendingQuery } from "@/lib/query";
import { RError, RLoading } from "./r-v2-chat";

const button = "min-h-11 rounded-xl border px-4 py-2 disabled:opacity-50";
function Question({ id }: { id: string }) {
  const { state } = useApp();
  const client = useQueryClient();
  const [answer, setAnswer] = useState("");
  const detail = useQuery(rDetailQuery(state.token, state.storeId, state.userId, id));
  const submit = useMutation({ mutationFn: (body: ROwnerInput) => rOwnerAnswer(state.token!, id, body),
    onSuccess: async () => { setAnswer(""); await client.invalidateQueries({ queryKey: rKeys.pending(state.storeId, state.userId) }); },
  });
  const latest = detail.data?.answers.at(-1);
  return <section className="space-y-4" data-testid="r-owner-detail">
    {detail.isLoading && <RLoading />}
    {detail.error && <RError error={detail.error} retry={() => void detail.refetch()} />}
    {detail.isFetching && !detail.isLoading && <p role="status">처리 상태 갱신 중…</p>}
    {detail.data && <>
      <h2 className="text-lg font-bold">직원이 확인을 요청한 내용</h2>
      {detail.data.occurrences.map((o) => <article key={o.receipt_id} className="rounded-xl border p-4 break-words">
        <p className="whitespace-pre-wrap">{o.original_question}</p>
        {o.context_snapshot?.context?.original_question && <p className="mt-2 whitespace-pre-wrap">앞선 질문: {o.context_snapshot.context.original_question}</p>}
        <dl className="mt-2">{Object.entries(o.resolved_query.confirmed_slots ?? {}).map(([slot, value]) => <div key={slot}><dt className="inline font-medium">{({ entity: "대상", predicate: "물어본 내용", temperature: "온도", size: "크기" } as Record<string, string>)[slot] ?? "확인한 조건"}: </dt><dd className="inline">{value}</dd></div>)}</dl>
      </article>)}
      {detail.data.answers.map((a) => <article key={a.owner_answer_id} className="rounded-xl bg-green-50 p-4 break-words">
        <p className="font-semibold">저장된 점주 답변 {a.revision}</p><p className="whitespace-pre-wrap">{a.answer}</p>
        <p>지식 반영: {({ PENDING: "대기", REVIEW: "검토 필요", LINKED: "기존 지식 연결", PUBLISHED: "공개 완료", FAILED: "실패" } as Record<string, string>)[a.knowledge_status] ?? "확인 중"}</p>
      </article>)}
      <p>저장한 원문은 해당 질문자에게 전달됩니다. 지식 반영 상태는 별도로 확인할 수 있습니다.</p>
      {submit.error && <RError error={submit.error} retry={() => submit.variables && submit.mutate(submit.variables)} />}
      {submit.isSuccess && <p role="status">답변이 저장됐습니다.</p>}
      <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); if (answer.trim() && !submit.isPending) submit.mutate({ request_id: crypto.randomUUID(), answer, expected_revision: latest?.revision ?? 0 }); }}>
        <label className="block" htmlFor="r-owner-answer">{latest ? "수정 답변" : "직원에게 보낼 답변"}</label>
        <textarea id="r-owner-answer" value={answer} disabled={submit.isPending} maxLength={10000} onChange={(event) => { setAnswer(event.target.value); if (submit.isSuccess) submit.reset(); }} className="min-h-32 w-full rounded-xl border p-3" />
        <button className={button} disabled={submit.isPending || !answer.trim()}>{submit.isPending ? "저장 중…" : latest ? "새 버전으로 저장" : "답변 저장"}</button>
      </form>
      <button className={button} disabled={detail.isFetching} onClick={() => void detail.refetch()}>최신 상태 확인</button>
    </>}
  </section>;
}
export default function RV2OwnerQuestions() {
  const { state } = useApp();
  const id = useSearchParams().get("question_id");
  const pending = useInfiniteQuery(rPendingQuery(state.token, state.storeId, state.userId));
  const questions = pending.data?.pages.flatMap((page) => page.questions) ?? [];
  return <main className="space-y-4 p-4 text-base" data-testid="r-owner-questions">
    <h1 className="text-xl font-bold">직원 질문 확인</h1>
    <Link href="/owner/questions" className="underline">이전 질문 보기</Link>
    {pending.isLoading && <RLoading />}
    {pending.error && <RError error={pending.error} retry={() => void pending.refetch()} />}
    {pending.data && !questions.length && <p>아직 확인을 요청한 질문이 없습니다.</p>}
    <nav className="space-y-2">{questions.map((q) => <Link key={q.pending_id} className="block min-h-11 rounded-xl border p-3 break-words" href={`/owner/questions/v2?question_id=${q.pending_id}`}>{q.status === "WAITING" ? "확인 대기" : "답변 저장됨"} · {q.question}</Link>)}</nav>
    {pending.hasNextPage && <button className={button} disabled={pending.isFetchingNextPage} onClick={() => void pending.fetchNextPage()}>다음 질문 보기</button>}
    {id && <Question key={id} id={id} />}
  </main>;
}
