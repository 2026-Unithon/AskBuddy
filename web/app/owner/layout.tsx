"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { OwnerJobMonitor } from "@/components/owner-job-monitor";
import { OwnerBottomNav } from "@/components/owner/owner-bottom-nav";
import { AuthGateState } from "@/components/auth-gate-state";
import { useAuthGuard } from "@/lib/guard";

export default function OwnerLayout({ children }: { children: ReactNode }) {
  const auth = useAuthGuard("OWNER", "/owner/auth");
  const pathname = usePathname();

  if (!auth.ready) {
    return <AuthGateState state={auth.state} onRetry={auth.retry} />;
  }

  // 리브랜딩 화면(/owner, /owner/cards)은 자기 TabBar 를 그린다. 옛 하단 탭은 아직 옮기지 않은 화면에만.
  const showBottomNav = pathname === "/owner/questions";

  return (
    <div className="app-page text-foreground">
      <div className="app-mobile-frame">
        <OwnerJobMonitor />
        {children}
        {showBottomNav && <OwnerBottomNav />}
      </div>
    </div>
  );
}
