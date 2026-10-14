import type { RCitation } from "@/lib/r-v2-api";

export function CitationOrigin({ citation }: { citation: RCitation }) {
  const kinds = { OWNER_ANSWER: "점주 답변", OWNER_TEXT: "사장님 직접 입력", SOURCE: "매장 자료", UNKNOWN: "출처 종류 확인 불가" };
  const sources: Record<string, string> = { VOICE: "음성 자료", VIDEO: "영상 자료", KAKAO: "메시지 자료", SCAN: "문서·사진 자료" };
  const label = citation.source_kind === "SOURCE" ? sources[citation.source_type ?? ""] ?? kinds.SOURCE
    : kinds[citation.source_kind] ?? (citation.owner_answer_id ? kinds.OWNER_ANSWER : kinds.UNKNOWN);
  const positions = Array.from(new Set((citation.source_locations ?? []).flatMap(({ locator }) => {
    if (locator.line != null) return [`${locator.line}번째 줄`];
    if (locator.page != null) return [`${locator.page}페이지`];
    if (locator.timestamp_sec != null) return [`${Math.floor(locator.timestamp_sec / 60)}분 ${locator.timestamp_sec % 60}초`];
    return [];
  })));
  return <>
    <p data-testid="citation-origin" className="mt-1 text-ink-muted">출처 · {label}{positions.length > 0 ? ` · ${positions.join(", ")}` : ""}</p>
    {citation.source_availability !== "AVAILABLE" && <p className="mt-1 text-ink-muted">원본 자료를 열람할 수 없어요. 당시 승인된 내용은 그대로 남아 있어요.</p>}
  </>;
}
