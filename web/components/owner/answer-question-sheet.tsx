"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { Button, Textarea } from "@/components/ui";
import { apiErrorMessage, ApiError } from "@/lib/api";
import type { IngestCapabilities, IngestSourceType, IntakeHint } from "@/lib/api";
import { acceptAttribute, sourceTypeFor, tooLargeMessage } from "@/lib/ingest-submit";
import { IntakeHintChips } from "./intake-hint-chips";
import type { AggregatedQuestionItem } from "./pending-question-card";

interface AnswerQuestionSheetProps {
  item: AggregatedQuestionItem | null;
  onClose: () => void;
  onSubmit: (questionId: number, answerText: string) => Promise<void>;
  /** 파일 하나를 올리고 답변에 붙인다. 서버 작업 상태는 상위 mutation 과 서버가 갖는다. */
  onAttach?: (args: {
    questionId: number;
    file: File;
    sourceType: IngestSourceType;
    hints: IntakeHint[];
    /** 이미 등록된 자료면 등록을 건너뛰고 붙이기만 한다. */
    sourceId?: number;
  }) => Promise<{ sourceId: number; duplicate?: boolean }>;
  capabilities?: IngestCapabilities;
  isSubmitting?: boolean;
  error?: string | null;
}

/** 자료 등록은 됐지만 붙이기가 실패한 경우 자료 번호를 들고 올라온다. */
export class AttachStepError extends Error {
  constructor(public sourceId: number, public cause: unknown) {
    super("attach step failed");
  }
}

type AttachmentStatus = "UPLOADING" | "DONE" | "FAILED";
type Attachment = {
  id: number;
  file: File;
  sourceType: IngestSourceType;
  status: AttachmentStatus;
  message: string | null;
  /** 등록에 성공한 자료 번호. 재시도는 이 값이 있으면 붙이기만 다시 한다. */
  sourceId: number | null;
};

export function AnswerQuestionSheet({
  item,
  onClose,
  onSubmit,
  onAttach,
  capabilities,
  isSubmitting = false,
  error = null,
}: AnswerQuestionSheetProps) {
  const [answerText, setAnswerText] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  // 화면 입력(초안)이다. 서버 작업의 상태는 여기서 소유하지 않는다.
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [hints, setHints] = useState<IntakeHint[]>([]);
  const [pickError, setPickError] = useState<string | null>(null);
  const nextId = useRef(1);
  const fileInput = useRef<HTMLInputElement>(null);

  if (!item) return null;

  const questionId = item.waitingQuestionId;
  const uploading = attachments.some((a) => a.status === "UPLOADING");
  const failed = attachments.some((a) => a.status === "FAILED");
  const canAttach = Boolean(onAttach && questionId && capabilities);

  function patch(id: number, next: Partial<Attachment>) {
    setAttachments((list) => list.map((a) => (a.id === id ? { ...a, ...next } : a)));
  }

  async function runAttach(entry: Attachment) {
    if (!onAttach || !questionId) return;
    patch(entry.id, { status: "UPLOADING", message: null });
    try {
      const done = await onAttach({
        questionId,
        file: entry.file,
        sourceType: entry.sourceType,
        hints,
        sourceId: entry.sourceId ?? undefined,
      });
      // 이미 올린 자료(같은 파일)면 새로 처리하지 않고 답변에 연결만 했다
      patch(entry.id, {
        status: "DONE",
        sourceId: done.sourceId,
        message: done.duplicate ? "이미 올린 자료라 답변에 연결만 했어요" : null,
      });
    } catch (err) {
      patch(entry.id, {
        status: "FAILED",
        sourceId: err instanceof AttachStepError ? err.sourceId : entry.sourceId,
        message:
          err instanceof ApiError
            ? apiErrorMessage(err, "첨부하지 못했어요.")
            : "첨부하지 못했어요. 다시 시도해 주세요.",
      });
    }
  }

  function handlePick(files: FileList | null) {
    if (!files) return;
    setPickError(null);
    const rejected: string[] = [];
    for (const file of Array.from(files)) {
      const sourceType = sourceTypeFor(file, capabilities);
      if (!sourceType) {
        rejected.push(`'${file.name}'은(는) 올릴 수 없는 형식이에요.`);
        continue;
      }
      const tooLarge = tooLargeMessage(file, sourceType, capabilities);
      if (tooLarge) {
        rejected.push(tooLarge);
        continue;
      }
      const entry: Attachment = { id: nextId.current++, file, sourceType, status: "UPLOADING", message: null, sourceId: null };
      setAttachments((list) => [...list, entry]);
      void runAttach(entry);
    }
    if (rejected.length > 0) setPickError(rejected.join(" "));
    if (fileInput.current) fileInput.current.value = "";
  }

  function removeAttachment(id: number) {
    setAttachments((list) => list.filter((a) => a.id !== id));
  }

  function requestClose() {
    if (!isSubmitting && !uploading) onClose();
  }

  async function handleSubmit() {
    const text = answerText.trim();
    if (!text) {
      setLocalError("답변 내용을 입력해주세요.");
      return;
    }
    if (uploading || failed) {
      setLocalError("첨부를 마치거나 실패한 첨부를 빼고 보내 주세요.");
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
      setAttachments([]);
      setHints([]);
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
      <div className="relative w-full max-w-[480px] rounded-t-3xl bg-surface p-5 shadow-2xl border-t border-border space-y-4 pb-[calc(1.25rem+env(safe-area-inset-bottom,0px))] max-h-[85dvh] flex flex-col overflow-y-auto">
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
            disabled={isSubmitting || uploading}
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
        <div className="flex-none flex flex-col space-y-1.5">
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
            className="min-h-28 resize-none bg-background font-medium"
          />
        </div>

        {/* 파일 첨부(선택) */}
        {canAttach && (
          <div className="space-y-2 shrink-0" data-testid="attach-area">
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              data-testid="attach-input"
              accept={acceptAttribute(capabilities)}
              onChange={(e) => handlePick(e.target.files)}
            />
            <IntakeHintChips value={hints} onChange={setHints} disabled={isSubmitting} />
            <button
              type="button"
              data-testid="attach-button"
              disabled={isSubmitting}
              onClick={() => fileInput.current?.click()}
              className="min-h-[44px] rounded-xl border border-border px-4 text-xs font-bold text-foreground active:scale-95 disabled:opacity-50"
            >
              📎 파일 첨부(선택)
            </button>
            {pickError && (
              <p role="alert" data-testid="attach-pick-error" className="text-xs font-semibold text-danger-700">
                {pickError}
              </p>
            )}
            {attachments.length > 0 && (
              <ul className="space-y-1.5" data-testid="attach-list">
                {attachments.map((a) => (
                  <li
                    key={a.id}
                    data-testid="attach-item"
                    data-status={a.status}
                    className="flex items-center justify-between gap-2 rounded-xl border border-border bg-background px-3 py-2 text-xs"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-foreground">{a.file.name}</p>
                      <p className={a.status === "FAILED" ? "text-danger-700" : "text-muted"}>
                        {a.status === "UPLOADING" && "올리는 중"}
                        {a.status === "DONE" && (a.message ?? "첨부 완료")}
                        {a.status === "FAILED" && (a.message ?? "첨부하지 못했어요.")}
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      {a.status === "FAILED" && (
                        <button
                          type="button"
                          data-testid="attach-retry"
                          disabled={isSubmitting}
                          onClick={() => void runAttach(a)}
                          className="min-h-[44px] px-2 font-bold text-brand-700"
                        >
                          다시 시도
                        </button>
                      )}
                      {a.status === "FAILED" && (
                        <button
                          type="button"
                          data-testid="attach-remove"
                          disabled={isSubmitting}
                          onClick={() => removeAttachment(a.id)}
                          className="min-h-[44px] px-2 font-semibold text-muted"
                        >
                          빼기
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* 하단 동사형 CTA 버튼 그룹 */}
        <div className="space-y-2 shrink-0 pt-1">
          <Button
            data-testid="answer-submit"
            size="lg"
            variant="primary"
            loading={isSubmitting}
            loadingLabel="답변 전송 중"
            disabled={!answerText.trim() || uploading || failed}
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
              disabled={isSubmitting || uploading}
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
