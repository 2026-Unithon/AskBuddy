"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { BackButton, ButtonLink, Caption, ListGroup, ListRow, PageHeader, Screen } from "@/components/kit";
import { OwnerAddComposer } from "@/components/owner/owner-add-composer";
import { productCategoriesQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

// 레시피는 며칠이면 가르치지만, 손님·배달·돌발 대응은 오래 일해야 익힌다.
// 사장님이 상황 하나씩 골라 평소 말하듯 답하면 그 답이 매뉴얼 카드가 된다.
// 카테고리 이름은 서버 기본값(auth DEFAULT_CATEGORIES)과 같다.
const GROUPS: { category: string; situations: string[] }[] = [
  {
    category: "손님응대",
    situations: [
      "메뉴에 없는 변경을 해 달라고 하면",
      "음료가 이상하다며 다시 만들어 달라고 하면",
      "환불을 해 달라고 하면",
      "단골이 늘 먹던 걸로 달라고 하면",
      "큰 소리로 항의하는 손님이 있으면",
    ],
  },
  {
    category: "배달대응",
    situations: [
      "배달 기사님이 늦거나 안 오면",
      "배달앱 주문이 잘못 들어오면",
      "배달 음료가 쏟아졌다고 연락이 오면",
    ],
  },
  {
    category: "돌발상황",
    situations: [
      "커피 머신이나 기계가 고장 나면",
      "결제기가 안 되면",
      "손님이나 직원이 다치면",
      "정전이나 단수가 되면",
      "사장님께 꼭 바로 연락해야 하는 일은",
    ],
  },
];

export default function ServiceGuidePage() {
  const { state } = useApp();
  const categories = useQuery(productCategoriesQuery(state.token, state.storeId));
  const [picked, setPicked] = useState<{ category: string; situation: string } | null>(null);
  const names = new Set((categories.data?.items ?? []).map((c) => c.name));
  const missing = categories.data ? GROUPS.map((g) => g.category).filter((name) => !names.has(name)) : [];

  return (
    <Screen
      footer={
        picked ? (
          <OwnerAddComposer
            key={`${picked.category}:${picked.situation}`}
            defaultText={`[${picked.category}] ${picked.situation}: `}
            defaultHints={["POLICY"]}
            placeholder="평소 알바생에게 말하듯 적어 주세요"
          />
        ) : undefined
      }
    >
      <BackButton href="/owner" />
      <PageHeader
        title="응대 매뉴얼 만들기"
        description="레시피보다 오래 걸리는 건 손님과 돌발 상황 대응이에요. 상황을 하나 골라 평소처럼 답해 주세요."
      />
      {missing.length > 0 && (
        <>
          <Caption>카테고리에 {missing.join(", ")}이(가) 없어서 기타로 모일 수 있어요.</Caption>
          <ButtonLink href="/owner/categories" variant="secondary">
            카테고리 추가하기
          </ButtonLink>
        </>
      )}
      {GROUPS.map((group) => (
        <ListGroup key={group.category} label={group.category}>
          {group.situations.map((situation) => {
            const active = picked?.category === group.category && picked.situation === situation;
            return (
              <ListRow
                key={situation}
                title={situation}
                subtitle={active ? "아래에 적어 주세요" : undefined}
                onClick={() => setPicked({ category: group.category, situation })}
              />
            );
          })}
        </ListGroup>
      ))}
      <Caption>답이 없는 상황은 알바생이 물어볼 때 사장님께 넘어와요. 그때 답하셔도 매뉴얼로 남아요.</Caption>
    </Screen>
  );
}
