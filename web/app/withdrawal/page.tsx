"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, ErrorInline, PageHeader, Screen, Skeleton, TextButton } from "@/components/kit";
import { apiErrorMessage, cancelWithdrawal, logoutSession } from "@/lib/api";
import { queryKeys, withdrawalQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

/** 날짜는 한국 날짜로 보인다(KST 변환은 프론트에서만) */
function kstDate(iso: string) {
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "long", day: "numeric" }).format(new Date(iso));
}

/** 사장님 탈퇴 대기 안내와 취소(계획 8). 기한 안에 다시 로그인한 사장님이 매장 화면보다 먼저 본다 */
export default function WithdrawalPage() {
  const router = useRouter();
  const client = useQueryClient();
  const { state, dispatch } = useApp();
  const withdrawal = useQuery(withdrawalQuery(state.token, state.userId));

  // 로그인이 없으면 첫 화면에서 로그인한 뒤 여기로 돌아온다
  useEffect(() => {
    if (state.hydrated && !state.token) router.replace(`/?next=${encodeURIComponent("/withdrawal")}`);
  }, [state.hydrated, state.token, router]);

  const cancel = useMutation({
    mutationFn: () => cancelWithdrawal(state.token!),
    onSuccess: () => {
      // 시작 화면 캐시에 남은 '탈퇴 대기'가 다시 이 화면으로 보내지 않게 지우고 새로 받는다
      client.removeQueries({ queryKey: queryKeys.bootstrap(state.userId, state.storeId) });
      void client.invalidateQueries({ queryKey: queryKeys.withdrawal(state.userId) });
      router.replace("/owner");
    },
  });
  const logout = useMutation({
    mutationFn: logoutSession,
    onSuccess: () => {
      client.clear();
      dispatch({ type: "LOGOUT" });
      window.location.replace("/");
    },
  });

  const due = withdrawal.data?.due_at;
  return (
    <div className="app-page text-foreground">
      <div className="app-mobile-frame">
        <Screen>
          <PageHeader title="탈퇴 대기 중이에요" />
          {(withdrawal.isLoading || !state.hydrated) && <Skeleton className="h-32" />}
          {withdrawal.error && (
            <ErrorInline
              message={apiErrorMessage(withdrawal.error, "탈퇴 상태를 불러오지 못했어요.")}
              onRetry={() => void withdrawal.refetch()}
              retrying={withdrawal.isRefetching}
            />
          )}
          {withdrawal.data && due && (
            <>
              <p className="text-[16px] leading-[1.6] text-ink [word-break:keep-all]">
                <strong>{kstDate(due)}</strong>에 매장과 계정이 지워져요. 지금 취소하면 매장이 다시 열려요.
              </p>
              {cancel.error && <ErrorInline message={apiErrorMessage(cancel.error, "취소하지 못했어요. 다시 눌러 주세요.")} />}
              <Button loading={cancel.isPending} onClick={() => cancel.mutate()}>
                탈퇴 취소하기
              </Button>
            </>
          )}
          {withdrawal.data && !due && (
            <p className="text-[16px] leading-[1.6] text-ink [word-break:keep-all]">탈퇴 대기 중인 매장이 없어요.</p>
          )}
          {state.token && (
            <TextButton disabled={logout.isPending} onClick={() => logout.mutate()}>
              로그아웃
            </TextButton>
          )}
        </Screen>
      </div>
    </div>
  );
}
