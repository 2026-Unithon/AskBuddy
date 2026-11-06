"use client";

import type { ReactNode } from "react";
import { useAuthGuard } from "@/lib/guard";
import { AuthGateState } from "@/components/auth-gate-state";

export default function StaffLayout({ children }: { children: ReactNode }) {
  const auth = useAuthGuard("STAFF", "/staff/auth");

  if (!auth.ready) {
    return <AuthGateState state={auth.state} onRetry={auth.retry} />;
  }

  return (
    <div className="app-page text-foreground">
      <div className="app-mobile-frame">
        {children}
      </div>
    </div>
  );
}
