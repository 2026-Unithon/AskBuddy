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

  // 심사·체험용 데모 계정을 미리 채워둔다. 처음 오는 사람이 가입부터 하지 않고
  // 바로 눌러서 볼 수 있어야 한다. 지우고 자기 계정으로 로그인해도 된다.
  const [loginId, setLoginId] = useState("jihyun@demo.cafe");
  const [loginPw, setLoginPw] = useState("demo1234");
  const [loginCode, setLoginCode] = useState("CAFE-DEMO");

  const [name, setName] = useState("");
  const [signupId, setSignupId] = useState("");
  const [signupPw, setSignupPw] = useState("");
  const [signupCode, setSignupCode] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 인증은 실패하면 절대 넘어가지 않는다. 회원이 아니면 들어올 수 없다.
  // 백엔드가 꺼져 있어도 마찬가지다 — 통과시키면 로그인이 없는 것과 같다.
  function describe(e: unknown): string {
    if (e instanceof ApiError) {
      if (e.status === 401) return "이메일 또는 비밀번호가 맞지 않습니다";
      if (e.status === 409) return "이미 가입된 이메일입니다";
      if (e.status === 404) return "초대코드가 올바르지 않습니다. 사장님께 다시 확인해주세요";
      if (e.status === 422) return "초대코드를 입력해주세요";
      return e.detail || `요청이 실패했습니다 (${e.status})`;
    }
    return "서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요";
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
      setError(describe(err));
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
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell>
      <TopBar title="알바생" backHref="/role" />
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
          <div
            role="alert"
            className="mb-4 flex items-start gap-2.5 rounded-2xl bg-danger-50 px-4 py-3 text-danger-700"
          >
            <span className="text-base leading-5">⚠️</span>
            <p className="flex-1 text-sm font-medium leading-5">{error}</p>
          </div>
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
              placeholder="초대코드 (이미 가입했다면 비워도 됩니다)"
              value={loginCode}
              onChange={(e) => setLoginCode(e.target.value.toUpperCase())}
            />
            <Button type="submit" size="lg" className="w-full mt-3" disabled={busy}>
              로그인
            </Button>
            <p className="mt-2 text-center text-xs font-semibold text-brand-700">
              로그인 버튼만 누르시면 이용 가능 하십니다~!
            </p>
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
