"use client";

import type { ReactNode } from "react";
import { useAuthGuard } from "@/lib/guard";

export default function StaffLayout({ children }: { children: ReactNode }) {
  const { ready } = useAuthGuard("STAFF", "/staff/auth");
  if (!ready) return null;
  return <>{children}</>;
}
