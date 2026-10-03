"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiErrorMessage, getPreflight, opsLogin, type PreflightReport } from "@/lib/api";
import { setOpsToken, useOpsToken, withOpsSession } from "@/lib/ops-session";
import { preflightQuery } from "@/lib/query";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Check = PreflightReport["checks"][number];
const DOT: Record<Check["state"], string> = { live: "bg-brand-500", warn: "bg-warn-500", dead: "bg-danger-500" };
const LABEL: Record<Check["state"], string> = { live: "연결됨", warn: "미확인", dead: "끊김" };

export default function PreflightPage() {
  const token = useOpsToken();
  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <header className="mb-8"><Link href="/" aria-label="뒤로가기" className="mb-4 inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-sm font-semibold text-muted hover:bg-surface-muted hover:text-foreground">← 처음으로</Link><p className="font-mono text-xs uppercase tracking-[0.2em] text-muted">preflight</p><h1 className="mt-2 text-2xl font-bold text-brand-700">배선 점검</h1><p className="mt-2 text-sm text-muted">운영자 전용 화면입니다. 배포한 뒤에 이 줄들이 전부 초록이어야 합니다.</p><p className="mt-1 font-mono text-xs text-muted">{API}</p></header>
      {token ? <Diagnostics token={token} /> : <OperatorLogin />}
    </main>
  );
}

function loginErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return "이메일 또는 비밀번호가 맞지 않습니다.";
  if (error instanceof ApiError && error.status === 422) return "이메일 또는 비밀번호 형식을 확인해주세요.";
  if (error instanceof ApiError && error.status === 429) return "실패가 반복돼 잠시 막혔습니다. 15분 뒤 다시 시도해주세요.";
  return apiErrorMessage(error, "로그인하지 못했습니다.");
}

function OperatorLogin() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => opsLogin(email.trim(), password),
    onSuccess: (result) => setOpsToken(result.token),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!login.isPending) login.mutate();
  }
  return (
    <form onSubmit={submit} className="rounded-2xl bg-surface px-5 py-5 shadow-sm">
      <h2 className="text-sm font-bold text-brand-700">운영자 로그인</h2>
      <label className="mt-4 block text-xs font-semibold text-muted" htmlFor="ops-email">이메일</label>
      <input id="ops-email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 h-11 w-full rounded-lg border border-border px-3 text-sm" />
      <label className="mt-3 block text-xs font-semibold text-muted" htmlFor="ops-password">비밀번호</label>
      <input id="ops-password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 h-11 w-full rounded-lg border border-border px-3 text-sm" />
      {login.error && <p role="alert" className="mt-3 text-sm text-danger-700">{loginErrorMessage(login.error)}</p>}
      <button type="submit" disabled={login.isPending} className="mt-4 h-11 w-full rounded-full bg-brand-600 text-sm font-semibold text-white disabled:opacity-40">{login.isPending ? "확인 중…" : "로그인"}</button>
    </form>
  );
}

function Diagnostics({ token }: { token: string }) {
  const queryClient = useQueryClient();
  const shallow = useQuery(preflightQuery(token));
  const deep = useMutation({ mutationFn: () => withOpsSession(() => getPreflight(true, token)) });
  const report = deep.data ?? shallow.data;
  const error = deep.error ?? shallow.error;
  const busy = deep.isPending || shallow.isFetching;
  function logout() {
    queryClient.removeQueries({ queryKey: preflightQuery(token).queryKey });
    setOpsToken(null);
  }
  return (
    <>
      {error && <div className="mb-5 rounded-2xl bg-danger-50 px-4 py-3 text-danger-700"><p className="text-sm font-bold">백엔드에 닿지 못했습니다 — {error instanceof Error ? error.message : "연결 오류"}</p><ul className="mt-2 list-disc pl-5 text-xs leading-relaxed"><li>API 서버 상태</li><li>웹 배포의 NEXT_PUBLIC_API_URL</li><li>API 서버의 ALLOWED_ORIGINS 설정</li></ul></div>}
      {report && <div className={`mb-5 rounded-2xl px-4 py-3 ${report.ok ? "bg-brand-50 text-brand-700" : "bg-danger-50 text-danger-700"}`}><p className="text-sm font-bold">{report.ok ? `전부 연결됐습니다 (env=${report.env})` : `막는 항목 ${report.blocking.length}개 — ${report.blocking.join(", ")}`}</p></div>}
      <section className="rounded-2xl bg-surface px-5 py-1 shadow-sm"><ul><Row name="프론트엔드" state="live" detail="Next.js 렌더링 정상" fix="" ms={null} />{report?.checks.map((check) => <Row key={check.name} {...check} />)}{!report && !error && <li className="py-4 text-sm text-muted">점검 중…</li>}</ul></section>
      <div className="mt-4 flex flex-wrap gap-2"><button onClick={() => void shallow.refetch()} disabled={busy} className="h-11 rounded-full border border-border px-4 text-sm font-semibold disabled:opacity-40">{shallow.isFetching ? "점검 중…" : "다시 점검"}</button><button onClick={() => deep.mutate()} disabled={busy} className="h-11 rounded-full bg-brand-600 px-4 text-sm font-semibold text-white disabled:opacity-40">{deep.isPending ? "실호출 중…" : "LLM까지 실호출"}</button><button onClick={logout} className="h-11 rounded-full px-4 text-sm font-semibold text-muted hover:bg-surface-muted">로그아웃</button></div><p className="mt-2 text-xs text-muted">LLM 실호출은 OpenAI·Gemini를 한 번씩 호출하므로 요금이 발생합니다.</p>
      {report && <section className="mt-8"><h2 className="text-sm font-bold text-brand-700">현재 설정</h2><dl className="mt-2 rounded-2xl bg-surface px-5 py-3 shadow-sm">{Object.entries(report.settings).map(([key, value]) => <div key={key} className="flex justify-between gap-4 border-b border-border py-1.5 last:border-0"><dt className="font-mono text-xs text-muted">{key}</dt><dd className="font-mono text-xs">{String(value)}</dd></div>)}</dl></section>}
    </>
  );
}

function Row({ name, state, detail, fix, ms }: Check) {
  return <li className="flex gap-3 border-b border-border py-3 last:border-0"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[state]} ${state === "warn" ? "motion-safe:animate-pulse" : ""}`} aria-hidden /><div className="min-w-0 flex-1"><div className="flex items-center justify-between gap-3"><p className="text-sm font-semibold">{name}</p><span className="text-xs font-bold text-muted">{LABEL[state]}{ms !== null ? ` · ${ms}ms` : ""}</span></div><p className="mt-0.5 text-xs text-muted">{detail}</p>{fix && <p className="mt-1 text-xs text-danger-500">{fix}</p>}</div></li>;
}
