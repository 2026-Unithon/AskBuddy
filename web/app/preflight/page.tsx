"use client";

import { useCallback, useEffect, useState } from "react";

// 배선 점검. 기능을 짜기 전에, 배포한 뒤에 여기 줄들이 전부 초록이어야 한다.
// 이 화면은 매장 데이터를 다루지 않으므로 인증 가드 밖(app/preflight)에 둔다.

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type State = "live" | "warn" | "dead";

type Check = {
  name: string;
  state: State;
  detail: string;
  fix: string;
  ms: number | null;
};

type Report = {
  ok: boolean;
  deep: boolean;
  env: string;
  blocking: string[];
  settings: Record<string, string | number>;
  checks: Check[];
};

const DOT: Record<State, string> = {
  live: "bg-brand-500",
  warn: "bg-warn-500",
  dead: "bg-danger-500",
};
const LABEL: Record<State, string> = {
  live: "연결됨",
  warn: "미확인",
  dead: "끊김",
};

export default function PreflightPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const probe = useCallback(async (deep: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API}/preflight${deep ? "?deep=1" : ""}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setReport((await res.json()) as Report);
    } catch (e) {
      setReport(null);
      // 여기서 실패하면 백엔드에 닿지 못한 것이다 — CORS 아니면 주소 문제다
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void probe(false);
  }, [probe]);

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <header className="mb-8">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted">preflight</p>
        <h1 className="mt-2 text-2xl font-bold text-brand-700">배선 점검</h1>
        <p className="mt-2 text-sm text-muted">
          기능을 짜기 전에, 배포한 뒤에 이 줄들이 전부 초록이어야 한다.
        </p>
        <p className="mt-1 font-mono text-xs text-muted">{API}</p>
      </header>

      {/* 프론트가 백엔드에 닿지도 못한 경우 — 나머지는 판단할 수 없다 */}
      {error && (
        <div className="mb-5 rounded-2xl bg-danger-50 px-4 py-3 text-danger-700">
          <p className="text-sm font-bold">백엔드에 닿지 못했습니다 — {error}</p>
          <ul className="mt-2 list-disc pl-5 text-xs leading-relaxed">
            <li>api 서버가 떠 있는지</li>
            <li>
              Vercel 의 <code className="font-mono">NEXT_PUBLIC_API_URL</code> 이 Railway 주소와
              같은지
            </li>
            <li>
              Railway 의 <code className="font-mono">ALLOWED_ORIGINS</code> 에 이 페이지 도메인이
              들어 있는지 (CORS)
            </li>
          </ul>
        </div>
      )}

      {report && (
        <div
          className={`mb-5 rounded-2xl px-4 py-3 ${
            report.ok ? "bg-brand-50 text-brand-700" : "bg-danger-50 text-danger-700"
          }`}
        >
          <p className="text-sm font-bold">
            {report.ok
              ? `전부 연결됐습니다 (env=${report.env})`
              : `막는 항목 ${report.blocking.length}개 — ${report.blocking.join(", ")}`}
          </p>
        </div>
      )}

      <section className="rounded-2xl bg-surface px-5 py-1 shadow-sm">
        <ul>
          <Row
            name="프론트엔드"
            state="live"
            detail="Next.js 렌더링 정상"
            fix=""
            ms={null}
          />
          {report?.checks.map((c) => <Row key={c.name} {...c} />)}
          {!report && !error && (
            <li className="py-4 text-sm text-muted">점검 중…</li>
          )}
        </ul>
      </section>

      <div className="mt-4 flex gap-2">
        <button
          onClick={() => probe(false)}
          disabled={busy}
          className="rounded-full border border-border px-4 h-10 text-sm font-semibold disabled:opacity-40"
        >
          {busy ? "점검 중…" : "다시 점검"}
        </button>
        <button
          onClick={() => probe(true)}
          disabled={busy}
          className="rounded-full bg-brand-600 px-4 h-10 text-sm font-semibold text-white disabled:opacity-40"
        >
          LLM 까지 실호출
        </button>
      </div>
      <p className="mt-2 text-xs text-muted">
        &quot;LLM 까지&quot; 는 OpenAI·Gemini 를 한 번씩 실제로 부른다. 요금이 든다.
      </p>

      {report && (
        <section className="mt-8">
          <h2 className="text-sm font-bold text-brand-700">현재 설정</h2>
          <dl className="mt-2 rounded-2xl bg-surface px-5 py-3 shadow-sm">
            {Object.entries(report.settings).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 border-b border-border py-1.5 last:border-0">
                <dt className="font-mono text-xs text-muted">{k}</dt>
                <dd className="font-mono text-xs">{String(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
    </main>
  );
}

function Row({ name, state, detail, fix, ms }: Check) {
  return (
    <li className="flex gap-3 border-b border-border py-3 last:border-0">
      <span
        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[state]} ${
          state === "warn" ? "animate-pulse" : ""
        }`}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-sm font-semibold">{name}</span>
          <span className="font-mono text-xs text-muted">
            {LABEL[state]}
            {ms ? ` · ${ms}ms` : ""}
          </span>
        </div>
        {detail && <p className="mt-0.5 break-all font-mono text-xs text-muted">{detail}</p>}
        {state !== "live" && fix && (
          <p className={`mt-1 text-xs ${state === "dead" ? "text-danger-700" : "text-warn-700"}`}>
            → {fix}
          </p>
        )}
      </div>
    </li>
  );
}
