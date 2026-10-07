import { redirect } from "next/navigation";

// 옛 R v2 대화 주소. 답 도착 알림(/staff/chat/v2?session_id=…)이 이미 저장돼 있어서 새 화면으로 넘긴다.
export default async function Page({ searchParams }: PageProps<"/staff/chat/v2">) {
  const { session_id: sessionId } = await searchParams;
  const id = Array.isArray(sessionId) ? sessionId[0] : sessionId;
  redirect(id ? `/staff/ask?session_id=${encodeURIComponent(id)}` : "/staff/ask");
}
