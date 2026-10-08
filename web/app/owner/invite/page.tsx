"use client";
import { ButtonLink, PageHeader, Screen } from "@/components/kit";
import { InviteLinkCard } from "@/components/invite-link-card";
export default function OwnerInvitePage() {
  return <Screen footer={<ButtonLink href="/owner" variant="secondary">매장으로 돌아가기</ButtonLink>}>
    <PageHeader title="첫 준비 끝났어요" description="초대 링크를 보내고 직원의 합류 요청을 승인해 주세요." />
    <InviteLinkCard />
    <ButtonLink href="/owner/members" variant="secondary">직원 관리 · 합류 승인</ButtonLink>
  </Screen>;
}
