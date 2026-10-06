import { BackButton, PageHeader, Screen } from "@/components/kit";
import { OwnerAddComposer } from "@/components/owner/owner-add-composer";

// O3 아무거나 넣기. 넣으면 작업 화면(O4)으로 넘어간다 — 추출 진행은 서버 작업 상태가 정본이다.
export default function OwnerAddPage() {
  return (
    <Screen footer={<OwnerAddComposer placeholder="여기에 말하거나 붙여넣기" />}>
      <BackButton href="/owner" />
      <PageHeader
        title="알려주고 싶은 걸 아무거나 넣어주세요"
        description="레시피, 마감할 일, 공지… 찍거나 파일로 넣으면 레시피와 오늘 할 일로 알아서 나눠요"
      />
      <p className="w-full rounded-[18px] bg-empty px-[18px] py-4 text-[13px] leading-[1.45] tracking-[-0.13px] text-ink [word-break:keep-all]">
        예) &ldquo;바닐라라떼는 얼음 가득, 시럽 2펌프, 우유 200에 샷 2개. 마감 때는 머신 청소랑 원두 소분, 쓰레기 정리&rdquo;
      </p>
    </Screen>
  );
}
