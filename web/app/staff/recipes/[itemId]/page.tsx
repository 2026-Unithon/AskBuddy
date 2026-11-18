"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import {
  BackButton,
  Button,
  ButtonLink,
  Empty,
  ErrorInline,
  NumberedContent,
  Screen,
  Skeleton,
  Surface,
  TextButton,
} from "@/components/kit";
import { SuggestedQuestions } from "@/components/staff/suggested-questions";
import { CardLinesView, PriceTag } from "@/components/owner/fact-card/card-lines-view";
import { splitPrice } from "@/lib/card-price";
import { ApiError, apiErrorMessage, setLearnItemCompletion } from "@/lib/api";
import { learnItemQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

// A8 레시피 보기: 지금 공개된 카드 + 확인 완료/재확인. 완료는 서버 저장 성공 뒤에만 확정한다 (MVP §12).
export default function StaffRecipePage() {
  const params = useParams<{ itemId: string }>();
  const itemId = /^\d+$/.test(params.itemId) ? Number(params.itemId) : 0;
  const { state } = useApp();
  const router = useRouter();
  const client = useQueryClient();
  const item = useQuery(learnItemQuery(state.token, state.storeId, state.userId, itemId));

  const complete = useMutation({
    mutationFn: (completed: boolean) =>
      setLearnItemCompletion(itemId, item.data!.published_version_id, completed, state.token!),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.learnItem(state.storeId, state.userId, itemId) }),
        client.invalidateQueries({ queryKey: queryKeys.roadmapRoot(state.storeId) }),
      ]),
    onError: async (error) => {
      // 그사이 새 버전이 공개됐으면 최신 내용을 다시 받는다
      if (error instanceof ApiError && error.status === 409) await item.refetch();
    },
  });

  if (item.isLoading) {
    return (
      <Screen>
        <BackButton parent="/staff/recipes" label="레시피" />
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-40" />
      </Screen>
    );
  }
  if (!itemId || item.error || !item.data) {
    const missing = !itemId || (item.error instanceof ApiError && [403, 404].includes(item.error.status));
    return (
      <Screen>
        <BackButton parent="/staff/recipes" label="레시피" />
        {missing ? (
          <Empty title="이 레시피를 볼 수 없어요" description="지워졌거나 아직 공개되지 않은 카드예요." action={<ButtonLink href="/staff/recipes">레시피로</ButtonLink>} />
        ) : (
          <ErrorInline message={apiErrorMessage(item.error, "레시피를 불러오지 못했어요.")} onRetry={() => void item.refetch()} retrying={item.isRefetching} />
        )}
      </Screen>
    );
  }

  const data = item.data;
  const done = data.status === "DONE";
  const reconfirm = data.status === "RECONFIRM_REQUIRED";
  // 사장님 상세와 같이 금액 줄은 제목 옆으로
  const lines = data.fact_blocks
    ? splitPrice(data.fact_blocks.map((block, i) => ({ key: String(i), kind: block.kind, heading: block.heading, lines: block.lines })))
    : null;
  const askWith = (text: string) => router.push(`/staff/ask?q=${encodeURIComponent(text)}`);

  return (
    <Screen
      footer={
        <>
          {complete.error && (
            <ErrorInline
              message={
                complete.error instanceof ApiError && complete.error.status === 409
                  ? "내용이 바뀌었어요. 다시 한 번 확인해주세요."
                  : "아직 완료로 저장되지 않았어요. 다시 눌러주세요."
              }
            />
          )}
          {done ? (
            <TextButton className="self-center" disabled={complete.isPending} onClick={() => complete.mutate(false)}>
              확인 취소하기
            </TextButton>
          ) : (
            <Button loading={complete.isPending} onClick={() => complete.mutate(true)}>
              확인했어요
            </Button>
          )}
          {/* s03c: 추천 질문 칩. 맨 앞은 이 레시피로 질문을 시작하는 칩 */}
          <div className="flex flex-col gap-2">
            <button
              type="button"
              data-suggested=""
              onClick={() => askWith(`${data.title} `)}
              className="min-h-10 self-start whitespace-nowrap rounded-full bg-surface px-3.5 text-[14px] font-medium text-primary shadow-card"
            >
              이 레시피에 대해 물어보기
            </button>
            <SuggestedQuestions cardId={data.card_id} limit={2} onPick={(question) => router.push(`/staff/ask?q=${encodeURIComponent(question)}&send=1`)} />
          </div>
        </>
      }
    >
      <BackButton parent="/staff/recipes" label="레시피" />
      {/* 머리는 사장님 카드 상세와 같다(카테고리 칩 + 제목). 직원은 카테고리를 옮기지 않으므로 칩은 누르지 않는다 */}
      <span className="inline-flex min-h-8 items-center self-start rounded-full bg-empty px-3 text-[13px] font-bold text-primary">{data.category.name}</span>
      <div className="-mt-2 flex items-baseline justify-between gap-3">
        <h1 className="min-w-0 text-[30px] font-bold leading-[1.28] tracking-[-0.9px] text-ink [word-break:keep-all]">{data.title}</h1>
        <PriceTag price={lines?.price ?? []} />
      </div>
      {/* 사실 카드면 사장님 상세와 같은 보기(계획 10), 아니면 본문 그대로 */}
      {lines ? (
        <CardLinesView blocks={lines.blocks.filter((block) => block.lines.length > 0)} />
      ) : (
        <Surface className="px-[18px] py-4">
          <NumberedContent content={data.content} />
        </Surface>
      )}
      {reconfirm && (
        <p className="rounded-[14px] bg-empty px-3.5 py-2.5 text-[12px] font-bold text-primary">내용이 바뀌었어요. 다시 한 번 확인해주세요</p>
      )}
    </Screen>
  );
}
