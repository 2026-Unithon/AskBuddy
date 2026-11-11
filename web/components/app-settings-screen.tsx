"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { BackButton, ConfirmDialog, ErrorInline, PageHeader, Screen, useFeedback } from "@/components/kit";
import { DangerZone } from "@/components/settings/danger-zone";
import { PushToggleRow } from "@/components/settings/push-toggle-row";
import { SettingsLink, SettingsSection } from "@/components/settings/settings-section";
import { apiErrorMessage, downloadKnowledge, logoutSession } from "@/lib/api";
import { useApp } from "@/lib/store";

/** 파일 이름의 날짜는 한국 날짜(KST 변환은 프론트에서만) */
function kstStamp(now: Date) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  return parts.replaceAll("-", "");
}

/** 설정(계획 8). 알림 설정, 개인정보 보호, 계정, 그리고 빨간 칸(퇴사, 탈퇴). */
export function AppSettingsScreen({ role }: { role: "OWNER" | "STAFF" }) {
  const owner = role === "OWNER";
  const base = owner ? "/owner" : "/staff";
  const { state } = useApp();
  const { toast } = useFeedback();
  // 확인 창 열림(화면 상태)
  const [confirmingLogout, setConfirmingLogout] = useState(false);

  // 서버의 세션을 먼저 폐기한다. 실패하면 이 화면에서 다시 누른다
  const logout = useMutation({
    mutationFn: logoutSession,
    onSuccess: () => window.location.replace("/"),
  });

  // 받은 JSON 을 파일로 저장한다. 서버 상태를 바꾸지 않으므로 무효화할 query 가 없다
  const download = useMutation({
    mutationFn: () => downloadKnowledge(state.token!),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `askbuddy-knowledge-${kstStamp(new Date())}.json`;
      link.click();
      URL.revokeObjectURL(url);
    },
    onError: (error) => toast(`매장 지식을 내려받지 못했어요. ${apiErrorMessage(error, "잠시 뒤 다시 눌러 주세요.")}`),
  });

  return (
    <Screen>
      <BackButton parent={`${base}/settings`} />
      <PageHeader title="설정" />
      <div className="flex flex-col gap-8">
        <SettingsSection title="알림 설정">
          <PushToggleRow role={role} />
        </SettingsSection>

        <SettingsSection title="개인정보 보호">
          {owner && (
            <SettingsLink title="매장 지식 내려받기" onClick={() => download.mutate()} disabled={download.isPending || !state.token} />
          )}
          {owner && <SettingsLink title="올린 자료 관리" href="/owner/settings/app/sources" />}
          <SettingsLink title="로그인된 기기" href={`${base}/settings/app/devices`} />
          <SettingsLink title="개인정보 처리방침" href="/privacy" />
          <SettingsLink title="이용약관" href="/terms" />
        </SettingsSection>

        <SettingsSection title="계정">
          {/* 지금 로그인은 카카오 하나다(이메일 로그인 계정은 없다) */}
          <SettingsLink title="로그인 방식" value="카카오" />
          {owner && <SettingsLink title="초대 링크 만들기" href="/owner/invite" />}
          <SettingsLink title="앱 버전" value={`v${process.env.NEXT_PUBLIC_APP_VERSION}`} />
          <SettingsLink title="로그아웃" onClick={() => setConfirmingLogout(true)} disabled={logout.isPending} />
        </SettingsSection>
        {logout.error && (
          <ErrorInline
            message={apiErrorMessage(logout.error, "로그아웃하지 못했어요.")}
            onRetry={() => logout.mutate()}
            retrying={logout.isPending}
          />
        )}

        <DangerZone role={role} />
      </div>

      {/* 확인 창은 열 때만 그린다(닫힌 창의 제목이 화면 구역 제목에 섞이지 않게) */}
      {confirmingLogout && (
        <ConfirmDialog
          open
          title="로그아웃할까요?"
          confirmLabel="로그아웃"
          tone="danger"
          loading={logout.isPending}
          onConfirm={() => {
            setConfirmingLogout(false);
            logout.mutate();
          }}
          onCancel={() => setConfirmingLogout(false)}
        />
      )}
    </Screen>
  );
}
