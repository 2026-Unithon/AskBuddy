"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useAuthGuard } from "@/lib/guard";
import { StaffBottomNav } from "@/components/staff-nav";

export default function StaffLayout({ children }: { children: ReactNode }) {
  const { ready } = useAuthGuard("STAFF", "/staff/auth");
  const pathname = usePathname();

  if (!ready) return null;

  // Figma의 게임형 로드맵은 화면 전체를 쓰고 자체 미션 CTA를 제공한다.
  const showBottomNav = pathname === "/staff/chat" || pathname === "/staff/faqs";

  return (
    <div className="min-h-dvh w-full flex justify-center bg-background text-foreground">
      <div className="w-full max-w-[480px] min-h-dvh bg-background flex flex-col relative">
        {children}
        {showBottomNav && <StaffBottomNav />}
      </div>
    </div>
  );
}
