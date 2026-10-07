import { redirect } from "next/navigation";

// 옛 R v2 화면 주소. 알림·Push 딥링크(/owner/questions/v2?question_id=…)가 이미 저장돼 있어서 지우지 않고 새 화면으로 넘긴다.
export default async function Page({ searchParams }: PageProps<"/owner/questions/v2">) {
  const { question_id: questionId } = await searchParams;
  const id = Array.isArray(questionId) ? questionId[0] : questionId;
  redirect(id ? `/owner/questions/${encodeURIComponent(id)}` : "/owner");
}
