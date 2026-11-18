"use client";

// 사실 근거 표시 도움말: 규격 이름·근거 자료 이름.
import type { FactOrigin, FactVariant } from "@/lib/api";

export function variantLabel(variant: FactVariant): string {
  const parts = [variant.temperature, variant.size].filter(Boolean);
  return parts.length > 0 ? parts.join(" ") : "규격 표시 없음";
}

/** 페이지 맨 아래 근거 자료 한 줄(o06c). 이름은 중복 없이, 원본이 지워졌으면 표시. */
export function evidenceNames(origins: FactOrigin[]): string[] {
  const names = origins.map((origin) => {
    if (origin.kind === "OWNER_ANSWER") return "사장님 답변";
    if (origin.kind === "OWNER_TEXT") return "사장님 직접 입력";
    const name = origin.source_title ?? "자료";
    return origin.source_availability === "DELETED" ? `${name} (원본 지워짐)` : name;
  });
  return [...new Set(names)];
}
