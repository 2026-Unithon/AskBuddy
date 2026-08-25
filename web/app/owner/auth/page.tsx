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

  // 백엔드가 안 떠 있어도 데모는 계속돼야 한다. 네트워크 단절이면 로컬 상태로 진행하고,
  // 401·409 처럼 서버가 내린 판정이면 그대로 사용자에게 보여준다.
  function handleFailure(e: unknown, fallback: () => void) {
    if (e instanceof ApiError) {
      setError(
        e.status === 401
          ? "아이디 또는 비밀번호가 맞지 않습니다"
          : e.detail || `요청이 실패했습니다 (${e.status})`
      );
      return;
    }
    setError(null);
    fallback();
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
      router.push("/owner/intent");
    } catch (err) {
      handleFailure(err, () => {
        dispatch({ type: "LOGIN_OWNER", name: loginId, storeName: "" });
        router.push("/owner/intent");
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
      handleFailure(err, () => {
        dispatch({ type: "LOGIN_OWNER", name: name || signupId, storeName });
        router.push("/owner/intent");
      });
    } finally {
      setBusy(false);
    }
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

        {error && (
          <p className="mb-3 text-sm text-danger-700" role="alert">
            {error}
          </p>
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
