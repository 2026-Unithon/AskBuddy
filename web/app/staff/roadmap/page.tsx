import { redirect } from "next/navigation";

// 옛 학습(로드맵) 주소. 서버 기본 목적지·학습 상세의 return_to 가 아직 이 주소를 가리켜서 레시피 탭으로 넘긴다.
export default function StaffRoadmapPage() {
  redirect("/staff/recipes");
}
