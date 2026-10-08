"use client";

import { useQuery } from "@tanstack/react-query";
import { BackButton, ErrorInline, ListGroup, ListRow, PageHeader, Screen, Skeleton, TextButton } from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
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
          { title: "직원 담당", subtitle: "직원마다 근무조 정하기", href: "/owner/members" },
          { title: "카테고리", subtitle: "카드를 나누는 묶음", href: "/owner/categories" },
          { title: "알림", subtitle: "질문이 오면 바로 알려드려요", href: "/owner/notifications" },
        ]
      : [
          { title: "내 계정", subtitle: user?.name },
          { title: "내 기록", subtitle: "내가 한 일 · 기록 남기기", href: `/${role.toLowerCase()}/me` },
          { title: "매장", subtitle: store?.store_name },
          { title: "답변 알림", subtitle: "사장님 답이 오면 알려드려요", href: "/staff/notifications/v2" },
        ];

  // 상태를 바꿔 다시 그리면 인증 가드가 먼저 "/로그인?next=설정"으로 보낸다.
  // 저장된 로그인 정보를 바로 지우고 처음 화면을 새로 연다 — 메모리의 쿼리 캐시도 함께 사라진다.
  const logout = () => {
    try {
      window.localStorage.removeItem("askbuddy_state");
    } catch {
      // 저장소를 못 써도 새로 열면 메모리 상태는 사라진다
    }
    window.location.replace("/");
  };

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
        <TextButton onClick={logout}>로그아웃</TextButton>
      </div>
    </Screen>
  );
}
