// W3b 사실 카드 화면 문구. 오류 코드 → 쉬운 한국어 한 문장 (w3b common §8).
import { ApiError, apiErrorMessage } from "@/lib/api";

const CANNOT_SAVE = "이 변경은 저장할 수 없어요. 새로고침 뒤 다시 시도해 주세요.";
const ENTITY_MOVED = "메뉴 정리가 바뀌어 이 카드에서 고칠 수 없어요.";
export const FACT_EDIT_DISABLED_TEXT = "사실 단위 고치기는 아직 열리지 않았어요.";
export const VALUE_CLEAR_TEXT = "값을 지우려면 이 사실을 빼고 새로 넣어 주세요.";
export const PARSE_FAILED_TEXT = "분석하지 못했어요. 다시 시도해 주세요. (입력은 그대로 둬요)";
export const NO_FACT_TEXT = "사실을 찾지 못했어요. 문장을 조금 더 구체적으로 써 주세요.";
export const STEP_ORDER_TEXT = "순서 단계 번호가 앞뒤 단계와 맞지 않아요. 넣은 단계를 위로·아래로 옮겨 알맞은 자리에 둔 뒤 다시 저장해 주세요.";
export const CARD_EXCLUDED_TEXT = "이 카드는 그사이 지워졌어요. 다시 살린 뒤 고쳐 주세요.";

const SAVE_MESSAGES: Record<string, string> = {
  CARD_VERSION_CONFLICT: "그사이 카드가 바뀌었어요. 최신 내용을 불러온 뒤 다시 고쳐 주세요.",
  FACT_CHANGED_ELSEWHERE: "이 사실은 다른 곳에서 먼저 고쳐졌어요. 빼고 새로 넣어 주세요.",
  FACT_MOVED_ENTITY: ENTITY_MOVED,
  CARD_ENTITY_MOVED: ENTITY_MOVED,
  FACT_VALUE_NOT_IN_SENTENCE: "숫자 칸과 문장 속 숫자가 달라요. 문장도 같이 고쳐 주세요.",
  STEP_REQUIRES_ORDER: "먼저 해야 하는 단계보다 앞으로 옮길 수 없어요.",
  FACT_REQUIRED_BY_OTHER: "다른 단계가 이 내용을 먼저 필요로 해서 뺄 수 없어요.",
  STEP_KIND_CHANGE: "순서 단계를 일반 내용으로(또는 반대로) 바꾸려면 빼고 새로 넣어 주세요.",
  FACT_DUPLICATE_IN_CARD: "이 카드에 이미 같은 내용이 있어요.",
  VARIANT_UNRESOLVED: "어떤 규격(HOT/ICE·사이즈)인지 알 수 없어요. 규격을 고르거나 문장을 고쳐 주세요.",
  CARD_WOULD_BE_EMPTY: "사실이 하나도 남지 않아요. 카드를 지우려면 \"카드 지우기\"를 눌러 주세요.",
  CARD_TOO_LARGE: CANNOT_SAVE,
  CARD_LAYOUT_INVALID: CANNOT_SAVE,
  FACT_SET_MISMATCH: CANNOT_SAVE,
  FACT_FIELD_INVALID: CANNOT_SAVE,
  FACT_EDIT_DISABLED: FACT_EDIT_DISABLED_TEXT,
  CARD_EXCLUDED: CARD_EXCLUDED_TEXT,
  NOT_FACT_CARD: CANNOT_SAVE,
};

export function errorCode(error: unknown): string | null {
  return error instanceof ApiError ? error.code : null;
}

/** 네트워크·시간 초과·5xx: 같은 멱등 키로 다시 보내도 되는 실패. */
export function isRetryable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return error.kind !== "http" || error.status >= 500 || error.retryable;
}

export function saveErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "저장하지 못했어요. 다시 시도해 주세요. (입력은 그대로 둬요)";
  if (error.code === "FACT_FIELD_INVALID" && error.details.field === "value") return VALUE_CLEAR_TEXT;
  // 단계 번호가 줄 자리와 어긋남: 새로고침으로는 풀리지 않는다 → 자리를 옮기게 안내
  if (error.code === "CARD_LAYOUT_INVALID" && error.details.plan_code === "PLAN_STEP_ORDER") return STEP_ORDER_TEXT;
  // 서버 문장을 그대로 쓴다(같은 키·다른 본문)
  if (error.code === "IDEMPOTENCY_CONFLICT") return error.detail || "같은 요청 키로 다른 내용이 이미 저장됐어요. 새로고침 뒤 다시 시도해 주세요.";
  const known = SAVE_MESSAGES[error.code];
  if (known) return known;
  if (isRetryable(error)) return `${apiErrorMessage(error, "저장하지 못했어요.")} 입력은 그대로 뒀어요.`;
  return apiErrorMessage(error, CANNOT_SAVE);
}

export function parseErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return PARSE_FAILED_TEXT;
  if (error.code === "PARSE_TEXT_TOO_LONG") {
    const max = typeof error.details.max_chars === "number" ? error.details.max_chars : 1000;
    return `글은 ${max}자까지 분석할 수 있어요. (입력은 그대로 둬요)`;
  }
  if (error.code === "FACT_EDIT_DISABLED") return FACT_EDIT_DISABLED_TEXT;
  if (error.code === "CARD_ENTITY_MOVED") return ENTITY_MOVED;
  if (error.code === "CARD_EXCLUDED") return CARD_EXCLUDED_TEXT;
  if (error.code === "PARSE_BASE_INVALID") return error.detail || "고칠 사실이 이 카드에 없어요.";
  return PARSE_FAILED_TEXT;
}

/** 분석 제안·결과 경고 (common §5-2). */
export function warningText(code: string, count = 0): string {
  switch (code) {
    case "MULTIPLE_FACTS":
      return `문장에서 사실 ${count}개를 찾았어요. 넣을 것만 고르세요.`;
    case "TOO_MANY_FACTS":
      return `사실이 많아 앞의 ${count}개만 보여요. 나머지는 따로 넣어 주세요.`;
    case "NO_FACT":
      return NO_FACT_TEXT;
    case "MODIFY_SPLIT":
      return "문장에 사실이 여러 개 있어 첫 번째만 칸에 채웠어요. 나머지는 '사실 추가'로 따로 넣어 주세요.";
    case "SUBJECT_MISMATCH":
      return "이 카드의 메뉴·업무와 다른 대상 같아요. 맞는지 확인해 주세요.";
    case "VARIANT_UNRESOLVED":
      return "어떤 규격(HOT/ICE·사이즈)인지 알 수 없어 넣을 수 없어요. 문장을 고쳐 다시 분석해 주세요.";
    case "NEW_VARIANT":
      return "이 카드에 없던 규격이에요. 넣으면 새 묶음이 생겨요.";
    case "VALUE_NOT_IN_SENTENCE":
      return "숫자 칸과 문장 속 숫자가 달라요. 문장도 같이 고쳐 주세요.";
    case "STEP_CHANGED":
      return "순서 단계 여부가 바뀌어 여기에 넣을 수 없어요. 빼고 새로 넣어 주세요.";
    default:
      return "확인이 필요한 제안이에요.";
  }
}

/** 이 경고가 있는 제안은 카드에 넣을 수 없다. */
export function blocksProposal(warnings: string[]): boolean {
  return warnings.includes("VARIANT_UNRESOLVED") || warnings.includes("STEP_CHANGED");
}
