import Link from "next/link";
import { Shell, TopBar } from "@/components/ui";

export default function OwnerIntentPage() {
  return (
    <Shell>
      <TopBar />
      <div className="flex-1 flex flex-col px-6 pt-2 pb-10 gap-8">
        <div className="space-y-1">
          <h1 className="text-xl font-bold">무엇을 하러 오셨어요?</h1>
          <p className="text-sm text-muted">언제든 다시 돌아올 수 있어요.</p>
        </div>

        <div className="flex flex-col gap-4">
          <Link
            href="/owner/category"
            className="group rounded-[var(--radius-lg)] bg-brand-600 text-white p-6 flex items-center gap-4 hover:bg-brand-700 transition-colors"
          >
            <div className="w-14 h-14 rounded-2xl bg-white/15 flex items-center justify-center text-2xl">
              📋
            </div>
            <div className="flex-1">
              <p className="font-semibold">인수인계 하러 왔어요</p>
              <p className="text-xs text-white/80 mt-0.5">업무 자료를 올려서 Buddy를 가르쳐요</p>
            </div>
            <span className="group-hover:translate-x-0.5 transition-transform">→</span>
          </Link>

          <Link
            href="/owner/dashboard"
            className="group rounded-[var(--radius-lg)] border border-border bg-surface p-6 flex items-center gap-4 hover:border-brand-300 hover:bg-brand-50/40 transition-colors"
          >
            <div className="w-14 h-14 rounded-2xl bg-brand-100 text-brand-700 flex items-center justify-center text-2xl">
              📊
            </div>
            <div className="flex-1">
              <p className="font-semibold text-foreground">대시보드 보러 왔어요</p>
              <p className="text-xs text-muted mt-0.5">직원 진행 상황과 대기 질문을 확인해요</p>
            </div>
            <span className="text-muted group-hover:translate-x-0.5 transition-transform">→</span>
          </Link>
        </div>
      </div>
    </Shell>
  );
}
