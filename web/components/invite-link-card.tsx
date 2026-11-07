"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, ConfirmDialog, ErrorInline, Icon, Skeleton, Surface, TextButton, useFeedback } from "@/components/kit";
import { apiErrorMessage, rotateInviteLink } from "@/lib/api";
import { shareInviteViaKakao } from "@/lib/kakao-share";
import { bootstrapQuery, inviteLinkQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

/** 카카오 말풍선 마크(카톡 버튼 전용). */
function KakaoMark() {
  return (
    <svg data-kakao-mark="" aria-hidden width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 3C6.48 3 2 6.58 2 11c0 2.86 1.88 5.37 4.7 6.78l-.98 3.6c-.09.33.28.6.57.41l4.3-2.85c.46.04.93.06 1.41.06 5.52 0 10-3.58 10-8S17.52 3 12 3z" />
    </svg>
  );
}

// 링크는 내부 토큰을 담고 있다. 화면에는 링크 자체를 보여 주지 않고 복사·공유만 한다(o15a)
export function InviteLinkCard() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const feedback = useFeedback();
  const link = useQuery(inviteLinkQuery(state.token, state.storeId));
  // 가드가 이미 불러 둔 bootstrap 캐시에서 매장명을 읽는다(추가 요청 없음)
  const storeName = useQuery(bootstrapQuery(state.token, state.userId, state.storeId)).data?.store?.store_name;
  const [confirming, setConfirming] = useState(false);
  const rotate = useMutation({
    mutationFn: () => rotateInviteLink(state.token!),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.inviteLink(state.storeId), data);
      setConfirming(false);
      feedback.toast("새 링크를 만들었어요");
    },
  });

  async function copy() {
    if (!link.data) return;
    try {
      await navigator.clipboard.writeText(link.data.url);
      feedback.toast("링크를 복사했어요");
    } catch {
      feedback.toast("복사하지 못했어요. 카톡으로 보내 주세요.");
    }
  }

  async function share() {
    if (!link.data) return;
    // 1) 카카오 카드 메시지 2) 휴대폰 공유창 3) 복사
    if (await shareInviteViaKakao({ url: link.data.url, storeName: storeName ?? "우리 매장" })) return;
    if (navigator.share) {
      try {
        await navigator.share({ title: "AskBuddy 합류 초대", text: "매장 합류 링크예요.", url: link.data.url });
        return;
      } catch {
        // 사용자가 공유 창을 닫았다
        return;
      }
    }
    await copy();
  }

  return (
    <Surface as="section" className="flex flex-col gap-3 p-5">
      <h2 className="text-[16px] font-bold text-ink">초대 링크</h2>
      {link.isPending && <Skeleton className="h-28" />}
      {link.isError && (
        <ErrorInline message={apiErrorMessage(link.error, "링크를 불러오지 못했어요.")} onRetry={() => void link.refetch()} retrying={link.isRefetching} />
      )}
      {link.data && (
        <div className="flex flex-col gap-2">
          <Button variant="kakao" onClick={() => void share()}>
            <KakaoMark />
            카톡으로 보내기
          </Button>
          <Button variant="secondary" onClick={() => void copy()}>
            <Icon name="clip" size={18} />
            링크 복사
          </Button>
        </div>
      )}
      <TextButton className="self-center" onClick={() => setConfirming(true)} disabled={!link.data}>
        링크 새로 만들기
      </TextButton>
      <ConfirmDialog
        open={confirming}
        title="새 링크를 만들까요?"
        description="지금 링크로는 더 이상 가입할 수 없어요."
        confirmLabel="새로 만들기"
        loading={rotate.isPending}
        error={rotate.error ? apiErrorMessage(rotate.error, "새 링크를 만들지 못했어요.") : null}
        onConfirm={() => rotate.mutate()}
        onCancel={() => {
          rotate.reset();
          setConfirming(false);
        }}
      />
    </Surface>
  );
}
