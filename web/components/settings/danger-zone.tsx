"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "@/components/kit";
import { SettingsLink, SettingsSection } from "@/components/settings/settings-section";
import { TypedConfirm } from "@/components/settings/typed-confirm";
import { apiErrorMessage, leaveStore, withdrawAccount } from "@/lib/api";
import { withdrawalQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

type Kind = "LEAVE" | "WITHDRAW";
const PHRASE: Record<Kind, string> = { LEAVE: "퇴사하겠습니다", WITHDRAW: "탈퇴하겠습니다" };
const ASK: Record<Kind, string> = { LEAVE: "퇴사하시겠습니까?", WITHDRAW: "탈퇴하시겠습니까?" };
const ACTION: Record<Kind, string> = { LEAVE: "퇴사하기", WITHDRAW: "탈퇴하기" };

/**
 * 빨간 칸(계획 8): 퇴사했어요(알바생만), 회원 탈퇴.
 * 'O하시겠습니까?' → 예 → 문구를 그대로 입력 → 서버. 설명은 사실만 적는다(붙잡는 문구 없음).
 */
export function DangerZone({ role }: { role: "OWNER" | "STAFF" }) {
  const owner = role === "OWNER";
  const { state, dispatch } = useApp();
  const client = useQueryClient();
  // 유예 일수는 서버 설정이 단일 출처다(사장님 탈퇴 설명에 쓴다)
  const withdrawal = useQuery({ ...withdrawalQuery(state.token, state.userId), enabled: owner && Boolean(state.token && state.userId) });
  // 어느 단계인지(화면 상태)
  const [step, setStep] = useState<{ kind: Kind; stage: "ask" | "type" } | null>(null);

  const run = useMutation({
    mutationFn: ({ kind, typed }: { kind: Kind; typed: string }) =>
      kind === "LEAVE" ? leaveStore(typed, state.token!) : withdrawAccount(typed, state.token!),
    // 서버가 이 기기 세션까지 끊었다. 남은 화면 상태를 지우고 첫 화면으로
    onSuccess: () => {
      client.clear();
      dispatch({ type: "LOGOUT" });
      window.location.replace("/");
    },
  });

  const days = withdrawal.data?.grace_days;
  const describe = (kind: Kind) => {
    if (kind === "LEAVE") return "이 매장에서 나가요. 계정은 남아 다른 매장에 합류할 수 있어요.";
    if (!owner) return "계정과 이름이 지워지고 이 매장에서 나가요. 질문 기록은 이름 없이 남아요.";
    return `${days}일 뒤 매장과 계정이 지워져요. 그동안 알바생도 매장에 들어올 수 없어요. ${days}일 안에 다시 로그인하면 취소할 수 있어요.`;
  };
  const open = (kind: Kind) => {
    run.reset();
    setStep({ kind, stage: "ask" });
  };

  return (
    <>
      <SettingsSection tone="danger">
        {!owner && <SettingsLink title="퇴사했어요" danger onClick={() => open("LEAVE")} />}
        {/* 사장님 설명에 유예 일수가 들어가므로 그 값을 받기 전에는 누를 수 없다 */}
        <SettingsLink title="회원 탈퇴" danger onClick={() => open("WITHDRAW")} disabled={owner && days === undefined} />
      </SettingsSection>
      {step?.stage === "ask" && (
        <ConfirmDialog
          open
          title={ASK[step.kind]}
          description={describe(step.kind)}
          confirmLabel="예"
          cancelLabel="아니요"
          tone="danger"
          onConfirm={() => setStep({ kind: step.kind, stage: "type" })}
          onCancel={() => setStep(null)}
        />
      )}
      {step?.stage === "type" && (
        <TypedConfirm
          title={ACTION[step.kind]}
          phrase={PHRASE[step.kind]}
          loading={run.isPending}
          error={run.error ? apiErrorMessage(run.error, "처리하지 못했어요. 다시 눌러 주세요.") : null}
          onSubmit={(typed) => run.mutate({ kind: step.kind, typed })}
          onClose={() => setStep(null)}
        />
      )}
    </>
  );
}
