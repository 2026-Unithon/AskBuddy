"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Empty,
  ErrorInline,
  Icon,
  ListGroup,
  ListRow,
  PageHeader,
  RefreshingHint,
  Screen,
  HeaderActions,
  Skeleton,
  Stagger,
  STAFF_TABS,
  TabBar,
} from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { roadmapQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

// A7 레시피: 승인 카드로 만든 동적 로드맵(카테고리 = 묶음, 카드 = 행). 샘플로 채우지 않는다 (MVP §12).
export default function StaffRecipesPage() {
  const { state } = useApp();
  const roadmap = useQuery(roadmapQuery(state.token, state.storeId, state.userId));
  const [search, setSearch] = useState("");
  const keyword = search.trim();
  const stages = (roadmap.data?.stages ?? [])
    .map((stage) => ({ ...stage, items: keyword ? stage.items.filter((item) => item.title.includes(keyword)) : stage.items }))
    .filter((stage) => stage.items.length > 0);
  const total = roadmap.data?.counts.total ?? 0;

  return (
    <Screen tabBar={<TabBar tabs={STAFF_TABS} />}>
      <PageHeader title="레시피" action={<HeaderActions role="STAFF" />} />
      <label className="flex w-full items-center gap-2 rounded-full bg-surface px-4 py-3 shadow-card">
        <Icon name="search" size={16} className="text-ink-muted" />
        <input
          type="search"
          aria-label="레시피 찾기"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="메뉴 이름으로 찾기"
          className="min-w-0 flex-1 bg-transparent text-[15px] leading-[1.45] tracking-[-0.15px] text-ink outline-none placeholder:text-ink-muted"
        />
      </label>

      {roadmap.isLoading && (
        <>
          <Skeleton className="h-40" />
          <Skeleton className="h-32" />
        </>
      )}
      {roadmap.error && (
        <ErrorInline message={apiErrorMessage(roadmap.error, "레시피를 불러오지 못했어요.")} onRetry={() => void roadmap.refetch()} retrying={roadmap.isRefetching} />
      )}
      {roadmap.data && total === 0 && (
        <Empty title="아직 준비된 학습 자료가 없어요" description="사장님이 자료를 올리면 여기에 레시피가 생겨요." />
      )}
      {roadmap.data && total > 0 && stages.length === 0 && (
        <Empty buddy={false} title="찾는 레시피가 없어요" description="다른 말로 찾거나 버디에게 물어보세요." />
      )}

      {/* s02b: 상태는 글자가 아니라 표시로(확인함은 초록 체크, 내용이 바뀐 것은 주황 점) */}
      <Stagger>
        {stages.map((stage) => (
          <ListGroup key={stage.category_id} label={stage.name}>
            {stage.items.map((item) => (
              <ListRow
                key={item.item_id}
                title={item.title}
                href={`/staff/recipes/${item.item_id}`}
                badge={
                  item.status === "RECONFIRM_REQUIRED" ? (
                    <span role="img" aria-label="내용이 바뀜" className="size-2.5 shrink-0 rounded-full bg-warn-500" />
                  ) : item.status === "DONE" ? (
                    <span role="img" aria-label="확인함" className="flex shrink-0 text-primary">
                      <Icon name="check" size={16} />
                    </span>
                  ) : undefined
                }
              />
            ))}
          </ListGroup>
        ))}
      </Stagger>
      <RefreshingHint active={roadmap.isRefetching && !roadmap.isLoading} />
    </Screen>
  );
}
