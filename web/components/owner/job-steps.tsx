import { Icon } from "@/components/kit";
import { JOB_STEPS, jobStepIndex } from "@/components/owner/job-steps-logic";

/** 정리 단계(o03a). 서버 상태대로 앞 단계는 체크, 지금 단계는 스피너, 뒤는 흐린 원. 진행률 숫자는 쓰지 않는다. */
export function JobSteps({ status }: { status: string }) {
  const current = jobStepIndex(status);
  return (
    <ol aria-label="정리 단계" className="flex flex-col gap-3 rounded-[20px] bg-surface px-[18px] py-4 shadow-card">
      {JOB_STEPS.map((label, index) => {
        const done = index < current;
        const active = index === current;
        return (
          <li key={label} aria-current={active ? "step" : undefined} className={`flex items-center gap-3 text-[15px] ${done || active ? "font-bold text-ink" : "text-ink-muted"}`}>
            <span
              aria-hidden
              className={`flex size-6 shrink-0 items-center justify-center rounded-full ${
                done ? "bg-primary text-white" : active ? "border-2 border-primary border-r-transparent motion-safe:animate-spin" : "border-2 border-empty"
              }`}
            >
              {done && <Icon name="check" size={14} className="animate-[check-pop_var(--dur-base)_var(--ease-spring)]" />}
            </span>
            {label}
          </li>
        );
      })}
    </ol>
  );
}
