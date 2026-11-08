// 카드 '확인해 주세요' 사유. 서버(api/app/ingest/fact_cards.py)는 코드로 저장하므로 화면에서 사람 말로 바꾼다.
// 코드가 아닌 문장(사람이 쓴 사유)은 그대로 보인다.
const REASONS: Record<string, string> = {
  FACT_CONFLICT_OPEN: "같은 항목에 서로 다른 값이 있어요. 맞는 값을 골라 주세요.",
  NO_PROVENANCE: "어느 자료에서 나온 내용인지 확인하지 못했어요.",
  REASSEMBLY_SUPERSEDED: "새로 올린 자료로 내용이 바뀌었어요. 다시 봐 주세요.",
  NEW_FACTS: "공개된 카드에 새 내용이 더해졌어요. 확인해 주세요.",
};
const FALLBACK = "자동으로 정리하지 못한 부분이 있어요. 내용을 확인해 주세요.";
const GENERIC = "내용이 확실하지 않아요. 확인해 주세요.";

export function reviewReasonText(reason: string | null | undefined): string {
  if (!reason) return GENERIC;
  if (REASONS[reason]) return REASONS[reason];
  if (reason.startsWith("FALLBACK:")) return FALLBACK;
  // 대문자·밑줄로만 된 처음 보는 코드는 그대로 보이지 않는다
  if (/^[A-Z0-9_:]+$/.test(reason)) return GENERIC;
  return reason;
}
