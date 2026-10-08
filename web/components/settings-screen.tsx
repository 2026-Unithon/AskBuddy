"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { BackButton, ErrorInline, ListGroup, ListRow, PageHeader, Screen, Skeleton, TextButton } from "@/components/kit";
import { apiErrorMessage, logoutSession } from "@/lib/api";
import { bootstrapQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

type Row = { title: string; subtitle?: string; href?: string };

/** S1 설정. 점주·직원 공용. 기능이 없는 항목(언어 등)은 넣지 않는다. */
export function SettingsScreen({ role }: { role: "OWNER" | "STAFF" }) {
  const { state } = useApp();
  const bootstrap = useQuery(bootstrapQuery(state.token, state.userId, state.storeId));
  const user = bootstrap.data?.user;
  const store = bootstrap.data?.store;

  const rows: Row[] =
    role === "OWNER"
      ? [
          { title: "내 계정", subtitle: user?.name },
          { title: "내 기록", subtitle: "내가 한 일 · 기록 남기기", href: `/${role.toLowerCase()}/me` },
          { title: "매장", subtitle: store?.store_name },
          { title: "근무조 · 알바생 기록", subtitle: "할 일 담기 · 영업일 시각 · 기록 조회", href: "/owner/shifts" },
          { title: "직원 관리", subtitle: "초대 · 합류 승인 · 담당 근무조", href: "/owner/members" },
          { title: "카테고리", subtitle: "카드를 나누는 묶음", href: "/owner/categories" },
          { title: "알림", subtitle: "질문이 오면 바로 알려드려요", href: "/owner/notifications" },
        ]
      : [
          { title: "내 계정", subtitle: user?.name },
          { title: "내 기록", subtitle: "내가 한 일 · 기록 남기기", href: `/${role.toLowerCase()}/me` },
          { title: "매장", subtitle: store?.store_name },
          { title: "답변 알림", subtitle: "사장님 답이 오면 알려드려요", href: "/staff/notifications/v2" },
        ];

  // 서버의 세션을 먼저 폐기한다. 실패하면 설정 화면에서 재시도한다.
  const logout = useMutation({
    mutationFn: logoutSession,
    onSuccess: () => window.location.replace("/"),
  });

  return (
    <Screen>
      <BackButton href={role === "OWNER" ? "/owner" : "/staff"} />
      <PageHeader title="설정" />
      {bootstrap.isLoading && <Skeleton className="h-60" />}
      {bootstrap.error && (
        <ErrorInline message={apiErrorMessage(bootstrap.error, "계정 정보를 불러오지 못했어요.")} onRetry={() => void bootstrap.refetch()} retrying={bootstrap.isRefetching} />
      )}
      {bootstrap.data && (
        <ListGroup>
          {rows.map((row) => (
            <ListRow key={row.title} title={row.title} subtitle={row.subtitle} href={row.href} />
          ))}
        </ListGroup>
      )}
      <div className="mt-auto pt-6">
        {logout.error && <ErrorInline message={apiErrorMessage(logout.error, "로그아웃하지 못했어요.")} onRetry={() => logout.mutate()} retrying={logout.isPending} />}
        <TextButton disabled={logout.isPending} onClick={() => logout.mutate()}>로그아웃</TextButton>
      </div>
    </Screen>
  );
}
