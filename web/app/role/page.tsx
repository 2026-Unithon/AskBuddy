import Link from "next/link";
import { BuddyBubble, Shell, TopBar } from "@/components/ui";

export default function RoleSelectPage() {
  return (
    <Shell>
      <TopBar />
      <div className="flex-1 flex flex-col px-6 pt-1 pb-10 gap-5">
        <BuddyBubble text="안녕하세요! 저는 Buddy예요 😊" />

        <div className="space-y-1">
          <h1 className="text-2xl font-bold text-brand-700">어떤 분이세요?</h1>
          <p className="text-sm text-muted">역할에 맞는 화면으로 안내해드릴게요</p>
        </div>

        <div className="flex flex-col gap-4">
          <Link
            href="/owner/auth"
            className="group rounded-[var(--radius-lg)] bg-surface p-6 flex flex-col gap-3 shadow-[0_2px_4px_-2px_rgba(0,0,0,0.10),0_4px_6px_-1px_rgba(0,0,0,0.10)] hover:-translate-y-0.5 transition-transform"
          >
            <span className="text-4xl">👑</span>
            <div>
              <p className="text-xl font-bold text-brand-700">사장님이에요</p>
              <p className="text-sm text-muted mt-1 leading-relaxed">
                인수인계 자료를 올리고
                <br />
                신입 현황을 한눈에 확인해요
              </p>
            </div>
            <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-background px-3 py-1 text-xs font-bold text-brand-700">
              <span className="w-2 h-2 rounded-full bg-brand-500" />
              사장님 · 퇴사자
            </span>
          </Link>

          <Link
            href="/staff/auth"
            className="group rounded-[var(--radius-lg)] bg-surface p-6 flex flex-col gap-3 shadow-[0_2px_4px_-2px_rgba(0,0,0,0.10),0_4px_6px_-1px_rgba(0,0,0,0.10)] hover:-translate-y-0.5 transition-transform"
          >
            <span className="text-4xl">🌱</span>
            <div>
              <p className="text-xl font-bold text-foreground">알바생이에요</p>
              <p className="text-sm text-muted mt-1 leading-relaxed">
                로드맵을 따라가며
                <br />
                업무를 차근차근 배워요
              </p>
            </div>
            <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-background px-3 py-1 text-xs font-bold text-foreground">
              <span className="w-2 h-2 rounded-full bg-accent-500" />
              신입 직원
            </span>
          </Link>
        </div>
      </div>
    </Shell>
  );
}
