"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Shell, TopBar } from "@/components/ui";
import { ApiError, askChat } from "@/lib/api";
import { faqsQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

function message(error: unknown) {
  return error instanceof ApiError ? error.detail || "자주 묻는 질문을 불러오지 못했어요." : "서버에 연결할 수 없습니다.";
}

export default function FaqPage() {
  const router = useRouter();
  const { state } = useApp();
  const queryClient = useQueryClient();
  const faqs = useQuery(faqsQuery(state.token, state.storeId));
  const ask = useMutation({
    mutationFn: (question: string) => askChat(question, state.token!),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.chat(state.storeId, state.userId) });
      router.push("/staff/chat");
    },
  });
  const error = faqs.error ?? ask.error;

  return (
    <Shell>
      <TopBar title="자주 묻는 질문" backHref="/staff/roadmap" />
      <div className="flex-1 space-y-3 overflow-y-auto px-5 pb-8">
        <p className="text-xs leading-relaxed text-muted">실제로 자주 나온 질문 중 현재 공개 카드로 답할 수 있는 항목만 보여드려요.</p>
        {faqs.isFetching && !faqs.isLoading && <p className="text-[11px] text-muted">최신 질문 확인 중…</p>}
        {faqs.isLoading && <div className="space-y-3" aria-label="자주 묻는 질문 불러오는 중">{[0, 1, 2].map((item) => <div key={item} className="h-28 animate-pulse rounded-2xl bg-surface-muted" />)}</div>}
        {error && <Card className="space-y-3 p-5 text-center"><p role="alert" className="text-sm text-danger-500">{message(error)}</p><Button variant="secondary" onClick={() => void faqs.refetch()}>다시 시도</Button></Card>}
        {!faqs.isLoading && !error && (faqs.data?.items.length ?? 0) === 0 && (
          <Card className="space-y-2 p-6 text-center"><p className="text-sm font-bold">아직 자주 묻는 질문이 없어요.</p><p className="text-xs text-muted">임의 예시는 만들지 않아요. 궁금한 업무는 Buddy에게 직접 물어보세요.</p><Link href="/staff/chat" className="inline-flex min-h-11 items-center text-sm font-bold text-brand-500">Buddy에게 질문하기</Link></Card>
        )}
        {faqs.data?.items.map((faq) => (
          <Card key={`${faq.card_id}-${faq.question}`} className="space-y-3 p-4">
            <div className="flex items-start justify-between gap-3"><div><Badge tone="neutral">{faq.category_name}</Badge><h2 className="mt-2 text-sm font-bold">{faq.question}</h2></div><span className="shrink-0 text-[11px] font-semibold text-muted">{faq.question_count}회 질문</span></div>
            <p className="line-clamp-2 text-xs leading-relaxed text-muted">근거 카드: {faq.card_title}</p>
            <Button className="w-full" disabled={ask.isPending} onClick={() => ask.mutate(faq.question)}>{ask.isPending && ask.variables === faq.question ? "근거 확인 중…" : "Buddy 답변 보기"}</Button>
          </Card>
        ))}
      </div>
    </Shell>
  );
}
