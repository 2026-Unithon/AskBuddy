"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  BackButton,
  Button,
  ButtonLink,
  Caption,
  Empty,
  ErrorInline,
  NumberedContent,
  Screen,
  Skeleton,
  Surface,
  TextButton,
  focusRing,
} from "@/components/kit";
import { ApiError, apiErrorMessage, setLearnItemCompletion } from "@/lib/api";
import { learnItemQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

// A8 레시피 보기: 지금 공개된 카드 + 확인 완료/재확인. 완료는 서버 저장 성공 뒤에만 확정한다 (MVP §12).
export default function StaffRecipePage() {
  const params = useParams<{ itemId: string }>();
  const itemId = /^\d+$/.test(params.itemId) ? Number(params.itemId) : 0;
  const { state } = useApp();
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
        <BackButton href="/staff/recipes" label="레시피" />
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-40" />
      </Screen>
    );
  }
  if (!itemId || item.error || !item.data) {
    const missing = !itemId || (item.error instanceof ApiError && [403, 404].includes(item.error.status));
    return (
      <Screen>
        <BackButton href="/staff/recipes" label="레시피" />
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
  const sources = [...new Set(data.evidence.map((e) => e.source.title).filter(Boolean))];
  const brokenSource = data.evidence.some((e) => e.source.source_availability === "DELETED");

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
          <Link
            href={`/staff/ask?q=${encodeURIComponent(`${data.title} `)}`}
            className={`flex h-14 w-full items-center rounded-[28px] bg-surface px-[18px] text-[15px] tracking-[-0.15px] text-ink-muted shadow-card ${focusRing}`}
          >
            이 레시피에 대해 물어보기
          </Link>
        </>
      }
    >
      <BackButton href="/staff/recipes" label="레시피" />
      <p className="text-[13px] font-bold text-primary">{data.category.name}</p>
      <h1 className="text-[30px] font-bold leading-[1.28] tracking-[-0.9px] text-ink [word-break:keep-all]">{data.title}</h1>
      <Surface className="px-[18px] py-4">
        <NumberedContent content={data.content} />
      </Surface>
      {reconfirm && (
        <p className="rounded-[14px] bg-empty px-3.5 py-2.5 text-[12px] font-bold text-primary">내용이 바뀌었어요. 다시 한 번 확인해주세요</p>
      )}
      {done && <Caption>확인했어요. 내용이 바뀌면 다시 알려드려요.</Caption>}
      {sources.length > 0 && (
        <Caption>
          출처 · {sources.join(", ")}
          {brokenSource ? " · 인용 끊김" : ""}
        </Caption>
      )}
    </Screen>
  );
}
