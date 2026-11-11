import { BackButton, PageHeader, Screen } from "@/components/kit";

/** 개인정보 처리방침. 로그인 없이 읽는다. 본문은 계획 8 Task 9(운영자 값 받은 뒤)에서 docs/dev/legal 초안을 그린다 */
export default function PrivacyPage() {
  return (
    <Screen>
      <BackButton parent="/" />
      <PageHeader title="개인정보 처리방침" />
    </Screen>
  );
}
