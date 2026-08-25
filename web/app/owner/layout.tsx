"use client";

import type { ReactNode } from "react";
import { useAuthGuard } from "@/lib/guard";

export default function OwnerLayout({ children }: { children: ReactNode }) {
  const { ready } = useAuthGuard("OWNER", "/owner/auth");
  if (!ready) return null;
  return <>{children}</>;
}
