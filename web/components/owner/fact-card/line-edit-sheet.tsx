"use client";

// 줄 고치기(계획 10): 보이는 줄 글을 그대로 고친다. 저장할 때 서버가 이 글을 다시 분석해 사실을 새 판으로 만든다.
import { useState } from "react";
import { Button, Sheet, focusRing } from "@/components/kit";

const MAX_CHARS = 300;

export function LineEditSheet({
  initial,
  onApply,
  onRemove,
  onClose,
}: {
  initial: string;
  onApply: (text: string) => void;
  onRemove: () => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(initial);
  const trimmed = text.trim();
  return (
    <Sheet open onClose={onClose} title="이 줄 고치기">
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-medium text-ink-muted">줄 글</span>
        <textarea
          value={text}
          maxLength={MAX_CHARS}
          rows={3}
          onChange={(event) => setText(event.target.value)}
          className={`rounded-[16px] bg-surface p-4 text-[16px] leading-[1.6] text-ink shadow-card ${focusRing}`}
        />
      </label>
      <Button disabled={!trimmed || trimmed === initial.trim()} onClick={() => onApply(trimmed)}>
        바꾸기
      </Button>
      <Button variant="danger" onClick={onRemove}>
        이 줄 빼기
      </Button>
      <Button variant="secondary" onClick={onClose}>
        그만두기
      </Button>
    </Sheet>
  );
}
