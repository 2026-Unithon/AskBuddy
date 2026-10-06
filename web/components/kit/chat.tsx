import type { ReactNode } from "react";

/** Figma Q: 오른쪽 진한 초록 말풍선 (내가 보낸 질문). */
export function QuestionBubble({ children, pending = false }: { children: ReactNode; pending?: boolean }) {
  return (
    <div className="flex w-full justify-end">
      <p
        data-testid="message-content"
        className={`max-w-[85%] whitespace-pre-wrap rounded-[16px] bg-primary px-3.5 py-2.5 text-[15px] font-medium leading-[1.45] tracking-[-0.15px] text-white shadow-primary [word-break:keep-all] ${
          pending ? "opacity-60" : ""
        }`}
      >
        {children}
      </p>
    </div>
  );
}

/** Figma A: 왼쪽 흰 말풍선. chips 에 근거 카드·상태 칩, actions 에 선택지·재시도. */
export function AnswerBubble({
  children,
  chips,
  actions,
  tone = "default",
}: {
  children: ReactNode;
  chips?: ReactNode;
  actions?: ReactNode;
  tone?: "default" | "error";
}) {
  return (
    <div className="flex w-full">
      <div
        className={`flex max-w-[85%] flex-col gap-2 rounded-[20px] px-3.5 py-2.5 shadow-card ${
          tone === "error" ? "bg-danger-50" : "bg-surface"
        }`}
      >
        <div data-testid="message-content" className="whitespace-pre-wrap text-[15px] leading-[1.45] tracking-[-0.15px] text-ink [word-break:keep-all]">
          {children}
        </div>
        {chips && <div className="flex flex-wrap gap-1.5">{chips}</div>}
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}
