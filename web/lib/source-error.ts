// 자료 처리 실패 이유를 사장님 말로(2026-11-08 사용자 실화면: 'RuntimeError: …하라'가 그대로 보였다).
// 서버는 개발자용 예외 문장을 남길 때가 있어 화면에서 거른다. node --test 가 바로 읽도록 import 없이 둔다.

export const SOURCE_ERROR_FALLBACK = "이 자료를 읽지 못했어요. 다시 시도하거나 다른 형식으로 올려 주세요.";

const KNOWN: Record<string, string> = {
  PARTIAL_RETRY_UNAVAILABLE: "일부만 읽었어요. 나머지는 다시 시도할 수 없어요.",
  PARTIAL_RETRY_FAILED: "일부만 읽었어요. 나머지를 다시 읽지 못했어요.",
  UPLOAD_TIMEOUT: "올리는 데 너무 오래 걸려요. 다시 올려 주세요.",
  JOB_CANCELED: "정리를 취소했어요.",
  JOB_STALLED: "정리가 멈췄어요. 다시 시도해 주세요.",
};

/** 사장님에게 쓴 문장인가: 해요체로 끝나고 영문 예외 이름·경로가 없다 */
function forOwner(message: string): boolean {
  const text = message.trim();
  if (/[A-Za-z_]+Error\b|\/[a-z]+\/|_[a-z]+|[A-Za-z]{4,}/.test(text)) return false;
  return /(요|요\.)$/.test(text);
}

export function sourceErrorText(error: { code?: string | null; message?: string | null } | null | undefined): string {
  if (!error) return SOURCE_ERROR_FALLBACK;
  if (error.code && KNOWN[error.code]) return KNOWN[error.code];
  if (error.message && forOwner(error.message)) return error.message.trim();
  return SOURCE_ERROR_FALLBACK;
}
