/**
 * 서버 오류 문구 중 사용자에게 보일 것만 고른다.
 * 우리 서버(ApiError)는 늘 한국어 문구를 준다. 한글이 없는 문구는 프레임워크 기본값("Not Found",
 * "Method Not Allowed")이나 개발자용이라 보이지 않고, 부르는 쪽의 상황 문구를 쓴다(2026-11-09 사용자 실화면).
 */
export function visibleDetail(detail: string): string | null {
  const text = detail.trim();
  if (!text) return null;
  return /[가-힣]/.test(text) ? text : null;
}
