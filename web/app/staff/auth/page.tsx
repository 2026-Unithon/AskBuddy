"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button, Input, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { ApiError, joinByInvite, login } from "@/lib/api";

type Tab = "login" | "signup";
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export default function StaffAuthPage() {
  const router = useRouter();
  const { dispatch } = useApp();
  const [tab, setTab] = useState<Tab>("login");

  // 데모 자격 증명은 명시적으로 켠 환경에서만 노출한다.
  const [loginId, setLoginId] = useState(DEMO_MODE ? "jiho@demo.cafe" : "");
  const [loginPw, setLoginPw] = useState(DEMO_MODE ? "demo1234" : "");

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
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const { token, user } = await login(loginId, loginPw, "STAFF");
      dispatch({
        type: "SET_AUTH",
        token,
        role: "STAFF",
        userId: user.user_id,
        storeId: user.store_id ?? null,
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
    if (busy) return;
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
        userId: user.user_id,
        storeId: user.store_id ?? null,
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
              type="button"
              onClick={() => setTab(t)}
              aria-pressed={tab === t}
              className={`flex-1 min-h-11 rounded-full text-sm font-semibold transition-colors ${
                tab === t ? "bg-surface text-brand-700 shadow-sm" : "text-muted"
              }`}
            >
              {t === "login" ? "로그인" : "회원가입"}
            </button>
          ))}
        </div>

        {error && (
          <div
            id="staff-auth-error"
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
              aria-label="이메일"
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "staff-auth-error" : undefined}
              value={loginId}
              onChange={(e) => setLoginId(e.target.value)}
              autoComplete="email"
              type="email"
              required
            />
            <Input
              placeholder="비밀번호"
              aria-label="비밀번호"
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "staff-auth-error" : undefined}
              type="password"
              value={loginPw}
              onChange={(e) => setLoginPw(e.target.value)}
              autoComplete="current-password"
              required
            />
            <Button type="submit" size="lg" className="w-full mt-3" loading={busy} loadingLabel="로그인 확인 중">
              로그인
            </Button>
            {DEMO_MODE && (
              <p className="mt-3 text-center text-sm font-bold text-brand-700">
                데모 계정이 입력되어 있습니다.
              </p>
            )}
          </form>
        ) : (
          <form onSubmit={handleSignup} className="flex flex-col gap-3">
            <Input
              placeholder="이름"
              aria-label="이름"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <Input
              placeholder="이메일"
              aria-label="이메일"
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "staff-auth-error" : undefined}
              value={signupId}
              onChange={(e) => setSignupId(e.target.value)}
              autoComplete="email"
              type="email"
              required
            />
            <Input
              placeholder="비밀번호"
              aria-label="비밀번호"
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "staff-auth-error" : undefined}
              type="password"
              value={signupPw}
              onChange={(e) => setSignupPw(e.target.value)}
              autoComplete="new-password"
              required
            />
            <Input
              placeholder="초대코드 (예: CAFE-DEMO)"
              aria-label="초대코드"
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "staff-auth-error" : undefined}
              value={signupCode}
              onChange={(e) => setSignupCode(e.target.value.toUpperCase())}
              required
            />
            <Button type="submit" size="lg" className="w-full mt-3" loading={busy} loadingLabel="계정 만드는 중">
              가입하고 시작하기
            </Button>
          </form>
        )}
      </div>
    </Shell>
  );
}
