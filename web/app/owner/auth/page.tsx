"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button, Input, Shell, TopBar } from "@/components/ui";
import { useApp } from "@/lib/store";
import { ApiError, createStore, login, signup } from "@/lib/api";

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

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 인증은 실패하면 절대 넘어가지 않는다. 회원이 아니면 들어올 수 없다.
  // 백엔드가 꺼져 있어도 마찬가지다 — 통과시키면 로그인이 없는 것과 같다.
  function describe(e: unknown): string {
    if (e instanceof ApiError) {
      if (e.status === 401) return "이메일 또는 비밀번호가 맞지 않습니다";
      if (e.status === 409) return "이미 가입된 이메일입니다";
      if (e.status === 404) return e.detail || "찾을 수 없습니다";
      if (e.status === 422) return "입력값을 다시 확인해주세요";
      return e.detail || `요청이 실패했습니다 (${e.status})`;
    }
    return "서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요";
  }

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { token, user } = await login(loginId, loginPw, "OWNER");
      dispatch({
        type: "SET_AUTH",
        token,
        role: "OWNER",
        displayName: user.name,
        userId: user.user_id,
        storeId: user.store_id ?? null,
      });
      // 이미 매장이 있으면 등록 흐름을 다시 태우지 않는다. 바로 대시보드로.
      router.push(user.store_id ? "/owner/dashboard" : "/owner/intent");
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
      const created = await signup({
        name: name || signupId,
        email: signupId,
        password: signupPw,
        role: "OWNER",
      });
      dispatch({
        type: "SET_AUTH",
        token: created.token,
        role: "OWNER",
        displayName: created.user.name,
        userId: created.user.user_id,
        storeId: created.user.store_id ?? null,
      });

      // 가입 직후 토큰에는 store_id 가 없다. 매장을 만들어야 /ingest/* 가 열린다.
      const store = await createStore(
        { storeName, businessType: "CAFE" },
        created.token
      );
      dispatch({
        type: "SET_STORE",
        token: store.token,
        storeId: store.store.store_id,
        storeSlug: store.store.store_slug,
        storeName: store.store.store_name,
      });
      router.push("/owner/intent");
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell>
      <TopBar title="사장님" backHref="/role" />
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
              placeholder="이메일 (예: owner@demo.cafe)"
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
            <Button type="submit" size="lg" className="w-full mt-3" disabled={busy}>
              {busy ? "확인 중…" : "로그인"}
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
              placeholder="이메일 (예: owner@demo.cafe)"
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
            <Button type="submit" size="lg" className="w-full mt-3" disabled={busy}>
              {busy ? "만드는 중…" : "가입하고 시작하기"}
            </Button>
          </form>
        )}
      </div>
    </Shell>
  );
}
