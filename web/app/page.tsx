import { Buddy, LinkButton, Shell } from "@/components/ui";

const FEATURES = [
  { icon: "🎙️", text: "음성·영상·텍스트로 업무를 알려주면" },
  { icon: "🤖", text: "AI Buddy가 학습해서 신입에게 가르쳐요" },
  { icon: "🎮", text: "듀오링고처럼 게임하며 업무를 배워요" },
];

export default function WelcomePage() {
  return (
    <Shell>
      <div className="flex-1 flex flex-col items-center justify-center px-6 text-center gap-6">
        <div className="relative">
          <Buddy size={148} />
          <span className="absolute -top-2 -right-2 text-3xl animate-bounce">🌟</span>
        </div>
        <div className="space-y-2">
          <h1 className="text-4xl font-bold text-brand-700 tracking-tight">AskBuddy</h1>
          <p className="text-xl font-semibold text-foreground leading-snug">
            간편한 인수인계,
            <br />
            <span className="text-brand-500">AskBuddy</span>입니다 👋
          </p>
          <p className="text-muted text-sm font-medium">처음에는 Buddy와 함께, 익숙해지면 혼자.</p>
        </div>
        <div className="w-full space-y-2.5">
          {FEATURES.map((f) => (
            <div key={f.text} className="flex items-center gap-3 bg-surface rounded-2xl px-4 py-3 shadow-sm">
              <span className="text-xl">{f.icon}</span>
              <span className="text-sm font-semibold text-foreground">{f.text}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="px-6 pb-10">
        <LinkButton href="/role" variant="primary" className="w-full h-13 text-base shadow-lg shadow-brand-200">
          시작하기 →
        </LinkButton>
      </div>
    </Shell>
  );
}
