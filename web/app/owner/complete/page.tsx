import { redirect } from "next/navigation";

// 옛 온보딩 완료 화면. 새 초대 화면(O5)으로 넘긴다.
export default function OwnerCompletePage() {
  redirect("/owner/invite");
}
