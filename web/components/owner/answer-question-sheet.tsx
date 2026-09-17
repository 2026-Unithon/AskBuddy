"use client";

import { useState } from "react";
import Link from "next/link";
import { Button, Textarea } from "@/components/ui";
import type { AggregatedQuestionItem } from "./pending-question-card";

interface AnswerQuestionSheetProps {
  item: AggregatedQuestionItem | null;
  onClose: () => void;
  onSubmit: (questionId: number, answerText: string) => Promise<void>;
  isSubmitting?: boolean;
  error?: string | null;
}

export function AnswerQuestionSheet({
  item,
  onClose,
  onSubmit,
  isSubmitting = false,
  error = null,
}: AnswerQuestionSheetProps) {
  const [answerText, setAnswerText] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  if (!item) return null;

  function requestClose() {
    if (!isSubmitting) onClose();
  }

  async function handleSubmit() {
    const text = answerText.trim();
    if (!text) {
      setLocalError("답변 내용을 입력해주세요.");
      return;
    }
    if (!item?.waitingQuestionId) {
      setLocalError("답변 가능한 대기 질문 번호가 없습니다.");
      return;
    }

    try {
      setLocalError(null);
      await onSubmit(item.waitingQuestionId, text);
      setAnswerText("");
      onClose();
    } catch {
      // 오류 시 텍스트는 보존되고 상위 error 또는 localError로 표시됨
    }
  }

  const effectiveError = error ?? localError;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 backdrop-blur-xs transition-opacity animate-[fadeIn_0.2s_ease-out]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sheet-title"
    >
      {/* 딤 영역 터치 시 닫기 */}
      <div className="absolute inset-0" onClick={requestClose} aria-hidden="true" />

      {/* 바텀시트 컨테이너 (최대 너비 480px) */}
      <div className="relative w-full max-w-[480px] rounded-t-3xl bg-surface p-5 shadow-2xl border-t border-border space-y-4 pb-[calc(1.25rem+env(safe-area-inset-bottom,0px))] max-h-[85dvh] flex flex-col">
        {/* 상단 드래그 핸들 */}
        <div className="mx-auto h-1.5 w-10 rounded-full bg-border shrink-0" aria-hidden="true" />

        {/* 헤더 */}
        <div className="flex items-start justify-between gap-2 shrink-0">
          <div>
            <h2 id="sheet-title" className="text-base font-bold text-foreground">
              직원 질문에 답변하기
            </h2>
            <p className="text-sm text-muted mt-0.5 leading-relaxed">
              답변하신 내용은 직원의 Buddy 채팅에 전달되고 매장의 정식 지식 카드로 검토·등록됩니다.
            </p>
          </div>
          <button
            type="button"
            onClick={requestClose}
            disabled={isSubmitting}
            aria-label="닫기"
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full text-muted hover:text-foreground active:scale-95 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* 질문 원문 박스 */}
        <div className="rounded-xl bg-surface-muted/50 p-3.5 space-y-1 border border-border shrink-0">
          <div className="flex items-center justify-between text-xs text-muted font-medium">
            <span>직원 {item.distinctStaffCount}명이 {item.occurrenceCount}회 질문</span>
          </div>
          <p className="text-base font-bold text-foreground leading-snug select-text">
            Q. {item.questionText}
          </p>
        </div>

        {/* 오류 알림 (사라지지 않고 텍스트 보존) */}
        {effectiveError && (
          <div
            id="answer-error"
            role="alert"
            className="rounded-xl border border-danger-500/30 bg-danger-50 p-3 text-xs text-danger-700 font-semibold"
          >
            ⚠️ {effectiveError}
          </div>
        )}

        {/* 답변 입력 텍스트 영역 */}
        <div className="flex-1 flex flex-col min-h-0 space-y-1.5">
          <label htmlFor="answer-input" className="text-xs font-bold text-foreground">
            답변 내용 <span className="text-brand-600">*</span>
          </label>
          <Textarea
            id="answer-input"
            data-testid="answer-input"
            rows={4}
            value={answerText}
            onChange={(e) => setAnswerText(e.target.value)}
            disabled={isSubmitting}
            placeholder="직원이 바로 이해할 수 있도록 명확하게 설명해주세요 (예: 우유는 제빙기 아래 냉장고 두 번째 선반에 있습니다)"
            aria-invalid={Boolean(effectiveError)}
            aria-describedby={effectiveError ? "answer-error" : undefined}
            className="flex-1 resize-none bg-background font-medium"
          />
        </div>

        {/* 하단 동사형 CTA 버튼 그룹 */}
        <div className="space-y-2 shrink-0 pt-1">
          <Button
            data-testid="answer-submit"
            size="lg"
            variant="primary"
            loading={isSubmitting}
            loadingLabel="답변 전송 중"
            disabled={!answerText.trim()}
            onClick={handleSubmit}
            className="w-full min-h-[48px] text-xs font-bold shadow-xs active:scale-[0.98]"
          >
            답변 보내기
          </Button>

          <div className="flex items-center justify-between gap-2 pt-1">
            <Link
              href={`/owner/cards?query=${encodeURIComponent(item.questionText)}`}
              aria-disabled={isSubmitting}
              onClick={(event) => {
                if (isSubmitting) {
                  event.preventDefault();
                  return;
                }
                requestClose();
              }}
              className="inline-flex min-h-[44px] items-center text-xs font-semibold text-brand-700 hover:underline px-2 py-1"
            >
              🔍 등록된 카드 연결하기
            </Link>

            <button
              type="button"
              disabled={isSubmitting}
              onClick={requestClose}
              className="min-h-[44px] px-3 text-xs font-semibold text-muted hover:text-foreground active:scale-95"
            >
              나중에 답하기
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
