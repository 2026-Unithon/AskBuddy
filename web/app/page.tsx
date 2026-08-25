import { LinkButton, Shell } from "@/components/ui";

export default function WelcomePage() {
  return (
    <Shell>
      <div className="flex-1 flex flex-col items-center justify-center px-8 text-center gap-6">
        <div className="w-24 h-24 rounded-[2rem] bg-brand-500 flex items-center justify-center text-5xl shadow-lg shadow-brand-200">
          🐻
        </div>
        <div className="space-y-2">
          <h1 className="text-2xl font-bold text-foreground">AskBuddy</h1>
          <p className="text-muted text-sm leading-relaxed">
            음성·영상·카톡·문서로 알려주면
            <br />
            Buddy가 배워서 신입에게 대신 가르쳐줘요
          </p>
        </div>
      </div>
      <div className="px-6 pb-10 flex flex-col gap-3">
        <LinkButton href="/role" variant="primary" className="w-full h-13 text-base">
          시작하기
        </LinkButton>
        <p className="text-center text-xs text-muted">
          승인된 매장 지식만 근거로 답해요. 확실하지 않으면 사장님께 넘겨요.
        </p>
      </div>
    </Shell>
  );
}
