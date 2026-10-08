import type { Metadata } from "next";
import { JoinClient } from "./join-client";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function storeName(token: string): Promise<string | null> {
  try {
    const res = await fetch(`${API}/auth/invites/${encodeURIComponent(token)}`, { cache: "no-store" });
    if (!res.ok) return null;
    return ((await res.json()) as { store_name: string }).store_name;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ token: string }> }): Promise<Metadata> {
  const { token } = await params;
  const name = await storeName(token);
  const title = name ? `${name}에서 초대했어요 · AskBuddy` : "AskBuddy 초대";
  const description = name ? "눌러서 매장에 합류하세요. 사장님이 승인하면 바로 시작해요." : "초대 링크를 확인해 주세요.";
  return {
    title,
    description,
    // 토큰이 든 주소가 검색에 노출되지 않게 한다
    robots: { index: false, follow: false },
    openGraph: { title, description, images: ["/images/buddy-hero.png"], type: "website" },
  };
}

export default async function JoinPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <JoinClient inviteToken={token} />;
}
