"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui";
import { apiErrorMessage, rotateInviteLink } from "@/lib/api";
import { shareInviteViaKakao } from "@/lib/kakao-share";
import { bootstrapQuery, inviteLinkQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

// 링크는 내부 토큰을 담고 있다. 화면에는 링크 자체를 보여 주지 않고 복사·공유만 한다
export function InviteLinkCard() {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const link = useQuery(inviteLinkQuery(state.token, state.storeId));
  // 가드가 이미 불러 둔 bootstrap 캐시에서 매장명을 읽는다(추가 요청 없음)
  const storeName = useQuery(bootstrapQuery(state.token, state.userId, state.storeId)).data?.store?.store_name;
  const [notice, setNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const rotate = useMutation({
    mutationFn: () => rotateInviteLink(state.token!),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.inviteLink(state.storeId), data);
      setConfirming(false);
      setNotice("새 링크를 만들었어요. 이전 링크는 더 이상 쓸 수 없어요.");
    },
  });

  async function copy() {
    if (!link.data) return;
    try {
      await navigator.clipboard.writeText(link.data.url);
      setNotice("링크를 복사했어요.");
    } catch {
      setNotice("복사하지 못했어요. 공유 버튼을 써 주세요.");
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
    <section className="rounded-2xl bg-surface p-4 shadow-sm">
      <h2 className="text-sm font-bold text-foreground">초대 링크</h2>
      <p className="mt-1 text-xs text-muted">알바생에게 보내 주세요. 가입하면 여기서 승인할 수 있어요.</p>
      {link.isPending && <p role="status" className="mt-3 text-xs text-muted">링크를 준비하고 있어요…</p>}
      {link.isError && (
        <div className="mt-3 flex items-center gap-2">
          <p role="alert" className="text-xs text-danger-500">{apiErrorMessage(link.error, "링크를 불러오지 못했어요.")}</p>
          <Button onClick={() => void link.refetch()}>다시 시도</Button>
        </div>
      )}
      {link.data && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Button onClick={() => void copy()}>링크 복사</Button>
          <Button onClick={() => void share()}>카톡으로 보내기</Button>
        </div>
      )}
      <p className="mt-2 min-h-4 text-xs text-muted" role="status" aria-live="polite">{notice}</p>
      {!confirming ? (
        <button type="button" className="text-xs font-bold text-muted underline" onClick={() => setConfirming(true)} disabled={!link.data}>
          링크 새로 만들기
        </button>
      ) : (
        <div className="mt-1 rounded-xl bg-surface-muted p-3 text-xs">
          <p>새로 만들면 지금 링크로는 더 이상 가입할 수 없어요. 이미 들어온 요청은 그대로 남아요.</p>
          <div className="mt-2 flex gap-2">
            <Button loading={rotate.isPending} loadingLabel="만드는 중" onClick={() => rotate.mutate()}>새로 만들기</Button>
            <Button onClick={() => setConfirming(false)}>취소</Button>
          </div>
          {rotate.error && <p role="alert" className="mt-1 text-danger-500">{apiErrorMessage(rotate.error, "새 링크를 만들지 못했어요.")}</p>}
        </div>
      )}
    </section>
  );
}
