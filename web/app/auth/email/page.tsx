"use client";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Input, Shell, TopBar } from "@/components/ui";
import { ApiError, apiErrorMessage, login, signup } from "@/lib/api";
import { useApp } from "@/lib/store";
import { LoginLoading, LoginRetry, useLoginDestination } from "@/components/login-session";
function Email() {
  const next = useSearchParams().get("next");
  const { dispatch } = useApp();
  const session = useLoginDestination(next);
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const auth = useMutation({
    mutationFn: () => mode === "login" ? login(email, password) : signup({ name, email, password }),
    onSuccess: (s) => { queryClient.clear(); dispatch({ type: "SET_AUTH", token: s.token, role: s.user.role, userId: s.user.user_id, storeId: s.user.store_id ?? null }); },
  });
  if (session.error) return <LoginRetry retry={session.retry} />;
  if (!session.state.hydrated || session.state.token) return <LoginLoading />;
  const message = auth.error instanceof ApiError && auth.error.status === 401 ? "이메일 또는 비밀번호를 확인해 주세요." : auth.error instanceof ApiError && auth.error.status === 409 ? "이미 가입된 이메일입니다. 로그인해 주세요." : apiErrorMessage(auth.error, "가입 또는 로그인에 실패했어요.");
  return <><TopBar title="이메일로 시작하기" backHref="/" /><form className="flex flex-1 flex-col justify-center gap-4 px-6 pb-10" onSubmit={(e) => { e.preventDefault(); if (!auth.isPending) auth.mutate(); }}>
    <h1 className="text-2xl font-bold">{mode === "login" ? "다시 만나 반가워요" : "AskBuddy에 오신 걸 환영해요"}</h1>
    {mode === "signup" && <Input aria-label="이름" placeholder="이름" value={name} onChange={(e) => setName(e.target.value)} required maxLength={50} />}
    <Input aria-label="이메일" placeholder="이메일" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
    <Input aria-label="비밀번호" placeholder="비밀번호" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} maxLength={72} />
    <Button type="submit" loading={auth.isPending}>{mode === "login" ? "로그인" : "가입하기"}</Button>
    {auth.error && <p role="alert" className="text-danger-500">{message}</p>}
    <Button variant="ghost" disabled={auth.isPending} onClick={() => { auth.reset(); setMode(mode === "login" ? "signup" : "login"); }}>{mode === "login" ? "처음이신가요? 가입하기" : "이미 계정이 있어요"}</Button>
  </form></>;
}
export default function Page() { return <Shell><Suspense fallback={<LoginLoading />}><Email /></Suspense></Shell>; }
