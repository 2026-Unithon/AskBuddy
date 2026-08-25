import Link from "next/link";
import Image from "next/image";

export default function WelcomePage() {
  return (
    <div className="min-h-dvh w-full flex justify-center bg-background">
      <div className="w-full max-w-[480px] min-h-dvh flex flex-col relative overflow-hidden">
        <Image
          src="/images/roadmap-bg.png"
          alt=""
          fill
          className="object-cover"
          style={{ objectPosition: "top" }}
          priority
        />

        <div
          className="relative flex-1 flex flex-col items-center justify-center px-6 text-center"
          aria-labelledby="welcome-title"
        >
          <div className="w-[190px] h-[190px] relative drop-shadow-[0_12px_24px_rgba(0,0,0,0.18)]">
            <Image src="/images/buddy.png" alt="AskBuddy 마스코트" fill className="object-contain" priority />
          </div>
          <div className="w-full max-w-[260px] mt-4">
            <h1
              id="welcome-title"
              className="text-4xl font-bold text-brand-700 tracking-[-0.9px] leading-10"
              style={{ textShadow: "0 1px 12px rgba(255,255,255,0.7)" }}
            >
              AskBuddy
            </h1>
            <p
              className="mt-2 text-xl font-semibold leading-[27.5px]"
              style={{ textShadow: "0 1px 12px rgba(255,255,255,0.7)" }}
            >
              <span className="text-foreground">
                간편한 인수인계,
                <br />
              </span>
              <span className="text-brand-500">AskBuddy</span>
              <span className="text-foreground">입니다 👋</span>
            </p>
            <p
              className="mt-2 text-sm font-medium text-foreground/70"
              style={{ textShadow: "0 1px 12px rgba(255,255,255,0.7)" }}
            >
              처음에는 Buddy와 함께, 익숙해지면 혼자.
            </p>
          </div>
        </div>

        <div className="relative px-6 pb-10">
          <Link
            href="/role"
            aria-label="AskBuddy 시작하기"
            className="flex w-full items-center justify-center py-4 rounded-2xl bg-brand-500 shadow-[0px_6px_20px_#5bbf6a61] font-bold text-lg text-white transition-transform active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-700"
          >
            시작하기 →
          </Link>
        </div>
      </div>
    </div>
  );
}
