import { redirect } from "next/navigation";

// 자주 묻는 질문 화면은 버디 입력창 위 추천 질문 칩으로 옮겼다(NAV-6, s05a). 옛 주소는 버디로 넘긴다.
export default function StaffFaqPage() {
  redirect("/staff/ask");
}
