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
    <div className="min-h-dvh w-full flex justify-center bg-background text-foreground">
      <div className="w-full max-w-[480px] min-h-dvh bg-background flex flex-col relative">
        {children}
        {showBottomNav && <StaffBottomNav />}
      </div>
    </div>
  );
}
