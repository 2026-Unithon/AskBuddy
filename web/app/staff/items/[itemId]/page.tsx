import { redirect } from "next/navigation";

// 옛 학습 상세 주소. 같은 항목의 레시피 보기로 넘긴다.
export default async function StaffItemPage({ params }: PageProps<"/staff/items/[itemId]">) {
  const { itemId } = await params;
  redirect(`/staff/recipes/${encodeURIComponent(itemId)}`);
}
