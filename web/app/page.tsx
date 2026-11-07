"use client";
import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Shell } from "@/components/ui";
import { BuddyImage, Stagger, focusRing } from "@/components/kit";
import { KakaoLoginButton } from "@/components/kakao-login-button";
import { LoginLoading, LoginRetry, useLoginDestination } from "@/components/login-session";

/** 로그인 첫 화면(a01a). 버디가 한 번 튀고, 글과 버튼이 차례로 나온다. */
function Login() {
  const next = useSearchParams().get("next");
  const session = useLoginDestination(next);
  if (session.error) return <LoginRetry retry={session.retry} />;
  if (!session.state.hydrated || session.state.token) return <LoginLoading />;
  return (
    <main className="flex flex-1 flex-col justify-center gap-8 px-6 py-10">
      <div className="flex flex-col items-center gap-4 text-center">
        <span data-bounce="" className="inline-block motion-safe:animate-[buddy-bounce_600ms_var(--ease-spring)_200ms_both]">
          <BuddyImage size={140} />
        </span>
        <Stagger step={80}>
          <h1 className="text-[34px] font-black tracking-[-0.68px] text-primary">AskBuddy</h1>
          <p className="text-[19px] font-bold leading-[1.45] text-ink">
            간편한 인수인계,
            <br />
            버디와 함께 시작해요.
          </p>
        </Stagger>
      </div>
      <div className="flex flex-col gap-3">
        <Stagger step={80}>
          <KakaoLoginButton intent="LOGIN" next={next} />
          <Link
            href={next ? `/auth/email?next=${encodeURIComponent(next)}` : "/auth/email"}
            className={`flex min-h-14 w-full items-center justify-center rounded-[12px] bg-surface text-[16px] font-bold text-ink shadow-card ${focusRing}`}
          >
            이메일로 시작하기
          </Link>
          <p className="text-center text-[14px] text-ink-muted">알바생은 사장님이 보낸 링크로 바로 들어와요.</p>
        </Stagger>
      </div>
    </main>
  );
}
export default function Page() {
  return (
    <Shell>
      <Suspense fallback={<LoginLoading />}>
        <Login />
      </Suspense>
    </Shell>
  );
}
