"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
 * 점주 답변 파일 첨부(선택, o10b). 답을 보내기 전·후 모두 붙일 수 있다 — 답변 처리가 끝난 뒤 붙은 첨부는
 * 서버가 보충 작업을 만든다. 작업(job) 상태는 서버가 갖고 작업 목록 화면이 보여 준다.
 * 화면은 입력창의 📎 도구로 고르고, 붙인 파일 줄과 종류 칩은 입력창 안팎에 놓는다.
 */
export function useAnswerAttachments(questionId: number) {
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
    if (!files || !caps.data) return;
    setPickError(null);
    const rejected: string[] = [];
    for (const file of Array.from(files)) {
      const sourceType = sourceTypeFor(file, caps.data);
      if (!sourceType) {
        rejected.push(`'${file.name}'은(는) 올릴 수 없는 형식이에요.`);
        continue;
      }
      const tooLarge = tooLargeMessage(file, sourceType, caps.data);
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

  return {
    caps,
    attachments,
    hints,
    setHints,
    pickError,
    open: () => fileInput.current?.click(),
    retry: (entry: Attachment) => void runAttach(entry),
    remove: (id: number) => setAttachments((list) => list.filter((x) => x.id !== id)),
    input: (
      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        data-testid="attach-input"
        accept={caps.data ? acceptAttribute(caps.data) : undefined}
        onChange={(e) => handlePick(e.target.files)}
      />
    ),
  };
}

export type AnswerAttachments = ReturnType<typeof useAnswerAttachments>;

/** 입력창 첨부 자리: 파일마다 한 줄(올리는 중·끝·실패와 다시·빼기). */
export function AnswerAttachmentRows({ files }: { files: AnswerAttachments }) {
  if (files.attachments.length === 0 && !files.pickError) return null;
  return (
    <div className="flex flex-col gap-1.5">
      {files.pickError && (
        <p role="alert" data-testid="attach-pick-error" className="text-[13px] font-semibold text-danger-700">
          {files.pickError}
        </p>
      )}
      <ul className="flex flex-col gap-1.5" data-testid="attach-list">
        {files.attachments.map((a) => (
          <li
            key={a.id}
            data-testid="attach-item"
            data-status={a.status}
            className={`flex items-center justify-between gap-2 rounded-[12px] px-2.5 py-1.5 text-[12px] font-medium ${
              a.status === "FAILED" ? "border border-danger-500 bg-danger-50 text-danger-700" : "bg-empty text-primary"
            }`}
          >
            <div className="min-w-0">
              <p className="truncate">{a.file.name}</p>
              {a.status === "UPLOADING" && <p className="text-ink-muted">올리는 중</p>}
              {a.status === "DONE" && a.message && <p className="text-ink-muted">{a.message}</p>}
              {a.status === "FAILED" && <p>{a.message ?? "첨부하지 못했어요."}</p>}
            </div>
            {a.status === "FAILED" && (
              <div className="flex shrink-0 gap-1">
                <button type="button" data-testid="attach-retry" onClick={() => files.retry(a)} className="min-h-8 rounded-[8px] bg-surface px-2.5 font-bold text-danger-700">
                  다시
                </button>
                <button type="button" data-testid="attach-remove" onClick={() => files.remove(a.id)} className="min-h-8 px-2 text-ink-muted">
                  빼기
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 파일을 하나라도 붙였을 때만 종류 칩을 보인다(o10b). 고른 종류는 그 뒤에 붙이는 파일부터 쓴다. */
export function AnswerAttachmentHints({ files }: { files: AnswerAttachments }) {
  if (files.attachments.length === 0) return null;
  return <IntakeHintChips value={files.hints} onChange={files.setHints} />;
}
