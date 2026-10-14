"use client";

import type { ReactNode } from "react";
import { OwnerJobMonitor } from "@/components/owner-job-monitor";
import { AuthGateState } from "@/components/auth-gate-state";
import { useAuthGuard } from "@/lib/guard";

export default function OwnerLayout({ children }: { children: ReactNode }) {
  const auth = useAuthGuard("OWNER", "/owner/auth");

  if (!auth.ready) {
    return <AuthGateState state={auth.state} onRetry={auth.retry} />;
  }

  return (
    <div className="app-page text-foreground">
      <div className="app-mobile-frame">
        <OwnerJobMonitor />
        {children}
      </div>
    </div>
  );
}
