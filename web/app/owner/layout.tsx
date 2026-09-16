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
    pathname === "/owner/questions" ||
    pathname === "/owner/cards";

  return (
    <div className="min-h-dvh w-full flex justify-center bg-background text-foreground">
      <div className="w-full max-w-[480px] min-h-dvh bg-background flex flex-col relative">
        <OwnerJobMonitor />
        {children}
        {showBottomNav && <OwnerBottomNav />}
      </div>
    </div>
  );
}
