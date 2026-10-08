"use client";

import { useQuery } from "@tanstack/react-query";
import { kakaoStartUrl } from "@/lib/api";
import { providersQuery } from "@/lib/query";

// 카카오 디자인 가이드: 배경 #FEE500, 글자 85% 검정. 서버 설정이 없으면 버튼을 숨긴다
export function KakaoLoginButton({ intent, invite, next, label = "카카오 로그인" }: {
  intent: "LOGIN" | "STAFF_JOIN";
  invite?: string;
  next?: string | null;
  label?: string;
}) {
  const providers = useQuery(providersQuery());
  if (providers.isPending) return <p role="status" className="text-center text-sm text-muted">로그인 방법을 확인하고 있어요…</p>;
  if (providers.isError) return <div className="text-center"><p role="alert" className="text-sm text-danger-500">카카오 로그인 설정을 불러오지 못했어요.</p><button type="button" className="min-h-11 underline" onClick={() => void providers.refetch()}>다시 시도</button></div>;
  if (!providers.data?.kakao) return null;
  return (
    <a
      href={kakaoStartUrl({ intent, invite, next })}
      className="flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#FEE500] text-[15px] font-bold text-black/85 active:scale-[0.98]"
    >
      <svg aria-hidden width="18" height="18" viewBox="0 0 24 24"><path fill="currentColor" d="M12 3C6.48 3 2 6.48 2 10.77c0 2.77 1.86 5.2 4.66 6.57l-.95 3.48c-.08.3.26.54.52.37l4.15-2.74c.53.07 1.07.1 1.62.1 5.52 0 10-3.48 10-7.78S17.52 3 12 3z" /></svg>
      {label}
    </a>
  );
}
