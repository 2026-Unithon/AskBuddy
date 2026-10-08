"use client";
import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Shell } from "@/components/ui";
import { AUTH_ERROR_COPY } from "@/lib/api";
import { LoginLoading, LoginRetry, useLoginDestination } from "@/components/login-session";
function Complete() {
  const params = useSearchParams();
  const error = params.get("error");
  const session = useLoginDestination(params.get("next"), !error);
  if (error || (session.state.hydrated && !session.state.token && !session.error)) return <div className="flex flex-1 flex-col justify-center gap-4 p-6 text-center"><p role="alert">{AUTH_ERROR_COPY[error ?? "KAKAO_FAILED"] ?? AUTH_ERROR_COPY.KAKAO_FAILED}</p><Link href="/" className="min-h-12 underline">로그인 화면으로</Link></div>;
  if (session.error) return <LoginRetry retry={session.retry} />;
  return <LoginLoading />;
}
export default function Page() { return <Shell><Suspense fallback={<LoginLoading />}><Complete /></Suspense></Shell>; }
