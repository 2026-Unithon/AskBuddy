import { redirect } from "next/navigation";

// 옛 업로드 화면. 서버 기본 목적지(첫 카드 승인 전 점주)가 아직 이 주소라 새 아무거나 넣기(O3)로 넘긴다.
export default function OwnerUploadPage() {
  redirect("/owner/add");
}
