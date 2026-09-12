"use client";

import type { ReactNode } from "react";
import { OwnerJobMonitor } from "@/components/owner-job-monitor";
import { useAuthGuard } from "@/lib/guard";

export default function OwnerLayout({ children }: { children: ReactNode }) {
  const { ready } = useAuthGuard("OWNER", "/owner/auth");
  if (!ready) return null;
  return (
    <>
      <OwnerJobMonitor />
      {children}
    </>
  );
}
