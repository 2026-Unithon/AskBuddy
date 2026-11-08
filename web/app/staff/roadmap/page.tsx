import { redirect } from "next/navigation";

// 옛 학습(로드맵) 주소. 예전에 받은 알림·북마크가 이 주소를 가리킬 수 있어 레시피 탭으로 넘긴다.
export default function StaffRoadmapPage() {
  redirect("/staff/recipes");
}
