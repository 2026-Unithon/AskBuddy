"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Badge, Buddy, Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { roadmapQuery } from "@/lib/query";
import { useApp } from "@/lib/store";

function message(error: unknown) {
  return error instanceof ApiError ? error.detail || "로드맵을 불러오지 못했어요." : "서버에 연결할 수 없습니다.";
}

export default function RoadmapPage() {
  const { state } = useApp();
  const roadmap = useQuery(roadmapQuery(state.token, state.storeId, state.userId));
  const counts = roadmap.data?.counts;
  const progress = counts?.total ? Math.round((counts.done / counts.total) * 100) : 0;

  return (
    <div className="min-h-dvh w-full bg-background">
      <header className="bg-brand-700 px-5 pb-6 pt-7 text-white">
        <div className="mx-auto max-w-2xl">
          <div className="flex items-center gap-3"><Buddy size={48} /><div><p className="text-xs text-white/65">{state.displayName ?? "직원"}님의 학습</p><h1 className="text-xl font-bold">{roadmap.data?.store.name ?? state.storeName}</h1></div><Link href="/role" className="ml-auto flex min-h-11 items-center text-xs font-semibold text-white/70">나가기</Link></div>
          <div className="mt-5"><div className="flex justify-between text-xs font-bold"><span>전체 진도</span><span>{progress}%</span></div><div className="mt-2 h-3 overflow-hidden rounded-full bg-white/20"><div className="h-full rounded-full bg-accent-500 transition-all" style={{ width: `${progress}%` }} /></div></div>
        </div>
      </header>
      <main className="mx-auto max-w-2xl space-y-5 px-5 py-5">
        <div className="grid grid-cols-2 gap-3"><Link href="/staff/chat" className="flex min-h-14 items-center justify-center gap-2 rounded-2xl bg-brand-500 text-sm font-bold text-white">💬 Buddy에게 질문</Link><Link href="/staff/faqs" className="flex min-h-14 items-center justify-center gap-2 rounded-2xl border border-border bg-surface text-sm font-bold text-brand-700">❓ 자주 묻는 질문</Link></div>
        {counts && counts.reconfirm_required > 0 && <Card className="border-accent-500/40 bg-accent-50 p-4 text-sm"><strong>{counts.reconfirm_required}개 내용이 바뀌었어요.</strong><p className="mt-1 text-xs text-muted">최신 내용을 다시 확인하면 완료 상태를 갱신할 수 있어요.</p></Card>}
        {roadmap.isFetching && !roadmap.isLoading && <p className="text-[11px] text-muted">최신 진도 확인 중…</p>}
        {roadmap.isLoading && <div className="space-y-3" aria-label="로드맵 불러오는 중">{[0, 1, 2].map((item) => <div key={item} className="h-36 animate-pulse rounded-2xl bg-surface-muted" />)}</div>}
        {roadmap.error && <Card className="space-y-3 p-5 text-center"><p role="alert" className="text-sm text-danger-500">{message(roadmap.error)}</p><Button variant="secondary" onClick={() => void roadmap.refetch()}>다시 시도</Button></Card>}
        {!roadmap.isLoading && !roadmap.error && (counts?.total ?? 0) === 0 && <Card className="space-y-2 p-6 text-center"><p className="text-sm font-bold">아직 공개된 학습 카드가 없어요.</p><p className="text-xs text-muted">사장님이 카드를 공개하면 업무별로 여기에 나타납니다.</p></Card>}
        {roadmap.data?.stages.map((stage) => (
          <section key={stage.category_id} className="space-y-2" aria-labelledby={`stage-${stage.category_id}`}>
            <h2 id={`stage-${stage.category_id}`} className="text-sm font-bold text-brand-700">{stage.name}</h2>
            {stage.items.map((item) => (
              <Link key={item.item_id} href={`/staff/items/${item.item_id}`} className="block">
                <Card className="flex min-h-16 items-center gap-3 p-4 transition-colors hover:bg-brand-50">
                  <span className="text-xl" aria-hidden>{item.status === "DONE" ? "✅" : item.status === "RECONFIRM_REQUIRED" ? "🔄" : "📖"}</span>
                  <span className="min-w-0 flex-1 text-sm font-semibold">{item.title}</span>
                  <Badge tone={item.status === "DONE" ? "brand" : item.status === "RECONFIRM_REQUIRED" ? "warn" : "neutral"}>{item.status === "DONE" ? "완료" : item.status === "RECONFIRM_REQUIRED" ? "다시 확인" : "시작"}</Badge>
                  <span className="text-muted" aria-hidden>→</span>
                </Card>
              </Link>
            ))}
          </section>
        ))}
      </main>
    </div>
  );
}
