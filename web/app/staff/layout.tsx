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

  const showBottomNav =
    pathname === "/staff/roadmap" ||
    pathname === "/staff/chat" ||
    pathname === "/staff/faqs";

  return (
    <div className="app-page text-foreground">
      <div className="app-mobile-frame">
        {children}
        {showBottomNav && <StaffBottomNav />}
      </div>
    </div>
  );
}
