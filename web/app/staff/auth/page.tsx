"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button, Input, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";

type Tab = "login" | "signup";

export default function StaffAuthPage() {
  const router = useRouter();
  const { dispatch } = useApp();
  const [tab, setTab] = useState<Tab>("login");

  const [loginId, setLoginId] = useState("");
  const [loginPw, setLoginPw] = useState("");
  const [loginCode, setLoginCode] = useState("");

  const [name, setName] = useState("");
  const [signupId, setSignupId] = useState("");
  const [signupPw, setSignupPw] = useState("");
  const [signupCode, setSignupCode] = useState("");

  function handleLogin(e: FormEvent) {
    e.preventDefault();
    dispatch({ type: "LOGIN_STAFF", name: loginId, inviteCode: loginCode });
    router.push("/staff/roadmap");
  }

  function handleSignup(e: FormEvent) {
    e.preventDefault();
    dispatch({ type: "LOGIN_STAFF", name: name || signupId, inviteCode: signupCode });
    router.push("/staff/roadmap");
  }

  return (
    <Shell>
      <TopBar title="알바생" />
      <div className="flex-1 flex flex-col px-6 pt-4 pb-10">
        <div className="flex rounded-full bg-surface-muted p-1 mb-6">
          {(["login", "signup"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 h-10 rounded-full text-sm font-semibold transition-colors ${
                tab === t ? "bg-surface text-brand-700 shadow-sm" : "text-muted"
              }`}
            >
              {t === "login" ? "로그인" : "회원가입"}
            </button>
          ))}
        </div>

        {tab === "login" ? (
          <form onSubmit={handleLogin} className="flex flex-col gap-3">
            <Input
              placeholder="아이디"
              value={loginId}
              onChange={(e) => setLoginId(e.target.value)}
              autoComplete="username"
              required
            />
            <Input
              placeholder="비밀번호"
              type="password"
              value={loginPw}
              onChange={(e) => setLoginPw(e.target.value)}
              autoComplete="current-password"
              required
            />
            <Input
              placeholder="초대코드 (예: CAFE-DEMO)"
              value={loginCode}
              onChange={(e) => setLoginCode(e.target.value.toUpperCase())}
              required
            />
            <Button type="submit" size="lg" className="w-full mt-3">
              로그인
            </Button>
          </form>
        ) : (
          <form onSubmit={handleSignup} className="flex flex-col gap-3">
            <Input
              placeholder="이름"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <Input
              placeholder="아이디"
              value={signupId}
              onChange={(e) => setSignupId(e.target.value)}
              autoComplete="username"
              required
            />
            <Input
              placeholder="비밀번호"
              type="password"
              value={signupPw}
              onChange={(e) => setSignupPw(e.target.value)}
              autoComplete="new-password"
              required
            />
            <Input
              placeholder="초대코드 (예: CAFE-DEMO)"
              value={signupCode}
              onChange={(e) => setSignupCode(e.target.value.toUpperCase())}
              required
            />
            <Button type="submit" size="lg" className="w-full mt-3">
              가입하고 시작하기
            </Button>
          </form>
        )}
      </div>
    </Shell>
  );
}
