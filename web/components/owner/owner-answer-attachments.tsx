"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Caption, ErrorInline } from "@/components/kit";
import { ApiError, apiErrorMessage, attachOwnerAnswerFile, type IngestSourceType, type IntakeHint } from "@/lib/api";
import { acceptAttribute, registerFileSource, sourceTypeFor, tooLargeMessage } from "@/lib/ingest-submit";
import { ingestCapabilitiesQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";
import { IntakeHintChips } from "./intake-hint-chips";

/** 자료 등록은 됐지만 붙이기가 실패한 경우 자료 번호를 들고 올라온다. */
class AttachStepError extends Error {
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

/**
 * 점주 답변 파일 첨부(선택). 답을 보내기 전·후 모두 붙일 수 있다 — 답변 처리가 끝난 뒤 붙은 첨부는
 * 서버가 보충 작업을 만든다. 작업(job) 상태는 서버가 갖고 작업 목록 화면이 보여 준다.
 */
export function OwnerAnswerAttachments({ questionId }: { questionId: number }) {
  const { state } = useApp();
  const queryClient = useQueryClient();
  const caps = useQuery(ingestCapabilitiesQuery(state.token, state.storeId));
  // 화면 입력(초안)이다. 서버 작업의 상태는 여기서 소유하지 않는다.
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [hints, setHints] = useState<IntakeHint[]>([]);
  const [pickError, setPickError] = useState<string | null>(null);
  const nextId = useRef(1);
  const fileInput = useRef<HTMLInputElement>(null);

  const attach = useMutation({
    mutationFn: async ({ file, sourceType, sourceId }: { file: File; sourceType: IngestSourceType; sourceId?: number }) => {
      // 재시도에서 이미 등록된 자료는 다시 등록하지 않고 붙이기만 한다
      let id = sourceId;
      let duplicate = false;
      if (id === undefined) {
        const registered = await registerFileSource(file, sourceType, state.token!, hints);
        id = registered.source_id;
        // 같은 파일을 전에 올렸다 — 붙이기만 하고 새 업로드로 다루지 않는다(다시 처리할지는 서버가 정한다)
        duplicate = registered.duplicate;
      }
      let jobId: number | null;
      try {
        jobId = (await attachOwnerAnswerFile(questionId, id, state.token!)).job_id;
      } catch (err) {
        throw new AttachStepError(id, err);
      }
      // 이미 등록된 자료에 서버가 작업을 만들지 않았으면 연결만 된 것이다
      return { sourceId: id, duplicate: duplicate && jobId === null };
    },
    onSuccess: ({ duplicate }) => {
      if (!duplicate) void queryClient.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) });
    },
  });

  if (caps.error) {
    return (
      <ErrorInline
        message={apiErrorMessage(caps.error, "파일 첨부를 준비하지 못했어요.")}
        onRetry={() => void caps.refetch()}
        retrying={caps.isRefetching}
      />
    );
  }
  if (!caps.data) return null;
  const capabilities = caps.data;

  function patch(id: number, next: Partial<Attachment>) {
    setAttachments((list) => list.map((a) => (a.id === id ? { ...a, ...next } : a)));
  }

  async function runAttach(entry: Attachment) {
    patch(entry.id, { status: "UPLOADING", message: null });
    try {
      const done = await attach.mutateAsync({
        file: entry.file,
        sourceType: entry.sourceType,
        sourceId: entry.sourceId ?? undefined,
      });
      patch(entry.id, {
        status: "DONE",
        sourceId: done.sourceId,
        message: done.duplicate ? "이미 올린 자료라 답변에 연결만 했어요" : null,
      });
    } catch (err) {
      const cause = err instanceof AttachStepError ? err.cause : err;
      patch(entry.id, {
        status: "FAILED",
        sourceId: err instanceof AttachStepError ? err.sourceId : entry.sourceId,
        message: cause instanceof ApiError ? apiErrorMessage(cause, "첨부하지 못했어요.") : "첨부하지 못했어요. 다시 시도해 주세요.",
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

  return (
    <div className="flex w-full flex-col gap-2 rounded-[20px] bg-surface px-[18px] py-4 shadow-card" data-testid="attach-area">
      <Caption>사진, 문서, 음성을 함께 붙이면 카드로 같이 정리해요(선택)</Caption>
      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        data-testid="attach-input"
        accept={acceptAttribute(capabilities)}
        onChange={(e) => handlePick(e.target.files)}
      />
      <IntakeHintChips value={hints} onChange={setHints} />
      <Button variant="secondary" data-testid="attach-button" onClick={() => fileInput.current?.click()}>
        파일 첨부
      </Button>
      {pickError && (
        <p role="alert" data-testid="attach-pick-error" className="text-[13px] font-semibold text-danger-700">
          {pickError}
        </p>
      )}
      {attachments.length > 0 && (
        <ul className="flex flex-col gap-1.5" data-testid="attach-list">
          {attachments.map((a) => (
            <li
              key={a.id}
              data-testid="attach-item"
              data-status={a.status}
              className="flex items-center justify-between gap-2 rounded-xl bg-background px-3 py-2 text-[13px]"
            >
              <div className="min-w-0">
                <p className="truncate font-semibold text-ink">{a.file.name}</p>
                <p className={a.status === "FAILED" ? "text-danger-700" : "text-ink-muted"}>
                  {a.status === "UPLOADING" && "올리는 중"}
                  {a.status === "DONE" && (a.message ?? "첨부 완료")}
                  {a.status === "FAILED" && (a.message ?? "첨부하지 못했어요.")}
                </p>
              </div>
              {a.status === "FAILED" && (
                <div className="flex shrink-0 gap-1">
                  <button type="button" data-testid="attach-retry" onClick={() => void runAttach(a)} className="min-h-11 px-2 font-bold text-primary">
                    다시 시도
                  </button>
                  <button
                    type="button"
                    data-testid="attach-remove"
                    onClick={() => setAttachments((list) => list.filter((x) => x.id !== a.id))}
                    className="min-h-11 px-2 font-semibold text-ink-muted"
                  >
                    빼기
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
