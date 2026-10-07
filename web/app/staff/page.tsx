import { redirect } from "next/navigation";

// 직원 첫 탭 "오늘 할 일"(체크리스트)은 P5에서 만든다. 그 전까지는 레시피 탭으로 보낸다.
export default function StaffHomePage() {
  redirect("/staff/recipes");
}
