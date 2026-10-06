"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { BuddyImage, Button, Caption, ErrorInline, Screen, Sheet, focusRing } from "@/components/kit";
import { ApiError, login, signup } from "@/lib/api";
import { useApp } from "@/lib/store";

type Mode = "login" | "signup";
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

// 인증은 실패하면 넘어가지 않는다. 백엔드가 꺼져 있어도 마찬가지다 (MVP §28 로그인 실패 문구).
function describe(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "이메일 또는 비밀번호가 달라요";
    if (error.status === 409) return "이미 가입된 이메일이에요. 로그인해 주세요";
    if (error.status === 422) return "입력한 내용을 다시 확인해 주세요";
    return error.detail || "지금은 로그인할 수 없어요. 잠시 후 다시 시도해 주세요";
  }
  return "서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요";
}

// 다른 화면에서 로그인으로 보내졌으면 그 화면으로 돌아간다. 점주 화면 안의 주소만 받는다
function destinationAfterLogin(): string {
  const requested = new URLSearchParams(window.location.search).get("next");
  return requested?.startsWith("/owner") && !requested.startsWith("//") ? requested : "/owner";
}

function Field({
  label,
  ...props
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[13px] font-medium text-ink-muted">{label}</span>
      <input
        {...props}
        className={`min-h-12 rounded-[16px] bg-surface px-4 text-[16px] text-ink shadow-card ${focusRing}`}
      />
    </label>
  );
}

// O1 시작·로그인. 카카오 로그인은 다른 작업에서 붙인다 (계획 U7) — 지금은 이메일만.
export default function OwnerAuthPage() {
  const router = useRouter();
  const { dispatch } = useApp();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState(DEMO_MODE ? "owner@demo.cafe" : "");
  const [password, setPassword] = useState(DEMO_MODE ? "demo1234" : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") {
        const { token, user } = await login(email, password, "OWNER");
        dispatch({ type: "SET_AUTH", token, role: "OWNER", userId: user.user_id, storeId: user.store_id ?? null });
        // 매장이 없으면 매장 이름부터 받는다
        router.push(user.store_id ? destinationAfterLogin() : "/owner/intent");
      } else {
        const created = await signup({ name: (name.trim() || email.split("@")[0]).slice(0, 50), email, password, role: "OWNER" });
        dispatch({ type: "SET_AUTH", token: created.token, role: "OWNER", userId: created.user.user_id, storeId: null });
        router.push("/owner/intent");
      }
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen
      footer={
        <>
          <Button onClick={() => setOpen(true)} variant="secondary">
            이메일로 시작하기
          </Button>
          <Caption className="text-center">알바생은 사장님이 보낸 링크로 들어와요</Caption>
        </>
      }
    >
      <div aria-hidden className="pointer-events-none absolute left-1/2 top-[160px] size-[300px] -translate-x-1/2">
        {/* eslint-disable-next-line @next/next/no-img-element -- 블러 필터 여백이 있는 장식 SVG */}
        <img alt="" src="/figma/halo.svg" className="absolute inset-[-13.33%] block size-[126.66%] max-w-none" />
      </div>
      <div className="relative flex flex-1 flex-col items-center justify-center gap-4">
        <BuddyImage size={176} />
        <h1 className="text-[34px] font-black leading-[1.45] tracking-[-0.68px] text-primary">AskBuddy</h1>
        <p className="text-[16px] font-medium leading-[1.45] tracking-[-0.16px] text-ink-muted">사장님이 없어도 돌아가는 매장</p>
      </div>

      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title={mode === "login" ? "이메일로 로그인" : "이메일로 가입"}
      >
        <form onSubmit={submit} className="flex flex-col gap-3">
          {error && <ErrorInline message={error} />}
          {mode === "signup" && (
            <Field label="이름" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
          )}
          <Field label="이메일" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
          <Field
            label="비밀번호"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={mode === "signup" ? 6 : undefined}
            required
          />
          <Button type="submit" loading={busy}>
            {mode === "login" ? "로그인" : "가입하고 시작하기"}
          </Button>
          <button
            type="button"
            onClick={() => {
              setMode(mode === "login" ? "signup" : "login");
              setError(null);
            }}
            className={`min-h-11 text-[13px] font-medium text-primary ${focusRing}`}
          >
            {mode === "login" ? "처음이에요 · 가입하기" : "이미 계정이 있어요 · 로그인"}
          </button>
        </form>
      </Sheet>
    </Screen>
  );
}
