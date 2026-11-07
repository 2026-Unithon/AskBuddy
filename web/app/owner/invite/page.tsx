"use client";
import { ButtonLink, Icon, PageHeader, Screen } from "@/components/kit";
import { InviteLinkCard } from "@/components/invite-link-card";

/** 첫 준비 끝(o19a). 끝의 기억을 좋게(피크엔드): 축하 체크가 튀어 오른다. */
export default function OwnerInvitePage() {
  return (
    <Screen footer={<ButtonLink href="/owner" variant="secondary">매장으로 돌아가기</ButtonLink>}>
      <div
        data-celebrate=""
        aria-hidden
        className="mx-auto mt-4 flex size-20 items-center justify-center rounded-full bg-primary text-white shadow-primary animate-[check-pop_400ms_var(--ease-spring)]"
      >
        <Icon name="check" size={40} />
      </div>
      <PageHeader title="첫 준비 끝났어요" />
      <InviteLinkCard />
      <ButtonLink href="/owner/members" variant="secondary">직원 관리</ButtonLink>
    </Screen>
  );
}
