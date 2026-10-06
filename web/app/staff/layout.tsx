"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useAuthGuard } from "@/lib/guard";
import { StaffBottomNav } from "@/components/staff-nav";
import { AuthGateState } from "@/components/auth-gate-state";

export default function StaffLayout({ children }: { children: ReactNode }) {
  const auth = useAuthGuard("STAFF", "/staff/auth");
  const pathname = usePathname();

  if (!auth.ready) {
    return <AuthGateState state={auth.state} onRetry={auth.retry} />;
  }

  // 리브랜딩 화면(/staff/recipes 등)은 자기 TabBar 를 그린다. 옛 하단 탭은 아직 옮기지 않은 화면에만.
  const showBottomNav = pathname === "/staff/chat" || pathname === "/staff/faqs";

  return (
    <div className="app-page text-foreground">
      <div className="app-mobile-frame">
        {children}
        {showBottomNav && <StaffBottomNav />}
      </div>
    </div>
  );
}
