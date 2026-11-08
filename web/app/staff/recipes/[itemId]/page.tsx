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
import { compactRecipe } from "@/components/owner/fact-card/fact-group";
import { RecipeView } from "@/components/owner/fact-card/recipe-view";
import { ApiError, apiErrorMessage, setLearnItemCompletion } from "@/lib/api";
import { learnItemQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

/**
 * 내용을 묶음별로 나눈다(s03a). 서버 본문(card_plan.render_card)은 `[재료 · HOT]` 머리줄 + `- 줄`/`1. 줄`,
 * 맨 끝에 근거 자료 줄이 붙는다. 머리줄은 '규격 + 종류'(HOT 재료) 제목으로, 근거 줄은 빼고(s03b), 줄머리 기호는 지운다.
 * 머리줄이 없는 옛 본문은 `HOT …`·`ICE …` 로 시작하는 줄을 규격 제목으로 나눈다.
 */
function splitVariants(content: string): { label: string | null; text: string }[] {
  const lines = content.split("\n").map((line) => line.trim());
  const head = /^\[([^\]·]+?)(?:\s*·\s*([^\]]+))?\]$/;
  if (lines.some((line) => head.test(line))) {
    const parts: { label: string | null; text: string }[] = [];
    for (const line of lines) {
      if (!line || line.startsWith("근거 자료")) continue;
      const match = line.match(head);
      if (match) {
        parts.push({ label: match[2] ? `${match[2].trim()} ${match[1].trim()}` : match[1].trim(), text: "" });
        continue;
      }
      const body = line.replace(/^(?:-\s+|\d+\.\s+)/, "");
      if (!parts.length) parts.push({ label: null, text: "" });
      const last = parts.at(-1)!;
      last.text = last.text ? `${last.text}\n${body}` : body;
    }
    return parts.filter((part) => part.text);
  }
  const variant = /^(HOT|ICE)\s+(.*)$/;
  if (!lines.some((line) => variant.test(line))) return [{ label: null, text: content }];
  const parts: { label: string | null; text: string }[] = [];
  for (const line of lines) {
    if (!line) continue;
    const match = line.match(variant);
    if (match) parts.push({ label: match[1], text: match[2] });
    else if (parts.length) parts.at(-1)!.text += `\n${line}`;
    else parts.push({ label: null, text: line });
  }
  return parts;
}

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
  const parts = splitVariants(data.content);
  const recipe = data.fact_blocks ? compactRecipe(data.fact_blocks) : null;
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
      <p className="text-[13px] font-bold text-primary">{data.category.name}</p>
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="min-w-0 text-[30px] font-bold leading-[1.28] tracking-[-0.9px] text-ink [word-break:keep-all]">{data.title}</h1>
        {recipe?.price && <p className="shrink-0 text-[17px] font-bold text-ink">{recipe.price}</p>}
      </div>
      {/* 사실 카드면 사장님 화면과 같은 한눈에 보기(계획 7 Task 12), 아니면 본문 그대로 */}
      {recipe ? <RecipeView recipe={recipe} /> : parts.map((part, i) =>
        part.label ? (
          <section key={i} className="flex flex-col gap-2">
            <h2 className="px-1 text-[18px] font-bold text-ink">{part.label}</h2>
            <Surface className="px-[18px] py-4">
              <NumberedContent content={part.text} />
            </Surface>
          </section>
        ) : (
          <Surface key={i} className="px-[18px] py-4">
            <NumberedContent content={part.text} />
          </Surface>
        ),
      )}
      {reconfirm && (
        <p className="rounded-[14px] bg-empty px-3.5 py-2.5 text-[12px] font-bold text-primary">내용이 바뀌었어요. 다시 한 번 확인해주세요</p>
      )}
    </Screen>
  );
}
