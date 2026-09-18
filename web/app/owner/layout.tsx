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

  const showBottomNav =
    pathname === "/owner/upload" ||
    pathname === "/owner/questions" || pathname === "/owner/questions/v2" ||
    pathname === "/owner/cards";

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
