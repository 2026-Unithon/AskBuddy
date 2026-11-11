"use client";

import { useEffect, useRef, useState } from "react";
import { Button, ErrorInline, Sheet, focusRing } from "@/components/kit";

/**
 * 되돌릴 수 없는 일의 두 번째 확인(계획 8). 문구를 그대로 쳐야 버튼이 켜진다(앞뒤 공백만 무시).
 * 서버도 같은 문구를 다시 본다.
 */
export function TypedConfirm({
  title,
  phrase,
  loading,
  error,
  onSubmit,
  onClose,
}: {
  title: string;
  phrase: string;
  loading: boolean;
  error?: string | null;
  onSubmit: (typed: string) => void;
  onClose: () => void;
}) {
  // 입력 초안(서버 값 아님)
  const [typed, setTyped] = useState("");
  const ok = typed.trim() === phrase;
  // 연타 막기: loading 이 그려지기 전 두 번째 누름을 바로 막는다. 실패가 오면 다시 누를 수 있다
  const inFlight = useRef(false);
  useEffect(() => {
    if (error) inFlight.current = false;
  }, [error]);
  return (
    <Sheet open onClose={() => !loading && onClose()} title={title}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!ok || loading || inFlight.current) return;
          inFlight.current = true;
          onSubmit(typed.trim());
        }}
      >
        <label className="flex flex-col gap-2">
          <span className="text-[15px] text-ink [word-break:keep-all]">
            &lsquo;{phrase}&rsquo;를 그대로 입력해 주세요.
          </span>
          <input
            value={typed}
            autoComplete="off"
            onChange={(event) => setTyped(event.target.value)}
            className={`min-h-12 rounded-[14px] bg-surface px-4 text-[16px] text-ink shadow-card outline-none ${focusRing}`}
          />
        </label>
        {error && <ErrorInline message={error} />}
        <Button type="submit" variant="danger" loading={loading} disabled={!ok}>
          {title}
        </Button>
      </form>
    </Sheet>
  );
}
