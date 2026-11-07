import { redirect } from "next/navigation";

// 옛 '이전 대화 이력' 주소. 할 수 있는 게 없는 화면이라 버디로 넘긴다(NAV-12).
export default function ChatHistoryPage() {
  redirect("/staff/ask");
}
