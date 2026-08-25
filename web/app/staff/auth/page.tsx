"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button, Input, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { ApiError, joinByInvite, login } from "@/lib/api";

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

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleFailure(e: unknown, fallback: () => void) {
    if (e instanceof ApiError) {
      setError(
        e.status === 401
          ? "이메일 또는 비밀번호가 맞지 않습니다"
          : e.detail || `요청이 실패했습니다 (${e.status})`
      );
      return;
    }
    // 백엔드가 꺼져 있으면 데모가 멈추지 않도록 로컬 상태로 진행한다
    setError(null);
    fallback();
  }

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { token, user } = await login(loginId, loginPw, "STAFF");
      dispatch({
        type: "SET_AUTH",
        token,
        role: "STAFF",
        displayName: user.name,
        userId: user.user_id,
        storeId: user.store_id ?? null,
        inviteCode: loginCode || undefined,
      });
      router.push("/staff/roadmap");
    } catch (err) {
      handleFailure(err, () => {
        dispatch({ type: "LOGIN_STAFF", name: loginId, inviteCode: loginCode });
        router.push("/staff/roadmap");
      });
    } finally {
      setBusy(false);
    }
  }

  async function handleSignup(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // 신입은 이 한 번으로 가입과 매장 합류가 같이 끝난다. 토큰에 store_id 가 들어온다.
      const { token, user } = await joinByInvite({
        name: name || signupId,
        email: signupId,
        password: signupPw,
        inviteCode: signupCode.trim().toUpperCase(),
      });
      dispatch({
        type: "SET_AUTH",
        token,
        role: "STAFF",
        displayName: user.name,
        userId: user.user_id,
        storeId: user.store_id ?? null,
        inviteCode: signupCode.trim().toUpperCase(),
      });
      router.push("/staff/roadmap");
    } catch (err) {
      handleFailure(err, () => {
        dispatch({ type: "LOGIN_STAFF", name: name || signupId, inviteCode: signupCode });
        router.push("/staff/roadmap");
      });
    } finally {
      setBusy(false);
    }
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

        {error && (
          <p className="mb-3 text-sm text-danger-700" role="alert">
            {error}
          </p>
        )}

        {tab === "login" ? (
          <form onSubmit={handleLogin} className="flex flex-col gap-3">
            <Input
              placeholder="이메일"
              value={loginId}
              onChange={(e) => setLoginId(e.target.value)}
              autoComplete="email"
              type="email"
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
            <Button type="submit" size="lg" className="w-full mt-3" disabled={busy}>
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
              placeholder="이메일"
              value={signupId}
              onChange={(e) => setSignupId(e.target.value)}
              autoComplete="email"
              type="email"
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
            <Button type="submit" size="lg" className="w-full mt-3" disabled={busy}>
              가입하고 시작하기
            </Button>
          </form>
        )}
      </div>
    </Shell>
  );
}
