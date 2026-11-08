// 서버 작업 상태 → 정리 단계 번호. node --test 가 바로 읽도록 import 없이 둔다.
// 0 올리는 중, 1 읽는 중, 2 카드 제작 중, 3 끝(모든 단계 체크)

export const JOB_STEPS = ["올리는 중", "읽는 중", "카드 제작 중"] as const;

export function jobStepIndex(status: string): 0 | 1 | 2 | 3 {
  if (status === "QUEUED" || status === "EXTRACTING") return 1;
  if (status === "CLASSIFYING") return 2;
  return 3;
}

// 끝난 단계는 과거형으로(2026-11-08 사용자). 지금·남은 단계는 JOB_STEPS 그대로
const DONE_STEPS = ["올렸어요", "읽었어요", "카드 만들었어요"] as const;

/** 단계 index 의 이름. current 는 지금 단계(jobStepIndex), 그보다 앞이면 끝난 단계 */
export function jobStepLabel(index: number, current: number): string {
  return index < current ? DONE_STEPS[index] : JOB_STEPS[index];
}
