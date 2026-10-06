"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, ButtonLink, Caption, ErrorInline, PageHeader, Screen, focusRing } from "@/components/kit";
import { apiErrorMessage, createStore } from "@/lib/api";
import { bootstrapQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

// O2 매장 이름만. 업종은 지금 카페만 구현돼 있어 CAFE 로 만들고, 카테고리는 서버 기본 세트로 시작한다 (계획 §2-2).
// 주소가 /owner/intent 인 이유: 서버 기본 목적지와 인증 가드가 "매장 없는 점주"를 이 주소로 보낸다.
export default function OwnerStoreNamePage() {
  const router = useRouter();
  const { state, dispatch } = useApp();
  const bootstrap = useQuery(bootstrapQuery(state.token, state.userId, state.storeId));
  const [storeName, setStoreName] = useState("");

  const create = useMutation({
    mutationFn: () => createStore({ storeName: storeName.trim(), businessType: "CAFE" }, state.token!),
    onSuccess: (result) => {
      // 매장 생성 응답의 새 토큰에만 store_id 가 들어 있다 — 옛 토큰을 버린다
      dispatch({ type: "SET_STORE", token: result.token, storeId: result.store.store_id });
      router.push("/owner/add");
    },
  });

  const ready = storeName.trim().length > 0 && !create.isPending && Boolean(state.token);

  // 이미 매장이 있는 점주는 다시 만들지 않는다. 자동으로 보내지 않는 이유: 매장을 만든 직후 토큰이 바뀌면
  // 레이아웃 가드가 이 화면을 다시 올리는데, 그때 자동 이동이 /owner/add 이동을 덮어쓴다.
  if (bootstrap.data?.store && create.isIdle) {
    return (
      <Screen footer={<ButtonLink href="/owner">오늘 매장으로</ButtonLink>}>
        <PageHeader title="이미 매장이 있어요" description={bootstrap.data.store.store_name} />
      </Screen>
    );
  }

  return (
    <Screen
      footer={
        <>
          {create.error && (
            <ErrorInline
              message={apiErrorMessage(create.error, "매장을 만들지 못했어요. 입력한 이름은 그대로 두었어요.")}
              onRetry={() => create.mutate()}
              retrying={create.isPending}
            />
          )}
          <Button loading={create.isPending} disabled={!ready} onClick={() => create.mutate()}>
            다음
          </Button>
        </>
      }
    >
      <PageHeader title="매장 이름만 알려주세요" />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) create.mutate();
        }}
      >
        <input
          aria-label="매장 이름"
          value={storeName}
          onChange={(event) => setStoreName(event.target.value)}
          maxLength={100}
          placeholder="예) 우리동네 카페 본점"
          autoComplete="organization"
          className={`min-h-[60px] w-full rounded-[20px] bg-surface px-[18px] text-[18px] font-medium tracking-[-0.36px] text-ink shadow-card placeholder:font-normal placeholder:text-ink-muted ${focusRing}`}
        />
      </form>
      <Caption className="text-[13px]">업종·메뉴는 넣어주시는 걸 보고 알아서 정리해요</Caption>
    </Screen>
  );
}
