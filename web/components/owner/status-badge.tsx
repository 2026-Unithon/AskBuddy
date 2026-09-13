"use client";

import { Badge } from "@/components/ui";

export function CardStatusBadge({ status }: { status: string }) {
  switch (status) {
    case "APPROVED":
      return <Badge tone="brand">✓ 공개됨</Badge>;
    case "NEEDS_REVIEW":
      return <Badge tone="danger">⚠ 검토 필요</Badge>;
    case "EXCLUDED":
      return <Badge tone="neutral">✕ 제외됨</Badge>;
    case "PENDING":
    default:
      return <Badge tone="warn">⏳ 미확인</Badge>;
  }
}

export function JobStatusBadge({ status }: { status: string }) {
  switch (status) {
    case "SUCCEEDED":
      return <Badge tone="brand">✓ 완료</Badge>;
    case "PARTIAL":
      return <Badge tone="warn">⚠ 일부 완료</Badge>;
    case "NO_RESULT":
      return <Badge tone="neutral">내용 없음</Badge>;
    case "FAILED":
      return <Badge tone="danger">✕ 실패</Badge>;
    case "EXTRACTING":
      return <Badge tone="brand">업무 추출 중…</Badge>;
    case "CLASSIFYING":
      return <Badge tone="brand">분류 중…</Badge>;
    case "QUEUED":
    default:
      return <Badge tone="neutral">대기 중…</Badge>;
  }
}

export function QuestionStatusBadge({ status }: { status: string }) {
  switch (status) {
    case "WAITING":
      return <Badge tone="warn">대기 중</Badge>;
    case "OWNER_ANSWERED":
      return <Badge tone="brand">사장님 답변</Badge>;
    case "HIT":
    default:
      return <Badge tone="neutral">지식 답변</Badge>;
  }
}

