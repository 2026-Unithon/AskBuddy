"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card } from "@/components/ui";
import { ApiError, askChat } from "@/lib/api";
import { faqsQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

function message(error: unknown) {
  return error instanceof ApiError
    ? error.detail || "자주 묻는 질문을 불러오지 못했어요."
    : "서버에 연결할 수 없습니다.";
}

export default function FaqPage() {
  const router = useRouter();
  const { state } = useApp();
  const queryClient = useQueryClient();

  const [expandedFaqKey, setExpandedFaqKey] = useState<string | null>(null);

  const faqs = useQuery(faqsQuery(state.token, state.storeId));

  const ask = useMutation({
    mutationFn: (question: string) => askChat(question, state.token!),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.chat(state.storeId, state.userId),
      });
      router.push("/staff/chat");
    },
  });

  const error = faqs.error ?? ask.error;

  function toggleExpand(key: string) {
    setExpandedFaqKey((prev) => (prev === key ? null : key));
  }

  return (
    <div className="flex-1 flex flex-col w-full bg-background min-h-dvh">
      {/* 상단 컴팩트 헤더 */}
      <header className="shrink-0 bg-surface border-b border-border px-4 py-3.5 flex items-center justify-between shadow-xs">
        <div>
          <h1 className="text-base font-bold text-brand-700">자주 묻는 질문</h1>
          <p className="text-xs text-muted mt-0.5">매장 실제 질문 빈도 기반 FAQ</p>
        </div>
        {faqs.isFetching && !faqs.isLoading && (
          <span className="text-xs text-muted bg-surface-muted px-2 py-0.5 rounded-full">
            갱신 중…
          </span>
        )}
      </header>

      {/* 메인 FAQ 리스트 (하단 탭 바 높이 고려 pb-24) */}
      <main className="flex-1 space-y-3 overflow-y-auto px-4 py-3 pb-[calc(6rem+env(safe-area-inset-bottom,0px))]">
        <p className="text-sm leading-relaxed text-muted px-0.5">
          실제로 자주 나온 질문 중 현재 공개된 업무 카드로 답할 수 있는 항목만 모았어요.
        </p>

        {/* 로딩 스켈레톤 */}
        {faqs.isLoading && (
          <div className="space-y-3" aria-label="자주 묻는 질문 불러오는 중">
            {[0, 1, 2].map((item) => (
              <div
                key={item}
                className="h-28 motion-safe:animate-pulse rounded-2xl bg-surface-muted/60"
              />
            ))}
          </div>
        )}

        {/* 에러 상태 */}
        {error && (
          <Card className="space-y-3 p-5 text-center">
            <p role="alert" className="text-sm font-semibold text-danger-500">
              {message(error)}
            </p>
            <Button
              variant="secondary"
              size="md"
              className="min-h-[44px]"
              onClick={() => void faqs.refetch()}
            >
              다시 시도
            </Button>
          </Card>
        )}

        {/* 빈 상태 (가짜 샘플 금지) */}
        {!faqs.isLoading && !error && (faqs.data?.items.length ?? 0) === 0 && (
          <Card className="space-y-3 p-6 text-center">
            <span className="text-3xl block" aria-hidden="true">
              ❓
            </span>
            <div className="space-y-1">
              <p className="text-sm font-bold text-foreground">
                아직 자주 묻는 질문이 없어요
              </p>
              <p className="text-sm text-muted leading-relaxed">
                가짜 예시는 만들지 않아요. 직원들의 질문이 쌓이면 자동으로 여기에 정리됩니다.
              </p>
            </div>
            <Link
              href="/staff/chat"
              className="inline-flex min-h-[44px] items-center justify-center rounded-xl bg-brand-500 px-4 text-sm font-bold text-white shadow-xs transition-transform active:scale-95 hover:bg-brand-600"
            >
              Buddy에게 직접 질문하기 →
            </Link>
          </Card>
        )}

        {/* FAQ 카드 목록 */}
        {faqs.data?.items.map((faq) => {
          const faqKey = `${faq.card_id}-${faq.question}`;
          const isExpanded = expandedFaqKey === faqKey;
          const isCurrentAsking = ask.isPending && ask.variables === faq.question;

          return (
            <Card
              key={faqKey}
              className="space-y-3 p-4 border-border transition-all hover:border-brand-200"
            >
              {/* 메타데이터: 카테고리 + 질문 횟수 */}
              <div className="flex items-center justify-between gap-2">
                <Badge tone="neutral">{faq.category_name}</Badge>
                <span className="shrink-0 text-xs font-bold text-brand-700 bg-brand-50 px-2 py-0.5 rounded-full">
                  {faq.question_count}회 질문됨
                </span>
              </div>

              {/* 질문 제목 */}
              <h2 className="text-base font-bold text-foreground leading-snug">
                Q. {faq.question}
              </h2>

              {/* 근거 카드 정보 및 본문 미리보기 토글 */}
              <div className="rounded-xl bg-surface-muted/40 p-3 space-y-1.5 border border-border/60">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted font-medium truncate">
                    근거: <strong>{faq.card_title}</strong>
                  </span>
                  <button
                    type="button"
                    onClick={() => toggleExpand(faqKey)}
                    className="min-h-11 rounded-lg px-3 text-sm font-bold text-brand-600 hover:bg-brand-50 hover:text-brand-700 shrink-0 ml-2"
                    aria-expanded={isExpanded}
                  >
                    {isExpanded ? "내용 닫기 ▲" : "내용 미리보기 ▼"}
                  </button>
                </div>

                {isExpanded && (
                  <div className="pt-2 border-t border-border/50 text-base leading-relaxed text-foreground/90 whitespace-pre-wrap select-text animate-[fadeIn_0.2s_ease-out]">
                    {faq.card_content}
                  </div>
                )}
              </div>

              {/* 하단 단일 액션 CTA */}
              <Button
                variant="primary"
                size="md"
                className="w-full min-h-[44px] font-bold text-sm active:scale-[0.98]"
                loading={isCurrentAsking}
                loadingLabel="Buddy 답변 불러오는 중"
                disabled={isCurrentAsking}
                onClick={() => ask.mutate(faq.question)}
              >
                Buddy와 대화로 확인하기 →
              </Button>
            </Card>
          );
        })}
      </main>
    </div>
  );
}
