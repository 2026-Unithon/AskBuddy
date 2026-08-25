import { LinkButton, Shell } from "@/components/ui";

export default function WelcomePage() {
  return (
    <Shell>
      <div className="flex-1 flex flex-col items-center justify-center px-8 text-center gap-6">
        <div className="w-[180px] h-[180px] rounded-[2.5rem] bg-brand-500 flex items-center justify-center text-7xl shadow-lg shadow-brand-200">
          🐻
        </div>
        <div className="space-y-2">
          <p className="text-lg font-semibold text-foreground leading-snug">
            간편한 인수인계,
            <br />
            <span className="text-brand-500">AskBuddy</span>입니다 👋
          </p>
          <p className="text-muted text-sm">처음에는 Buddy와 함께, 익숙해지면 혼자.</p>
        </div>
      </div>
      <div className="px-6 pb-10 flex flex-col gap-3">
        <LinkButton href="/role" variant="primary" className="w-full h-13 text-base shadow-lg shadow-brand-200">
          시작하기 →
        </LinkButton>
        <p className="text-center text-xs text-muted">
          승인된 매장 지식만 근거로 답해요. 확실하지 않으면 사장님께 넘겨요.
        </p>
      </div>
    </Shell>
  );
}
