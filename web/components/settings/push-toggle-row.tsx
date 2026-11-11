"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ErrorInline, Sheet, Switch, focusRing } from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import { readPushEnv, turnPushOff, turnPushOn } from "@/lib/push";
import { pushState, type PushEnv } from "@/lib/push-state";
import { pushKeyQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

type BrowserEnv = Omit<PushEnv, "configured">;

const HELP = {
  IOS_NEEDS_HOME: {
    message: "홈 화면에 추가해야 받을 수 있어요",
    button: "추가하는 법",
    title: "홈 화면에 추가하기",
    steps: ["Safari 아래 공유 버튼을 눌러요.", "홈 화면에 추가를 골라요.", "홈 화면의 AskBuddy로 열고 여기서 켜요."],
  },
  DENIED: {
    message: "휴대폰 설정에서 알림이 꺼져 있어요",
    button: "켜는 법",
    title: "알림 켜는 법",
    steps: ["아이폰은 설정 > 알림 > AskBuddy 에서 켜요.", "안드로이드는 Chrome 주소창 왼쪽 자물쇠 > 권한 > 알림 에서 켜요."],
  },
} as const;

/** 설정의 '이 기기 푸시 알림 받기' 한 줄(계획 8). 폰이 막고 있으면 이유와 켜는 법을 토글 아래 한 줄로 */
export function PushToggleRow({ role }: { role: "OWNER" | "STAFF" }) {
  const { state } = useApp();
  const client = useQueryClient();
  const key = useQuery(pushKeyQuery(state.token, state.storeId, state.userId));
  // 브라우저 권한, 구독은 서버 데이터가 아니라 이 기기의 상태다
  const [env, setEnv] = useState<BrowserEnv | null>(null);
  const [envError, setEnvError] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    readPushEnv()
      .then((next) => !cancelled && setEnv(next))
      .catch(() => !cancelled && setEnvError(true));
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = useMutation({
    mutationFn: async (next: boolean) => {
      if (next) await turnPushOn(role, state.token!);
      else await turnPushOff(role, state.token!);
      return readPushEnv();
    },
    onSuccess: (next) => {
      setEnv(next);
      // 사장님 알림 화면의 구독 상태도 서버 값으로 맞춘다
      void client.invalidateQueries({ queryKey: queryKeys.notificationSupport(state.storeId) });
    },
  });

  const status = env ? pushState({ ...env, configured: Boolean(key.data?.push_configured && key.data.vapid_public_key) }) : null;
  const help = status === "IOS_NEEDS_HOME" || status === "DENIED" ? HELP[status] : null;
  const usable = status === "ON" || status === "OFF";

  return (
    <li className="flex flex-col gap-1 py-1">
      <Switch
        label="이 기기 푸시 알림 받기"
        checked={status === "ON"}
        disabled={!usable || toggle.isPending || !state.token}
        onChange={(next) => toggle.mutate(next)}
      />
      {help && (
        <p className="flex flex-wrap items-center gap-x-2 pb-2 text-[14px] text-ink [word-break:keep-all]">
          <span>{help.message}</span>
          <button type="button" onClick={() => setHelpOpen(true)} className={`min-h-11 font-bold text-primary underline ${focusRing}`}>
            {help.button}
          </button>
        </p>
      )}
      {status === "UNSUPPORTED" && <p className="pb-2 text-[14px] text-ink">이 브라우저는 알림을 받을 수 없어요</p>}
      {key.error && (
        <ErrorInline message={apiErrorMessage(key.error, "알림 설정을 불러오지 못했어요.")} onRetry={() => void key.refetch()} retrying={key.isRefetching} />
      )}
      {envError && <ErrorInline message="이 기기의 알림 상태를 확인하지 못했어요." />}
      {toggle.error && <ErrorInline message={apiErrorMessage(toggle.error, "알림 설정을 바꾸지 못했어요. 다시 눌러 주세요.")} />}
      {help && (
        <Sheet open={helpOpen} onClose={() => setHelpOpen(false)} title={help.title}>
          <ol className="flex list-decimal flex-col gap-2 pb-2 pl-5 text-[16px] leading-[1.5] text-ink [word-break:keep-all]">
            {help.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </Sheet>
      )}
    </li>
  );
}
