import Link from "next/link";
import { Shell, TopBar } from "@/components/ui";

export default function OwnerIntentPage() {
  return (
    <Shell>
      <TopBar />
      <div className="flex-1 flex flex-col px-6 pt-2 pb-10 gap-8">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold text-brand-700">어떤 일로 오셨나요?</h1>
          <p className="text-sm text-muted">알맞은 화면으로 안내해드릴게요</p>
        </div>

        <div className="flex flex-col gap-4">
          <Link
            href="/owner/category"
            className="rounded-[var(--radius-lg)] bg-brand-700 text-white p-6 flex flex-col gap-3 shadow-[0_8px_28px_rgba(46,107,60,0.35)] hover:-translate-y-0.5 transition-transform"
          >
            <span className="text-4xl">📤</span>
            <div>
              <p className="text-xl font-bold">인수인계 하러 왔어요</p>
              <p className="text-sm text-white/70 mt-1 leading-relaxed">
                업무 자료를 Buddy에게 가르쳐
                <br />
                신입이 빠르게 배울 수 있게 해요
              </p>
            </div>
          </Link>

          <Link
            href="/owner/dashboard"
            className="rounded-[var(--radius-lg)] bg-surface border border-border p-6 flex flex-col gap-3 shadow-[0_1px_2px_-1px_rgba(0,0,0,0.10),0_1px_3px_rgba(0,0,0,0.10)] hover:-translate-y-0.5 transition-transform"
          >
            <span className="text-4xl">📊</span>
            <div>
              <p className="text-xl font-bold text-brand-700">대시보드 보러 왔어요</p>
              <p className="text-sm text-muted mt-1 leading-relaxed">
                직원 진행상황 확인 및
                <br />
                대기 중인 질문에 답변해요
              </p>
            </div>
          </Link>
        </div>
      </div>
    </Shell>
  );
}
