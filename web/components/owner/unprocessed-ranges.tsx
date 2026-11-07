"use client";

import { Button, ButtonLink, Caption } from "@/components/kit";
import type { IngestJobDetail, UnprocessedRange } from "@/lib/api";

type JobSource = IngestJobDetail["sources"][number];

const REASON: Record<UnprocessedRange["reason"], string> = {
  TRUNCATED: "정리하다가 끊겼어요",
  CALL_FAILED: "정리하는 중에 오류가 났어요",
  EMPTY: "내용을 읽지 못했어요",
};

// 조사까지 붙여 돌려준다 — "이 자료를" / "31~67줄(「…」부터)을"
function where(range: UnprocessedRange) {
  if (range.from_line === 0) return "이 자료를";
  const lines = range.from_line === range.to_line ? `${range.from_line}줄` : `${range.from_line}~${range.to_line}줄`;
  return range.first_line ? `${lines}(「${range.first_line}…」부터)을` : `${lines}을`;
}

/** 정리하지 못한 줄 범위(S9). 정리된 카드는 그대로 두고 이 부분만 따로 알린다.
 *  [다시 시도]는 범위마다 한 번(서버가 최대 3번 시도). 쓴 뒤에도 남으면 [직접 적기]만 보인다(S10). */
export function UnprocessedRanges({
  sources,
  onRetry,
  retrying,
}: {
  sources: JobSource[];
  onRetry: () => void;
  retrying: boolean;
}) {
  const withRanges = sources.filter((s) => (s.unprocessed_ranges ?? []).length > 0 && s.source_availability !== "DELETED");
  if (withRanges.length === 0) return null;
  const canRetry = withRanges.some((s) => (s.unprocessed_ranges ?? []).some((r) => !r.owner_retry_used));
  return (
    <section data-testid="unprocessed-ranges" className="flex flex-col gap-3 rounded-[20px] bg-warn-50 px-[18px] py-4">
      <p className="text-[15px] font-bold text-ink">일부를 정리하지 못했어요</p>
      <Caption>정리된 내용은 카드로 반영했어요. 아래 부분만 다시 확인해 주세요.</Caption>
      <ul className="flex flex-col gap-2">
        {withRanges.map((source) => (
          <li key={source.source_id} className="flex flex-col gap-1">
            <span className="truncate text-[14px] font-medium text-ink">{source.filename}</span>
            {(source.unprocessed_ranges ?? []).map((range) => (
              <span key={`${range.from_line}-${range.to_line}`} data-testid="unprocessed-range" className="text-[13px] text-ink-muted">
                {where(range)} 정리하지 못했어요 · {REASON[range.reason]}({range.attempts}번 시도)
              </span>
            ))}
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        {canRetry && (
          <Button variant="secondary" className="flex-1 py-[11px] text-[14px]" loading={retrying} disabled={retrying} onClick={onRetry}>
            다시 시도
          </Button>
        )}
        <ButtonLink href="/owner/add" variant="secondary" className="flex-1 py-[11px] text-[14px]">
          직접 적기
        </ButtonLink>
      </div>
    </section>
  );
}
