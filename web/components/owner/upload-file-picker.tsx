"use client";

import { useRef, type ChangeEvent } from "react";
import type { UploadSourceType } from "@/lib/types";
import type { QueuedUploadFile } from "./upload-queue-item";

const ALLOWED_EXT_MAP: Record<string, UploadSourceType> = {
  mp3: "VOICE",
  m4a: "VOICE",
  wav: "VOICE",
  mp4: "VIDEO",
  mov: "VIDEO",
  txt: "KAKAO",
  zip: "KAKAO",
  pdf: "SCAN",
  png: "SCAN",
  jpg: "SCAN",
  jpeg: "SCAN",
};

const ACCEPT_STRING = ".mp3,.m4a,.wav,.mp4,.mov,.txt,.zip,.pdf,.png,.jpg,.jpeg";

interface UploadFilePickerProps {
  onFilesAdded: (newFiles: QueuedUploadFile[]) => void;
  onInvalidFiles?: (errorMessages: string[]) => void;
  disabled?: boolean;
}

export function UploadFilePicker({
  onFilesAdded,
  onInvalidFiles,
  disabled = false,
}: UploadFilePickerProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;

    const validItems: QueuedUploadFile[] = [];
    const invalidMessages: string[] = [];

    Array.from(fileList).forEach((file) => {
      const ext = file.name.includes(".")
        ? file.name.split(".").pop()!.toLowerCase()
        : "";
      const matchedType = ALLOWED_EXT_MAP[ext];

      if (matchedType) {
        validItems.push({
          id: `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
          file,
          sourceType: matchedType,
          status: "pending",
        });
      } else {
        invalidMessages.push(
          `'${file.name}'은(는) 지원하지 않는 형식입니다. (지원: mp3, m4a, wav, mp4, mov, txt, zip, pdf, png, jpg)`
        );
      }
    });

    if (validItems.length > 0) {
      onFilesAdded(validItems);
    }
    if (invalidMessages.length > 0 && onInvalidFiles) {
      onInvalidFiles(invalidMessages);
    }

    // 다음 선택을 위해 초기화
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT_STRING}
        onChange={handleChange}
        disabled={disabled}
        className="hidden"
        aria-label="업로드할 파일 선택"
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={disabled}
        className="w-full min-h-[56px] flex items-center justify-center gap-2.5 rounded-2xl border-2 border-dashed border-brand-400 bg-brand-50/40 px-4 py-3.5 text-brand-700 font-bold text-sm shadow-2xs transition-all active:scale-[0.98] hover:bg-brand-50 hover:border-brand-500 disabled:opacity-50 disabled:pointer-events-none"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.3">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
        <span>자료 파일 추가 (음성·영상·문서·카톡)</span>
      </button>
      <p className="mt-1.5 text-center text-[11px] text-muted">
        여러 개 파일을 한 번에 선택할 수 있으며 형식이 자동 판별됩니다.
      </p>
    </div>
  );
}

