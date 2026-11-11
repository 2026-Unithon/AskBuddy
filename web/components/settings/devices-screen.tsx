"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BackButton, Chip, ConfirmDialog, Empty, ErrorInline, PageHeader, Screen, Skeleton, focusRing } from "@/components/kit";
import { apiErrorMessage, revokeDevice, type DeviceSession } from "@/lib/api";
import { devicesQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

/** 로그인된 기기(계획 8 Task 8). 이 기기는 설정의 로그아웃을 쓰고, 다른 기기는 여기서 끊는다 */
export function DevicesScreen({ role }: { role: "OWNER" | "STAFF" }) {
  const { state } = useApp();
  const client = useQueryClient();
  const devices = useQuery(devicesQuery(state.token, state.userId));
  // 끊을지 묻는 기기(화면 상태)
  const [asking, setAsking] = useState<DeviceSession | null>(null);

  const revoke = useMutation({
    mutationFn: (familyId: string) => revokeDevice(familyId, state.token!),
    onSuccess: () => {
      setAsking(null);
      void client.invalidateQueries({ queryKey: queryKeys.devices(state.userId) });
    },
  });

  return (
    <Screen>
      <BackButton parent={role === "OWNER" ? "/owner/settings/app" : "/staff/settings/app"} />
      <PageHeader title="로그인된 기기" />
      {devices.isLoading && <Skeleton className="h-32" />}
      {devices.error && (
        <ErrorInline
          message={apiErrorMessage(devices.error, "기기 목록을 불러오지 못했어요.")}
          onRetry={() => void devices.refetch()}
          retrying={devices.isRefetching}
        />
      )}
      {devices.data && devices.data.length === 0 && <Empty title="로그인된 기기가 없어요" description="다시 로그인하면 여기에 보여요." />}
      {devices.data && devices.data.length > 0 && (
        <ul className="flex flex-col divide-y divide-empty">
          {devices.data.map((device) => (
            <li key={device.family_id} className="flex min-h-14 items-center gap-3 py-2">
              <span className="min-w-0 flex-1 truncate text-[16px] font-bold text-ink">{device.label}</span>
              {device.current ? (
                <Chip size="sm">이 기기</Chip>
              ) : (
                <button
                  type="button"
                  aria-label={`${device.label} 로그아웃`}
                  onClick={() => {
                    revoke.reset();
                    setAsking(device);
                  }}
                  className={`min-h-11 shrink-0 rounded-full px-3 text-[14px] font-bold text-danger-700 ${focusRing}`}
                >
                  로그아웃
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {asking && (
        <ConfirmDialog
          open
          title="이 기기에서 로그아웃할까요?"
          confirmLabel="로그아웃"
          tone="danger"
          loading={revoke.isPending}
          error={revoke.error ? apiErrorMessage(revoke.error, "로그아웃하지 못했어요. 다시 눌러 주세요.") : null}
          onConfirm={() => revoke.mutate(asking.family_id)}
          onCancel={() => setAsking(null)}
        />
      )}
    </Screen>
  );
}
