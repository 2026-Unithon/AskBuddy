"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useApp } from "@/lib/store";
import { chatQuery } from "@/lib/query";
import { RError, RLoading } from "@/components/r-v2-chat";

export default function ChatHistoryPage() {
  const { state } = useApp();
  const history = useQuery(chatQuery(state.token, state.storeId, state.userId));
  return <main className="space-y-4 p-4">
    <h1 className="text-xl font-bold">이전 대화 이력</h1>
    <p>새 질문은 새 Buddy 화면에서 할 수 있습니다.</p>
    <Link href="/staff/chat/v2" className="inline-flex min-h-11 items-center rounded-xl border px-4">Buddy에서 질문하기</Link>
    {history.isLoading && <RLoading />}
    {history.error && <RError error={history.error} retry={() => void history.refetch()} />}
    {history.data && !history.data.messages.length && <p>이전 대화가 없습니다.</p>}
    <ol className="space-y-3">{history.data?.messages.map((message) => <li key={message.message_id} className="rounded-xl border p-4 break-words">
      <p className="font-semibold">{message.sender_type === "USER" ? "내 질문" : "이전에 저장된 답변"}</p>
      <p className="whitespace-pre-wrap">{message.content}</p>
    </li>)}</ol>
  </main>;
}
