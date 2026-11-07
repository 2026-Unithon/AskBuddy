"use client";

import Link from "next/link";
import { focusRing, Sheet, useFeedback } from "@/components/kit";
import { QuestionAnswerForm } from "@/components/owner/question-answer-form";

/** 질문을 누르면 아래에서 올라오는 답하기 시트(o01d). 보내면 닫고 알린다. */
export function QuestionSheet({
  question,
  onClose,
  onSent,
}: {
  question: { pending_id: string; question: string } | null;
  onClose: () => void;
  /** 보낸 질문 id. 저장이 늦게 끝나면 이미 다른 질문 시트가 열려 있을 수 있어, 부모가 같은 질문일 때만 닫는다 */
  onSent: (pendingId: string) => void;
}) {
  const { toast } = useFeedback();
  return (
    <Sheet open={question !== null} onClose={onClose} title={question?.question ?? ""} description="한 번 답하면 다음 알바는 이걸 안 물어봐요">
      {question && (
        <>
          <QuestionAnswerForm
            pendingId={question.pending_id}
            onSent={() => {
              toast("답을 보냈어요");
              onSent(question.pending_id);
            }}
          />
          <Link href={`/owner/questions/${question.pending_id}`} className={`self-center text-[13px] text-ink-muted underline underline-offset-4 ${focusRing}`}>
            자세히 보기
          </Link>
        </>
      )}
    </Sheet>
  );
}
