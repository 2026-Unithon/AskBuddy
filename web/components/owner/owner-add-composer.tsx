"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Caption, Composer, ComposerTool, ErrorInline, Icon } from "@/components/kit";
import { apiErrorMessage } from "@/lib/api";
import {
  acceptAttribute,
  sourceTypeFor,
  submitIngest,
  supportsText,
  tooLargeMessage,
  type PickedFile,
  type SourceFailure,
} from "@/lib/ingest-submit";
import { ingestCapabilitiesQuery, queryKeys } from "@/lib/query";
import { useApp } from "@/lib/store";

/**
 * O3·O6 "새로 알려줄 것 넣기". 찍기·파일은 기존 업로드 경로, 글은 서버가 TEXT 를 지원할 때만(계획 U6-1).
 * 말하기는 녹음 형식 결정 전까지 숨긴다(U6-2).
 * 접수(202)되면 작업 화면으로 넘긴다 — 추출 진행은 이 컴포넌트가 들고 있지 않는다.
 */
export function OwnerAddComposer({ placeholder = "새로 알려줄 것 넣기" }: { placeholder?: string }) {
  const { state } = useApp();
  const router = useRouter();
  const client = useQueryClient();
  const caps = useQuery(ingestCapabilitiesQuery(state.token, state.storeId));
  const [text, setText] = useState("");
  const [files, setFiles] = useState<PickedFile[]>([]);
  const [pickErrors, setPickErrors] = useState<string[]>([]);
  const [failures, setFailures] = useState<SourceFailure[]>([]);
  // 같은 입력을 다시 보내면 같은 작업으로 묶이게 한다. 입력이 바뀌면 새 키.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const textEnabled = supportsText(caps.data);
  const submit = useMutation({
    mutationFn: () => submitIngest({ files, text: textEnabled ? text : "", token: state.token!, idempotencyKey }),
    onSuccess: async (result) => {
      setFailures(result.failures);
      if (result.jobId === null) return;
      await client.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) });
      setText("");
      setFiles([]);
      setIdempotencyKey(crypto.randomUUID());
      router.push(`/owner/jobs/${result.jobId}`);
    },
  });

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const errors: string[] = [];
    const added: PickedFile[] = [];
    for (const file of Array.from(list)) {
      const type = sourceTypeFor(file, caps.data);
      if (!type) {
        errors.push(`'${file.name}'은(는) 지금 읽지 못하는 형식이에요.`);
        continue;
      }
      const tooLarge = tooLargeMessage(file, type, caps.data);
      if (tooLarge) errors.push(tooLarge);
      else added.push({ id: crypto.randomUUID(), file, sourceType: type });
    }
    setPickErrors(errors);
    if (added.length) {
      setFiles((prev) => [...prev, ...added]);
      setIdempotencyKey(crypto.randomUUID());
    }
  };

  const hasText = text.trim().length > 0;
  const canSubmit = files.length > 0 || (hasText && textEnabled);

  return (
    <div className="flex flex-col gap-2">
      {submit.error && (
        <ErrorInline
          message={apiErrorMessage(submit.error, "전송이 완료되지 않았어요. 다시 올려주세요.")}
          onRetry={() => submit.mutate()}
          retrying={submit.isPending}
        />
      )}
      {failures.length > 0 && !submit.isPending && (
        <ErrorInline message={failures.map((f) => `${f.name}: ${f.message}`).join("\n")} />
      )}
      {pickErrors.length > 0 && <ErrorInline message={pickErrors.join("\n")} />}
      <Composer
        label="새로 알려줄 것"
        value={text}
        onChange={(value) => {
          setText(value);
          setIdempotencyKey(crypto.randomUUID());
        }}
        onSubmit={() => submit.mutate()}
        canSubmit={canSubmit && caps.isSuccess}
        submitting={submit.isPending}
        placeholder={placeholder}
        tools={
          <>
            <ComposerTool icon="camera" label="찍기" onClick={() => cameraRef.current?.click()} disabled={!caps.data || submit.isPending} />
            <ComposerTool icon="clip" label="파일" onClick={() => fileRef.current?.click()} disabled={!caps.data || submit.isPending} />
          </>
        }
        attachments={
          files.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5">
              {files.map((item) => (
                <li key={item.id} className="flex max-w-full items-center gap-1 rounded-full bg-empty py-1 pl-2.5 pr-1 text-[12px] font-medium text-primary">
                  <Icon name="clip" size={12} />
                  <span className="truncate">{item.file.name}</span>
                  <button
                    type="button"
                    aria-label={`${item.file.name} 빼기`}
                    disabled={submit.isPending}
                    onClick={() => setFiles((prev) => prev.filter((f) => f.id !== item.id))}
                    className="flex size-6 items-center justify-center rounded-full text-[14px] leading-none"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          ) : undefined
        }
      />
      {hasText && !textEnabled && caps.isSuccess && (
        <Caption>글로 넣기는 곧 열려요. 지금은 사진이나 파일로 넣어 주세요.</Caption>
      )}
      {caps.error && (
        <ErrorInline message="올릴 수 있는 형식을 확인하지 못했어요." onRetry={() => void caps.refetch()} retrying={caps.isRefetching} />
      )}
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(event) => {
          addFiles(event.target.files);
          event.target.value = "";
        }}
      />
      <input
        ref={fileRef}
        type="file"
        multiple
        accept={acceptAttribute(caps.data)}
        hidden
        onChange={(event) => {
          addFiles(event.target.files);
          event.target.value = "";
        }}
      />
    </div>
  );
}
