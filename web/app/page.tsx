"use client";
import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Buddy, Shell } from "@/components/ui";
import { KakaoLoginButton } from "@/components/kakao-login-button";
import { LoginLoading, LoginRetry, useLoginDestination } from "@/components/login-session";
function Login() {
  const next = useSearchParams().get("next");
  const session = useLoginDestination(next);
  if (session.error) return <LoginRetry retry={session.retry} />;
  if (!session.state.hydrated || session.state.token) return <LoginLoading />;
  return <div className="flex flex-1 flex-col justify-center gap-6 px-6 py-10">
    <div className="flex flex-col items-center gap-4 text-center"><Buddy size={150} /><h1 className="text-4xl font-bold text-brand-700">AskBuddy</h1><p className="text-xl font-semibold">간편한 인수인계,<br />버디와 함께 시작해요.</p></div>
    <div className="mt-8 space-y-3"><KakaoLoginButton intent="LOGIN" next={next} />
    <Link href={next ? `/auth/email?next=${encodeURIComponent(next)}` : "/auth/email"} className="flex min-h-12 items-center justify-center rounded-xl border border-border bg-surface font-semibold">이메일로 시작하기</Link></div>
    <p className="text-center text-base text-muted">알바생은 사장님이 보낸 링크로 바로 들어와요.</p>
  </div>;
}
export default function Page() { return <Shell><Suspense fallback={<LoginLoading />}><Login /></Suspense></Shell>; }
