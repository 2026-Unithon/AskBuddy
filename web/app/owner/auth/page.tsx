"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button, Input, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";

type Tab = "login" | "signup";

export default function OwnerAuthPage() {
  const router = useRouter();
  const { dispatch } = useApp();
  const [tab, setTab] = useState<Tab>("login");

  const [loginId, setLoginId] = useState("");
  const [loginPw, setLoginPw] = useState("");

  const [name, setName] = useState("");
  const [storeName, setStoreName] = useState("");
  const [signupId, setSignupId] = useState("");
  const [signupPw, setSignupPw] = useState("");

  function handleLogin(e: FormEvent) {
    e.preventDefault();
    dispatch({ type: "LOGIN_OWNER", name: loginId, storeName: "" });
    router.push("/owner/intent");
  }

  function handleSignup(e: FormEvent) {
    e.preventDefault();
    dispatch({ type: "LOGIN_OWNER", name: name || signupId, storeName });
    router.push("/owner/intent");
  }

  return (
    <Shell>
      <TopBar title="사장님" />
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
            <Button type="submit" size="lg" className="w-full mt-3">
              로그인
            </Button>
          </form>
        ) : (
          <form onSubmit={handleSignup} className="flex flex-col gap-3">
            <Input
              placeholder="사장님 이름"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <Input
              placeholder="매장명 (예: 데모 카페)"
              value={storeName}
              onChange={(e) => setStoreName(e.target.value)}
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
            <Button type="submit" size="lg" className="w-full mt-3">
              가입하고 시작하기
            </Button>
          </form>
        )}
      </div>
    </Shell>
  );
}
