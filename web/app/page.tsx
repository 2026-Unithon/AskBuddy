import Link from "next/link";
import Image from "next/image";
import { Shell } from "@/components/ui";

export default function WelcomePage() {
  return (
    <Shell>
      <div
        className="flex-1 flex flex-col items-center justify-center px-6 text-center"
        aria-labelledby="welcome-title"
      >
        <div className="w-[233px] h-[233px] relative" role="img" aria-label="AskBuddy 마스코트">
          <Image src="/images/buddy.png" alt="" fill className="object-cover" priority />
        </div>
        <div className="w-full max-w-[232px] mt-6">
          <h1
            id="welcome-title"
            className="text-4xl font-bold text-brand-700 tracking-[-0.9px] leading-10"
          >
            AskBuddy
          </h1>
          <p className="mt-2 text-xl font-semibold tracking-normal leading-[27.5px]">
            <span className="text-foreground">
              간편한 인수인계,
              <br />
            </span>
            <span className="text-brand-500">AskBuddy</span>
            <span className="text-foreground">입니다 👋</span>
          </p>
          <p className="mt-2 text-sm font-medium text-muted">처음에는 Buddy와 함께, 익숙해지면 혼자.</p>
        </div>
      </div>
      <div className="px-6 pb-10">
        <Link
          href="/role"
          aria-label="AskBuddy 시작하기"
          className="flex w-full items-center justify-center py-4 rounded-2xl bg-brand-500 shadow-[0px_6px_20px_#5bbf6a61] font-bold text-lg text-white transition-transform active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-700"
        >
          시작하기 →
        </Link>
      </div>
    </Shell>
  );
}
