"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApp } from "@/lib/store";
import { ApiError } from "@/lib/api";
import { rAsk, rCreateSession, type RChatInput } from "@/lib/r-v2-api";
import { rCitationQuery, rHistoryQuery, rKeys, rSessionsQuery } from "@/lib/query";

const button = "min-h-11 rounded-xl border px-4 py-2 disabled:opacity-50";
function Citation({ receipt, order, broken }: { receipt: string; order: number; broken: boolean }) {
  const { state } = useApp();
  const [open, setOpen] = useState(false);
  const citation = useQuery(rCitationQuery(state.token, state.storeId, state.userId, receipt, order, open));
  return <div className="mt-3"><button className={button} onClick={() => setOpen(!open)} aria-expanded={open}>근거 {order} 확인{broken && " · 인용 끊김"}</button>
    {open && <div className="space-y-2 border-l-2 pl-3">{citation.isLoading && <RLoading />}{citation.error && <RError error={citation.error} retry={() => void citation.refetch()} />}
      {citation.data && <><p className="font-semibold">{citation.data.title}</p><p className="whitespace-pre-wrap">{citation.data.text}</p>{citation.data.source_availability !== "AVAILABLE" && <p>원본 자료를 열람할 수 없습니다. 당시 승인된 내용은 보존되어 있습니다.</p>}</>}
    </div>}
  </div>;
}
export function RLoading() {
  return <div aria-label="대화 불러오는 중" className="space-y-4 p-5 animate-pulse"><div className="h-12 rounded-xl bg-gray-200" /><div className="h-32 rounded-xl bg-gray-200" /><div className="h-12 rounded-xl bg-gray-200" /></div>;
}
export function RError({ error, retry }: { error: unknown; retry: () => void }) {
  return <div role="alert" className="rounded-xl border border-red-200 p-4"><p>{error instanceof ApiError ? error.detail : "서버에 연결하지 못했습니다. 입력 내용은 유지됩니다."}</p><button className={button} onClick={retry}>다시 확인</button></div>;
}
export default function RV2Chat() {
  const { state } = useApp();
  const router = useRouter();
  const client = useQueryClient();
  const session = useSearchParams().get("session_id");
  const [input, setInput] = useState("");
  const sessions = useQuery(rSessionsQuery(state.token, state.storeId, state.userId));
  const history = useInfiniteQuery(rHistoryQuery(state.token, state.storeId, state.userId, session));
  const create = useMutation({
    mutationFn: (id: string) => rCreateSession(state.token!, id),
    onSuccess: async (data) => { await client.invalidateQueries({ queryKey: rKeys.sessions(state.storeId, state.userId) }); router.push(`/staff/chat/v2?session_id=${data.session_id}`); },
  });
  const ask = useMutation({ mutationFn: (body: RChatInput) => rAsk(state.token!, body),
    onSuccess: async (_data, body) => { if (!body.policy_receipt_id) setInput(""); await client.invalidateQueries({ queryKey: rKeys.history(state.storeId, state.userId, body.session_id) }); },
  });
  const messages = history.data?.pages.flatMap((page) => page.messages) ?? [];
  const last = messages.at(-1);
  const busy = ask.isPending || create.isPending;
  return <main className="w-full space-y-4 p-4 text-base" data-testid="r-chat">
    <h1 className="text-xl font-bold">확인된 매장 지식으로 질문하기</h1>
    <Link className="underline" href="/staff/chat">이전 대화 보기</Link>
    <Link className="inline-block min-h-11 px-3 py-2 underline" href="/staff/notifications/v2">답변 알림</Link>
    <button className={button} disabled={busy || !state.token} onClick={() => create.mutate(crypto.randomUUID())}>새 대화</button>
    {sessions.isLoading && <RLoading />}
    {sessions.error && <RError error={sessions.error} retry={() => void sessions.refetch()} />}
    {create.error && <RError error={create.error} retry={() => create.variables && create.mutate(create.variables)} />}
    {!session && sessions.data && <nav className="space-y-2"><p>{sessions.data.sessions.length ? "이어서 볼 대화를 선택하세요." : "새 대화를 시작해 업무를 질문해 보세요."}</p>{sessions.data.sessions.map((s) => <Link className="block min-h-11 underline" key={s.session_id} href={`/staff/chat/v2?session_id=${s.session_id}`}>대화 {s.session_id}</Link>)}</nav>}
    {session && <>
      {history.isLoading && <RLoading />}
      {history.error && <RError error={history.error} retry={() => void history.refetch()} />}
      {history.isFetching && !history.isLoading && <p role="status">대화 갱신 중…</p>}
      {history.data && messages.length === 0 && <p>궁금한 대상과 규격을 함께 알려주세요.</p>}
      <ol className="space-y-4" aria-live="polite">{messages.map((m) => <li key={m.message_id} className="rounded-2xl border bg-white p-4 break-words">
        <p className="mb-2 font-semibold">{m.sender === "USER" ? "내 질문" : m.owner_answer_id ? "사장님 답변" : "Buddy"}</p>
        <p className="whitespace-pre-wrap">{m.content}</p>
        {m.response?.action === "SAFE_ROUTE" && m.receipt_id && m.original_question && m.message_id === last?.message_id && !history.hasNextPage && <div className="mt-3 space-y-2">
          <p>이 질문을 사장님께 전달할 수 있어요. 확인 요청은 안전하다는 판정을 뜻하지 않습니다.</p>
          <button className={button} data-testid="r-policy-confirm" disabled={busy} onClick={() => ask.mutate({ request_id: crypto.randomUUID(), session_id: session, question: m.original_question!, policy_receipt_id: m.receipt_id! })}>사장님께 확인 요청</button>
        </div>}
        {m.owner_answer_id && <p className="mt-2 text-sm">답변 {m.revision} · 지식 반영: {({ PENDING: "대기", REVIEW: "검토 필요", LINKED: "기존 지식 연결", PUBLISHED: "공개 완료", FAILED: "실패" } as Record<string, string>)[m.knowledge_status ?? ""] ?? "확인 중"}</p>}
        {m.receipt_id && m.response?.citations.map((c, index) => <Citation key={index} receipt={m.receipt_id!} order={index+1} broken={c.source_availability !== "AVAILABLE"} />)}
        {m.response?.action === "CLARIFY" && m.message_id === last?.message_id && !history.hasNextPage && m.context_revision !== null && <div className="mt-3 flex flex-wrap gap-2">{m.response.allowed_options.map((option) => <button className={button} disabled={busy} key={option} onClick={() => ask.mutate({ request_id: crypto.randomUUID(), session_id: session, question: option, option, context_id: m.response!.context_id!, context_revision: m.context_revision! })}>{option}</button>)}</div>}
      </li>)}</ol>
      {history.hasNextPage && <button className={button} disabled={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>다음 대화 기록 보기</button>}
      {ask.error && <RError error={ask.error} retry={() => ask.variables && ask.mutate(ask.variables)} />}
      {ask.isPending && <p role="status">{ask.variables?.policy_receipt_id ? "확인 요청을 보내고 있어요…" : "근거를 확인하고 있어요…"}</p>}
      <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); if (input.trim() && !busy) ask.mutate({ request_id: crypto.randomUUID(), session_id: session, question: input }); }}>
        <label className="block" htmlFor="r-question">업무 질문</label><textarea id="r-question" maxLength={1000} value={input} disabled={busy} onChange={(event) => setInput(event.target.value)} className="w-full rounded-xl border p-3" />
        <button className={button} disabled={busy || !input.trim() || !history.data}>질문하기</button>
      </form>
      <button className={button} disabled={history.isFetching} onClick={() => void history.refetch()}>새 답변 확인</button>
    </>}
  </main>;
}
