import Link from "next/link";
import { Shell, TopBar } from "@/components/ui";

export default function RoleSelectPage() {
  return (
    <Shell>
      <TopBar />
      <div className="flex-1 flex flex-col px-6 pt-2 pb-10 gap-8">
        <div className="space-y-1">
          <h1 className="text-xl font-bold">누구신가요?</h1>
          <p className="text-sm text-muted">역할에 맞는 화면으로 안내해드릴게요.</p>
        </div>

        <div className="flex flex-col gap-4">
          <Link
            href="/owner/auth"
            className="group rounded-[var(--radius-lg)] border border-border bg-surface p-6 flex items-center gap-4 hover:border-brand-300 hover:bg-brand-50/40 transition-colors"
          >
            <div className="w-14 h-14 rounded-2xl bg-brand-100 text-brand-700 flex items-center justify-center text-2xl">
              🧑‍🍳
            </div>
            <div className="flex-1">
              <p className="font-semibold text-foreground">사장님이에요</p>
              <p className="text-xs text-muted mt-0.5">업무를 Buddy에게 알려주고 관리해요</p>
            </div>
            <span className="text-muted group-hover:translate-x-0.5 transition-transform">→</span>
          </Link>

          <Link
            href="/staff/auth"
            className="group rounded-[var(--radius-lg)] border border-border bg-surface p-6 flex items-center gap-4 hover:border-brand-300 hover:bg-brand-50/40 transition-colors"
          >
            <div className="w-14 h-14 rounded-2xl bg-brand-100 text-brand-700 flex items-center justify-center text-2xl">
              🙋
            </div>
            <div className="flex-1">
              <p className="font-semibold text-foreground">알바생이에요</p>
              <p className="text-xs text-muted mt-0.5">초대코드로 들어가서 업무를 배워요</p>
            </div>
            <span className="text-muted group-hover:translate-x-0.5 transition-transform">→</span>
          </Link>
        </div>
      </div>
    </Shell>
  );
}
