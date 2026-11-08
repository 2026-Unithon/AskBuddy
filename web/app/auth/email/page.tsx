"use client";
import { Suspense, useState, type InputHTMLAttributes } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Shell } from "@/components/ui";
import { BackButton, Button, TextButton } from "@/components/kit";
import { ApiError, apiErrorMessage, login, signup } from "@/lib/api";
import { useApp } from "@/lib/store";
import { LoginLoading, LoginRetry, useLoginDestination } from "@/components/login-session";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** 칸 하나: 보이는 이름, 칸 아래 빨간 글(a02a). 오류면 aria-invalid 와 빨간 테두리. */
function Field({ id, label, error, ...input }: { id: string; label: string; error?: string | null } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="px-1 text-[14px] font-bold text-ink">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`min-h-12 rounded-[14px] bg-surface px-4 text-[16px] text-ink shadow-card outline-none focus:ring-2 ${
          error ? "ring-2 ring-danger-500 focus:ring-danger-500" : "focus:ring-primary"
        }`}
        {...input}
      />
      {error && (
        <p id={`${id}-error`} role="alert" className="px-1 text-[13px] font-semibold text-danger-700">
          {error}
        </p>
      )}
    </div>
  );
}

function Email() {
  const next = useSearchParams().get("next");
  const { dispatch } = useApp();
  const session = useLoginDestination(next);
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  // 칸을 떠났거나 보내려 했을 때부터 형식 오류를 보인다(입력 중에는 재촉하지 않는다)
  const [touched, setTouched] = useState({ name: false, email: false, password: false });
  const auth = useMutation({
    mutationFn: () => (mode === "login" ? login(email, password) : signup({ name, email, password })),
    onSuccess: (s) => {
      queryClient.clear();
      dispatch({ type: "SET_AUTH", token: s.token, role: s.user.role, userId: s.user.user_id, storeId: s.user.store_id ?? null });
    },
  });
  if (session.error) return <LoginRetry retry={session.retry} />;
  if (!session.state.hydrated || session.state.token) return <LoginLoading />;

  const emailFormat = EMAIL.test(email.trim()) ? null : "이메일 형식을 확인해 주세요";
  const passwordFormat = password.length >= 6 ? null : "비밀번호는 6자 이상이에요";
  const nameFormat = mode === "signup" && !name.trim() ? "이름을 적어 주세요" : null;
  const serverError = auth.error;
  const wrongPassword = serverError instanceof ApiError && serverError.status === 401;
  const taken = serverError instanceof ApiError && serverError.status === 409;
  const emailError = touched.email ? emailFormat : null;
  const passwordError = (touched.password ? passwordFormat : null) ?? (wrongPassword ? "이메일 또는 비밀번호를 확인해 주세요." : null);

  return (
    <main className="flex flex-1 flex-col gap-6 px-6 pb-10 pt-4">
      <BackButton parent="/" />
      <form
        noValidate
        className="flex flex-1 flex-col justify-center gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          setTouched({ name: true, email: true, password: true });
          if (nameFormat || emailFormat || passwordFormat || auth.isPending) return;
          auth.mutate();
        }}
      >
        <h1 className="text-[26px] font-bold leading-[1.35] tracking-[-0.52px] text-ink">
          {mode === "login" ? "이메일로 시작해요" : "처음 오셨군요, 반가워요"}
        </h1>
        {mode === "signup" && (
          <Field
            id="name"
            label="이름"
            value={name}
            maxLength={50}
            autoComplete="name"
            error={touched.name ? nameFormat : null}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, name: true }))}
          />
        )}
        <Field
          id="email"
          label="이메일"
          type="email"
          autoComplete="email"
          value={email}
          error={emailError ?? (taken ? "이미 가입된 이메일입니다. 로그인해 주세요." : null)}
          onChange={(e) => {
            setEmail(e.target.value);
            if (auth.error) auth.reset();
          }}
          onBlur={() => setTouched((t) => ({ ...t, email: true }))}
        />
        <Field
          id="password"
          label="비밀번호"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          value={password}
          maxLength={72}
          error={passwordError}
          onChange={(e) => {
            setPassword(e.target.value);
            if (auth.error) auth.reset();
          }}
          onBlur={() => setTouched((t) => ({ ...t, password: true }))}
        />
        <Button type="submit" loading={auth.isPending}>
          {mode === "login" ? "로그인" : "가입하기"}
        </Button>
        {serverError && !wrongPassword && !taken && (
          <p role="alert" className="text-[13px] font-semibold text-danger-700">
            {apiErrorMessage(serverError, "가입 또는 로그인에 실패했어요.")}
          </p>
        )}
        <TextButton
          className="self-center"
          disabled={auth.isPending}
          onClick={() => {
            auth.reset();
            setTouched({ name: false, email: false, password: false });
            setMode(mode === "login" ? "signup" : "login");
          }}
        >
          {mode === "login" ? "처음이신가요? 가입하기" : "이미 계정이 있어요"}
        </TextButton>
      </form>
    </main>
  );
}
export default function Page() {
  return (
    <Shell>
      <Suspense fallback={<LoginLoading />}>
        <Email />
      </Suspense>
    </Shell>
  );
}
