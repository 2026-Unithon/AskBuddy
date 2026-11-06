"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useNavHistory } from "@/lib/nav-history";
import { useRef, useState } from "react";
import { Caption, Composer, ComposerTool, ErrorInline, Icon, useFeedback } from "@/components/kit";
import { IntakeHintChips } from "@/components/owner/intake-hint-chips";
import { apiErrorMessage, type IntakeHint } from "@/lib/api";
import {
  acceptAttribute,
  sourceTypeFor,
  submitIngest,
  supportsText,
  tooLargeMessage,
  type ItemUpdate,
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
export function OwnerAddComposer({
  placeholder = "새로 알려줄 것 넣기",
  defaultText = "",
  defaultHints = [],
  text: controlledText,
  onTextChange,
}: {
  placeholder?: string;
  /** 응대 가이드처럼 상황 문장을 미리 넣어 둘 때. 바꾸려면 부모가 key 로 다시 그린다. */
  defaultText?: string;
  defaultHints?: IntakeHint[];
  /** 주면 제어형(넣기 화면의 예시 칩이 글을 채운다), 안 주면 내부 상태 */
  text?: string;
  onTextChange?: (value: string) => void;
}) {
  const { state } = useApp();
  const router = useRouter();
  const { markReplace } = useNavHistory();
  const { toast } = useFeedback();
  const client = useQueryClient();
  const caps = useQuery(ingestCapabilitiesQuery(state.token, state.storeId));
  const [innerText, setInnerText] = useState(defaultText);
  const text = controlledText ?? innerText;
  const [files, setFiles] = useState<PickedFile[]>([]);
  // 파일마다 올리는 중·끝·실패. 화면 입력의 일부라 이 컴포넌트가 들고, 새로 넣으면 비운다.
  const [progress, setProgress] = useState<Record<string, ItemUpdate>>({});
  const [pickErrors, setPickErrors] = useState<string[]>([]);
  // 점주 선택 칩: 화면 입력일 뿐이라 이 컴포넌트가 들고, 제출이 성공하면 비운다.
  const [hints, setHints] = useState<IntakeHint[]>(defaultHints);
  const [failures, setFailures] = useState<SourceFailure[]>([]);
  // 같은 입력을 다시 보내면 같은 작업으로 묶이게 한다. 입력이 바뀌면 새 키.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const setText = (value: string) => {
    if (onTextChange) onTextChange(value);
    else setInnerText(value);
    setIdempotencyKey(crypto.randomUUID());
  };

  const textEnabled = supportsText(caps.data);
  const maxChars = caps.data?.TEXT?.max_chars;
  const overLimit = maxChars !== undefined && text.length > maxChars;
  const submit = useMutation({
    mutationFn: () =>
      submitIngest({
        files,
        text: textEnabled ? text : "",
        token: state.token!,
        idempotencyKey,
        hints,
        onItem: (key, update) => setProgress((prev) => ({ ...prev, [key]: update })),
      }),
    onMutate: () => {
      setFailures([]);
      setProgress({});
    },
    onSuccess: async (result) => {
      setFailures(result.failures);
      if (result.jobId === null) return;
      await client.invalidateQueries({ queryKey: queryKeys.ingestJobs(state.storeId) });
      // 일부만 실패한 채 작업으로 넘어가면 넣기 화면의 실패 줄이 사라지므로 다음 화면까지 남는 알림으로 알린다
      const failedNames = result.failures.map((f) => f.name);
      if (failedNames.length) toast(`${failedNames.join(", ")}은(는) 올리지 못했어요`, { keepOnNavigate: true });
      setText("");
      setFiles([]);
      setHints([]);
      setProgress({});
      setIdempotencyKey(crypto.randomUUID());
      // 넣기 화면은 끝났으니 기록에서 지운다(폰 뒤로가 넣기 전 화면으로)
      markReplace();
      router.replace(`/owner/jobs/${result.jobId}`);
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
  const canSubmit = (files.length > 0 || (hasText && textEnabled)) && !overLimit;
  const textFailure = failures.find((f) => f.key === "text");

  return (
    <div className="flex flex-col gap-2">
      {submit.error && (
        <ErrorInline
          message={apiErrorMessage(submit.error, "전송이 완료되지 않았어요. 다시 올려주세요.")}
          onRetry={() => submit.mutate()}
          retrying={submit.isPending}
        />
      )}
      {textFailure && !submit.isPending && <ErrorInline message={textFailure.message} onRetry={() => submit.mutate()} />}
      {pickErrors.length > 0 && <ErrorInline message={pickErrors.join("\n")} />}
      <Composer
        label="새로 알려줄 것"
        value={text}
        onChange={setText}
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
            <ul className="flex flex-col gap-1.5">
              {files.map((item) => (
                <FileRow
                  key={item.id}
                  name={item.file.name}
                  update={progress[item.id]}
                  failure={failures.find((f) => f.key === item.id)?.message}
                  disabled={submit.isPending}
                  onRemove={() => setFiles((prev) => prev.filter((f) => f.id !== item.id))}
                  onRetry={() => submit.mutate()}
                />
              ))}
            </ul>
          ) : undefined
        }
      />
      {maxChars !== undefined && hasText && (
        <p className={`text-right text-[15px] font-bold ${overLimit ? "text-danger-700" : "text-ink-muted"}`} aria-live="polite">
          {overLimit ? `${maxChars.toLocaleString()}자까지 넣을 수 있어요` : `${(maxChars - text.length).toLocaleString()}자 남았어요`}
        </p>
      )}
      <IntakeHintChips
        value={hints}
        onChange={(next) => {
          setHints(next);
          setIdempotencyKey(crypto.randomUUID());
        }}
        disabled={submit.isPending}
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

/** 첨부 파일 한 줄: 올리는 중 막대, 끝나면 체크, 실패하면 빨간 줄과 이유와 '다시'. */
function FileRow({
  name,
  update,
  failure,
  disabled,
  onRemove,
  onRetry,
}: {
  name: string;
  update?: ItemUpdate;
  failure?: string;
  disabled: boolean;
  onRemove: () => void;
  onRetry: () => void;
}) {
  const failed = Boolean(failure) || update?.status === "FAILED";
  const uploading = update?.status === "UPLOADING";
  const done = update?.status === "DONE";
  return (
    <li
      className={`flex flex-col gap-1 rounded-[12px] px-2.5 py-1.5 text-[12px] font-medium ${
        failed ? "border border-danger-500 bg-danger-50 text-danger-700" : "bg-empty text-primary"
      }`}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <Icon name={done ? "check" : "clip"} size={12} />
        <span className="min-w-0 flex-1 truncate">{name}</span>
        {failed ? (
          <button type="button" disabled={disabled} onClick={onRetry} className="min-h-8 rounded-[8px] bg-surface px-2.5 font-bold text-danger-700">
            다시
          </button>
        ) : (
          !uploading && (
            <button
              type="button"
              aria-label={`${name} 빼기`}
              disabled={disabled}
              onClick={onRemove}
              className="flex size-8 items-center justify-center rounded-full text-[14px] leading-none"
            >
              ×
            </button>
          )
        )}
      </div>
      {uploading && (
        <div
          role="progressbar"
          aria-label={`${name} 올리는 중`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round((update.progress ?? 0) * 100)}
          className="h-1 w-full overflow-hidden rounded-full bg-surface"
        >
          <div className="h-full rounded-full bg-primary transition-[width] duration-150" style={{ width: `${Math.max(4, (update.progress ?? 0) * 100)}%` }} />
        </div>
      )}
      {failed && failure && <p>{failure}</p>}
    </li>
  );
}
