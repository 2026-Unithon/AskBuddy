// 서버 작업 상태 → 정리 단계 번호. node --test 가 바로 읽도록 import 없이 둔다.
// 0 올렸어요, 1 읽는 중, 2 나누는 중, 3 끝(모든 단계 체크)

export const JOB_STEPS = ["올렸어요", "읽는 중", "나누는 중"] as const;

export function jobStepIndex(status: string): 0 | 1 | 2 | 3 {
  if (status === "QUEUED" || status === "EXTRACTING") return 1;
  if (status === "CLASSIFYING") return 2;
  return 3;
}
